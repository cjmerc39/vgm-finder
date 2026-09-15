"""Mood tags for tracks, one album per call, from the collector only.

The app stays a static page: tagging runs here with ANTHROPIC_API_KEY from
Actions secrets, never in the browser. The vocabulary lives in moods.json;
the model may only choose from it, and a reply carrying anything else, or
no parseable JSON, is retried once and then the album is left untagged for
the run. Tags are written as a "moods" list on each track in
data/tracks/<id>.json and as their union on the row in releases.json. A
row with a "moods" key (even empty) is tagged and never touched again
unless --retag is passed; a row without one is picked up next time.

  python collector/moods.py daily                        # new albums only, capped (the daily workflow)
  python collector/moods.py backfill --cap N --workers 4 # the one-time backfill, dispatched until "moods complete"
  python collector/moods.py backfill --retag --cap N     # tag again albums that already carry moods

Every run appends its albums, tokens and dollar cost to moods-state.json,
which the workflows commit, so the spend is on the record.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect

MOODS_PATH = Path(__file__).resolve().parent / "moods.json"
STATE_PATH = Path(__file__).resolve().parent / "moods-state.json"
TRACKS_DIR = collect.DATA_PATH.parent / "tracks"
MODEL = "claude-haiku-4-5"
PRICE_IN, PRICE_OUT = 1.00, 5.00        # dollars per million tokens, Claude Haiku 4.5
DAILY_CAP = 40                          # albums a daily run may tag: a bad day cannot run up a bill
DAILY_WINDOW_DAYS = 30                  # the daily step tags albums first seen this recently
MAX_TAGS = 3
CHUNK_TRACKS = 100                      # tracks per call: about 14 output tokens a track keeps a reply near 1,500
RUNS_KEPT = 60


def load_vocab(path=MOODS_PATH):
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    return [(m["mood"], m.get("gloss", "")) for m in d["moods"]]


def system_prompt(vocab):
    terms = "\n".join(f"- {m}: {g}" for m, g in vocab)
    return (
        "You tag soundtrack tracks with moods for a listener's playlist builder.\n"
        "Judge each track from the work it scores, its medium and year, the composers, the genres, "
        "and the track's title and position. Choose only from this vocabulary, exactly as written:\n"
        f"{terms}\n"
        f"Give each track 1 to {MAX_TAGS} moods that a listener would feel, most fitting first. "
        "When the title gives no real clue and the album's character does not settle it, give that track no moods "
        "rather than a guess. Licensed songs and cues alike are tagged by how they sound. "
        "Reply with JSON only, one entry per track, in order, keyed by the track number given."
    )


def album_prompt(r, tracks, start=1, total=None):
    """The album and its tracks, numbered from start. A chunk of a long
    album says which stretch it is, so the numbers stay the album's own."""
    medium = {"game": "video game", "film": "film", "tv": "television series"}.get(r.get("medium") or "game", "work")
    lines = [f"Album: {r.get('albumTitle') or r.get('title')}",
             f"Work: {r.get('game') or r.get('title')} ({medium}, {(r.get('date') or '')[:4] or 'year unknown'})"]
    if r.get("composers"):
        lines.append("Composers: " + ", ".join(r["composers"]))
    if r.get("genres"):
        lines.append("Genres: " + ", ".join(r["genres"]))
    total = total or len(tracks)
    end = start + len(tracks) - 1
    lines.append(f"Tracks {start} to {end} of {total}:" if total > len(tracks) else "Tracks:")
    for i, t in enumerate(tracks, start):
        lines.append(f"{i}. {t.get('title') or ''}")
    return "\n".join(lines)


def chunks(tracks, size=None):
    """(start, tracks) stretches of at most size tracks, evenly cut, so no
    single reply has to carry more than about 1,500 output tokens."""
    size = size or CHUNK_TRACKS
    n = len(tracks)
    parts = max(1, -(-n // size))
    out, at = [], 0
    for k in range(parts):
        take = n // parts + (1 if k < n % parts else 0)
        out.append((at + 1, tracks[at:at + take]))
        at += take
    return out


def schema_for(vocab_terms):
    """The reply's JSON schema: the mood words are an enum of the
    vocabulary, so the model cannot emit a word outside it."""
    return {
        "type": "object",
        "properties": {
            "tracks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"n": {"type": "integer"},
                                   "moods": {"type": "array", "items": {"type": "string", "enum": list(vocab_terms)}}},
                    "required": ["n", "moods"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["tracks"],
        "additionalProperties": False,
    }


SCHEMA = schema_for([m["mood"] for m in json.loads(MOODS_PATH.read_text(encoding="utf-8"))["moods"]])


def parse_reply_why(text, numbers, vocab_terms):
    """The model's reply as ({track number: [moods]}, "") or (None, why) when
    it is not JSON, not the expected shape, names a track outside the
    numbers asked about (an int means 1 to that many), or uses a mood
    outside the vocabulary. Order is kept as given."""
    valid = range(1, numbers + 1) if isinstance(numbers, int) else numbers
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return None, "not JSON"
    items = data.get("tracks") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return None, "no tracks list"
    allowed = set(vocab_terms)
    out = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("n"), int) or not isinstance(item.get("moods"), list):
            return None, f"bad entry {json.dumps(item)[:60]}"
        n, moods = item["n"], item["moods"]
        if n not in valid:
            return None, f"track {n} not asked about"
        kept = []
        for m in moods:
            if not isinstance(m, str):
                return None, f"track {n}: mood is not a string"
            m = m.strip().lower()
            if m not in allowed:
                return None, f"track {n}: '{m}' is outside the vocabulary"  # free text is rejected
            if m not in kept:
                kept.append(m)
        out[n] = kept[:MAX_TAGS]
    return out, ""


def parse_reply(text, numbers, vocab_terms):
    return parse_reply_why(text, numbers, vocab_terms)[0]


def make_client():
    """An Anthropic client, or None when no key is set (warned, never fatal)."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    import anthropic  # lazy: tests run without the SDK
    return anthropic.Anthropic(max_retries=3)


def call_model(client, system, prompt):
    """-> (reply text, input tokens, output tokens)."""
    response = client.messages.create(
        model=MODEL, max_tokens=16000, system=system,
        messages=[{"role": "user", "content": prompt}],
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
    )
    text = next((b.text for b in response.content if b.type == "text"), "")
    return text, response.usage.input_tokens, response.usage.output_tokens


def tag_album(client, r, tracks, vocab, system=None, call=call_model):
    """One album tagged in place: moods on its tracks, their union on the
    row. -> {"ok": bool, "in": tokens, "out": tokens, "tries": n, "calls": n}.
    Long albums go in chunks of CHUNK_TRACKS, each its own call with the
    album's own track numbers. A reply the parser rejects is tried once
    more; a chunk rejected twice leaves the whole album as it was, to be
    picked up on a later run, so no album is ever half tagged."""
    system = system or system_prompt(vocab)
    terms = [m for m, _ in vocab]
    used_in = used_out = calls = 0
    tries = 1
    tags = {}
    for start, part in chunks(tracks):
        prompt = album_prompt(r, part, start, len(tracks))
        numbers = range(start, start + len(part))
        got, why, text = None, "", ""
        for attempt in (1, 2):
            text, tin, tout = call(client, system, prompt)
            used_in += tin
            used_out += tout
            calls += 1
            got, why = parse_reply_why(text, numbers, terms)
            if got is not None:
                break
            tries = 2
        if got is None:
            return {"ok": False, "in": used_in, "out": used_out, "tries": 2, "calls": calls,
                    "why": why, "reply": (text or "")[:160]}
        tags.update(got)
    counts = {}
    for i, t in enumerate(tracks, 1):
        moods = tags.get(i) or []
        if moods:
            t["moods"] = moods
            for m in moods:
                counts[m] = counts.get(m, 0) + 1
        else:
            t.pop("moods", None)
    r["moods"] = sorted(counts, key=lambda m: (-counts[m], terms.index(m)))  # commonest first, the list's order breaks ties
    return {"ok": True, "in": used_in, "out": used_out, "tries": tries, "calls": calls}


def first_seen(r):
    return min((s.get("seenAt") or "9999") for s in r.get("sources") or []) if r.get("sources") else "9999"


def untagged(releases, tracks_dir, retag=False):
    """Rows with a tracklist and no moods yet: newest first within each
    medium, the mediums dealt in turn (game, film, tv), so a capped run
    spreads across all three and the backfill advances them together."""
    by_medium = {"game": [], "film": [], "tv": []}
    for r in releases:
        if r.get("retired") or not (r.get("tracksN") or 0) > 0:
            continue
        if "moods" in r and not retag:
            continue
        if not (Path(tracks_dir) / f"{r['id']}.json").exists():
            continue
        by_medium.setdefault(r.get("medium") or "game", []).append(r)
    for rows in by_medium.values():
        rows.sort(key=lambda r: (r.get("date") or "", first_seen(r)), reverse=True)
    out = []
    lanes = [rows for rows in by_medium.values() if rows]
    while lanes:
        for rows in lanes:
            out.append(rows.pop(0))
        lanes = [rows for rows in lanes if rows]
    return out


def new_albums(releases, tracks_dir, now=None, days=DAILY_WINDOW_DAYS):
    """The daily step's set: untagged rows first seen within the window."""
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return [r for r in untagged(releases, tracks_dir) if first_seen(r) >= since]


def cost(tin, tout):
    return tin / 1e6 * PRICE_IN + tout / 1e6 * PRICE_OUT


def load_state(path=STATE_PATH):
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(d, dict):
            return {"tagged": int(d.get("tagged", 0)), "inputTokens": int(d.get("inputTokens", 0)),
                    "outputTokens": int(d.get("outputTokens", 0)), "cost": float(d.get("cost", 0.0)),
                    "runs": list(d.get("runs", []))}
    except (OSError, ValueError):
        pass
    return {"tagged": 0, "inputTokens": 0, "outputTokens": 0, "cost": 0.0, "runs": []}


def save_state(state, path=STATE_PATH):
    Path(path).write_text(json.dumps(state, indent=1) + "\n", encoding="utf-8")


def tag_rows(rows, tracks_dir, client, vocab, workers=1, log=print, call=call_model):
    """Tag each row, writing its tracks file as it lands. -> summary."""
    tracks_dir = Path(tracks_dir)
    system = system_prompt(vocab)
    summary = {"tagged": 0, "skipped": 0, "failed": 0, "inputTokens": 0, "outputTokens": 0, "retried": 0}

    def one(r):
        path = tracks_dir / f"{r['id']}.json"
        tracks = json.loads(path.read_text(encoding="utf-8"))
        try:
            res = tag_album(client, r, tracks, vocab, system, call)
        except Exception as e:  # a transport failure: the row stays for a later run
            log(f"  fail {r['id']}: {e}")
            return r, None, None
        if res["ok"]:
            path.write_text(json.dumps(tracks, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return r, res, tracks

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for r, res, _ in pool.map(one, rows):
            if res is None:
                summary["failed"] += 1
                continue
            summary["inputTokens"] += res["in"]
            summary["outputTokens"] += res["out"]
            summary["retried"] += res["tries"] > 1
            if res["ok"]:
                summary["tagged"] += 1
            else:
                summary["skipped"] += 1
                log(f"  skip {r['id']}: rejected twice, last because {res.get('why')}: {res.get('reply')!r}")
    summary["cost"] = cost(summary["inputTokens"], summary["outputTokens"])
    return summary


def record_run(state, kind, summary, remaining, now=None):
    state["tagged"] += summary["tagged"]
    state["inputTokens"] += summary["inputTokens"]
    state["outputTokens"] += summary["outputTokens"]
    state["cost"] = round(state["cost"] + summary["cost"], 4)
    state["runs"] = (state["runs"] + [{"at": (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                       "kind": kind, "tagged": summary["tagged"], "skipped": summary["skipped"],
                                       "failed": summary["failed"], "inputTokens": summary["inputTokens"],
                                       "outputTokens": summary["outputTokens"], "cost": round(summary["cost"], 4),
                                       "remaining": remaining}])[-RUNS_KEPT:]
    return state


def run(kind="daily", cap=DAILY_CAP, workers=1, retag=False, data_path=None, tracks_dir=None,
        state_path=None, client=None, vocab=None, now=None, log=print, call=call_model):
    """The daily step (kind daily: new albums only) or a backfill run (kind
    backfill: any untagged album), both capped. -> summary or None when the
    key is missing."""
    data_path = Path(data_path or collect.DATA_PATH)
    tracks_dir = Path(tracks_dir or TRACKS_DIR)
    state_path = Path(state_path or STATE_PATH)
    client = client if client is not None else make_client()
    if client is None:
        log("moods: ANTHROPIC_API_KEY not set, tagging skipped")
        return None
    vocab = vocab or load_vocab()
    data = collect.load_data(data_path)
    releases = data["releases"]
    pool = new_albums(releases, tracks_dir, now) if kind == "daily" else untagged(releases, tracks_dir, retag)
    rows = pool[:cap]
    summary = tag_rows(rows, tracks_dir, client, vocab, workers=workers, log=log, call=call)
    remaining = len(untagged(releases, tracks_dir)) if kind == "backfill" else len(pool) - summary["tagged"]
    summary["remaining"] = remaining
    if summary["tagged"]:
        data["updatedAt"] = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
        data_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    state = record_run(load_state(state_path), kind, summary, remaining, now)
    save_state(state, state_path)
    log(f"moods ({kind}): {summary['tagged']} albums tagged, {summary['skipped']} skipped, {summary['failed']} failed, "
        f"{summary['retried']} retried; {summary['inputTokens']} in / {summary['outputTokens']} out tokens, "
        f"${summary['cost']:.4f} this run, ${state['cost']:.2f} to date; {remaining} untagged remaining")
    if kind == "backfill":
        log("moods complete" if remaining == 0 else "moods in progress: dispatch again")
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kind", choices=["daily", "backfill"], nargs="?", default="daily")
    ap.add_argument("--cap", type=int, default=None)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--retag", action="store_true", help="tag albums that already carry moods (backfill only)")
    args = ap.parse_args()
    cap = args.cap if args.cap is not None else (DAILY_CAP if args.kind == "daily" else 500)
    run(args.kind, cap=cap, workers=args.workers, retag=args.retag and args.kind == "backfill")
