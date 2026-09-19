"""Mood tags for tracks, one album per call, from the collector only.

The app stays a static page: tagging runs here with ANTHROPIC_API_KEY from
Actions secrets, never in the browser. The vocabulary lives in moods.json;
the model may only choose from it, and a reply carrying anything else, or
no parseable JSON, is retried once and then the album is left untagged for
the run. Tags are written as a "moods" list on each track in
data/tracks/<id>.json, and the row in releases.json carries the album's top
three moods by track count (ties by those tracks' plays) as "moods", with
how many tracks carry each as "moodsN". A row with a "moods" key (even
empty) is tagged and never touched again unless --retag is passed; a row
without one is picked up next time.

  python collector/moods.py daily                        # new albums only, capped (the daily workflow)
  python collector/moods.py backfill --cap N --workers 4 # the one-time backfill, dispatched until "moods complete"
  python collector/moods.py backfill --retag --cap N     # tag again albums that already carry moods
  python collector/moods.py derive                       # re-rank every tagged row's album moods, no API calls
  python collector/moods.py sample --vocab NEW.json --cap 14   # try a new vocabulary: a review file, catalog untouched
  python collector/moods.py batch-submit                  # a full retag in one Message Batch, at half price
  python collector/moods.py batch-collect                 # waits for it, applies it, records the spend

A vocabulary file carries a version. A row tagged by a vocabulary past the
first records it as "moodsV"; a row tagged by an older version counts as
untagged, so a new vocabulary retags the catalog without --retag and a
partly finished switch picks up where it stopped.

Every run appends its albums, tokens and dollar cost to moods-state.json,
which the workflows commit, so the spend is on the record.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect

MOODS_PATH = Path(__file__).resolve().parent / "moods.json"
STATE_PATH = Path(__file__).resolve().parent / "moods-state.json"
BATCH_PATH = Path(__file__).resolve().parent / "moods-batch.json"
SAMPLE_PATH = Path(__file__).resolve().parent / "moods-sample.json"
BATCH_DISCOUNT = 0.5                    # Message Batches bill half the standard token price
TRACKS_DIR = collect.DATA_PATH.parent / "tracks"
MODEL = "claude-haiku-4-5"
PRICE_IN, PRICE_OUT = 1.00, 5.00        # dollars per million tokens, Claude Haiku 4.5
DAILY_CAP = 40                          # albums a daily run may tag: a bad day cannot run up a bill
DAILY_WINDOW_DAYS = 30                  # the daily step tags albums first seen this recently
MAX_TAGS = 3
ALBUM_MOODS = 3                         # the row carries its album's top three moods, not every mood a track has
CHUNK_TRACKS = 100                      # tracks per call: about 14 output tokens a track keeps a reply near 1,500
RUNS_KEPT = 60


def load_vocab(path=MOODS_PATH):
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    return [(m["mood"], m.get("gloss", "")) for m in d["moods"]]


def vocab_version(path=MOODS_PATH):
    """The vocabulary's version; the first vocabulary carries none."""
    return int(json.loads(Path(path).read_text(encoding="utf-8")).get("version") or 1)


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


# a title that opens with its own track number ("8 - Mission Mode" on
# Pikmin's five-track selection): the model keyed replies by that number
# instead of the list's, so the prompt shows the title without it
_OWN_NUMBER = re.compile(r"^\s*\d{1,3}\s*[-.):]\s+")


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
        lines.append(f"{i}. {_OWN_NUMBER.sub('', t.get('title') or '')}")
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


def call_model(client, system, prompt, schema=None):
    """-> (reply text, input tokens, output tokens)."""
    response = client.messages.create(
        model=MODEL, max_tokens=16000, system=system,
        messages=[{"role": "user", "content": prompt}],
        output_config={"format": {"type": "json_schema", "schema": schema or SCHEMA}},
    )
    text = next((b.text for b in response.content if b.type == "text"), "")
    return text, response.usage.input_tokens, response.usage.output_tokens


def album_moods(tracks, terms):
    """The album's top ALBUM_MOODS moods: most tracks first, a tie going to
    the mood whose tracks have more plays, then to the vocabulary's order.
    -> (moods, counts), counts[i] being how many tracks carry moods[i]."""
    rank = {m: i for i, m in enumerate(terms)}
    counts, plays = {}, {}
    for t in tracks:
        n = collect._plays_num(t.get("plays")) or 0
        for m in t.get("moods") or []:
            if m in rank:
                counts[m] = counts.get(m, 0) + 1
                plays[m] = plays.get(m, 0) + n
    top = sorted(counts, key=lambda m: (-counts[m], -plays[m], rank[m]))[:ALBUM_MOODS]
    return top, [counts[m] for m in top]


def set_album_moods(r, tracks, terms, version=None):
    """The row's album-level moods from its tracks, and the vocabulary
    version that tagged them past the first. -> True when they changed."""
    top, n = album_moods(tracks, terms)
    changed = r.get("moods") != top or r.get("moodsN") != n
    r["moods"], r["moodsN"] = top, n
    if version and version > 1:
        r["moodsV"] = version
    return changed


def tag_album(client, r, tracks, vocab, system=None, call=call_model, version=None):
    """One album tagged in place: moods on its tracks, the album's top three
    on the row. -> {"ok": bool, "in": tokens, "out": tokens, "tries": n, "calls": n}.
    Long albums go in chunks of CHUNK_TRACKS, each its own call with the
    album's own track numbers. A reply the parser rejects is tried once
    more; a chunk rejected twice leaves the whole album as it was, to be
    picked up on a later run, so no album is ever half tagged."""
    system = system or system_prompt(vocab)
    terms = [m for m, _ in vocab]
    if call is call_model:
        call = partial(call_model, schema=schema_for(terms))  # the reply's enum is this vocabulary
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
    for i, t in enumerate(tracks, 1):
        moods = tags.get(i) or []
        if moods:
            t["moods"] = moods
        else:
            t.pop("moods", None)
    set_album_moods(r, tracks, terms, version)
    return {"ok": True, "in": used_in, "out": used_out, "tries": tries, "calls": calls}


def first_seen(r):
    return min((s.get("seenAt") or "9999") for s in r.get("sources") or []) if r.get("sources") else "9999"


def untagged(releases, tracks_dir, retag=False, version=1):
    """Rows with a tracklist and no moods yet, or moods from an older
    vocabulary: newest first within each medium, the mediums dealt in turn
    (game, film, tv), so a capped run spreads across all three and the
    backfill advances them together."""
    by_medium = {"game": [], "film": [], "tv": []}
    for r in releases:
        if r.get("retired") or not (r.get("tracksN") or 0) > 0:
            continue
        if "moods" in r and (r.get("moodsV") or 1) >= version and not retag:
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


def new_albums(releases, tracks_dir, now=None, days=DAILY_WINDOW_DAYS, version=1):
    """The daily step's set: untagged rows first seen within the window."""
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return [r for r in untagged(releases, tracks_dir, version=version) if first_seen(r) >= since]


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


def tag_rows(rows, tracks_dir, client, vocab, workers=1, log=print, call=call_model, version=None):
    """Tag each row, writing its tracks file as it lands. -> summary."""
    tracks_dir = Path(tracks_dir)
    system = system_prompt(vocab)
    summary = {"tagged": 0, "skipped": 0, "failed": 0, "inputTokens": 0, "outputTokens": 0, "retried": 0}

    def one(r):
        path = tracks_dir / f"{r['id']}.json"
        tracks = json.loads(path.read_text(encoding="utf-8"))
        try:
            res = tag_album(client, r, tracks, vocab, system, call, version=version)
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


def derive(data_path=None, tracks_dir=None, vocab=None, log=print):
    """Every tagged row's album moods ranked again from its tracks file, with
    no API call, for when the album rule changes. Untagged rows stay as they
    are. -> how many rows changed."""
    data_path = Path(data_path or collect.DATA_PATH)
    tracks_dir = Path(tracks_dir or TRACKS_DIR)
    terms = [m for m, _ in (vocab or load_vocab())]
    data = collect.load_data(data_path)
    seen = changed = 0
    for r in data["releases"]:
        path = tracks_dir / f"{r['id']}.json"
        if "moods" not in r or not path.exists():
            continue
        seen += 1
        changed += set_album_moods(r, json.loads(path.read_text(encoding="utf-8")), terms)
    if changed:
        data_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log(f"moods derive: {seen} tagged rows read, {changed} changed")
    return changed


def run(kind="daily", cap=DAILY_CAP, workers=1, retag=False, data_path=None, tracks_dir=None,
        state_path=None, client=None, vocab=None, now=None, log=print, call=call_model, vocab_path=None):
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
    vocab = vocab or load_vocab(vocab_path or MOODS_PATH)
    version = vocab_version(vocab_path or MOODS_PATH)
    data = collect.load_data(data_path)
    releases = data["releases"]
    pool = (new_albums(releases, tracks_dir, now, version=version) if kind == "daily"
            else untagged(releases, tracks_dir, retag, version=version))
    rows = pool[:cap]
    summary = tag_rows(rows, tracks_dir, client, vocab, workers=workers, log=log, call=call, version=version)
    remaining = (len(untagged(releases, tracks_dir, version=version)) if kind == "backfill"
                 else len(pool) - summary["tagged"])
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


def sample_rows(releases, tracks_dir, per_medium):
    """Albums people know, spread through each medium: every k-th of the 200
    most played with at least four tracks."""
    picks = []
    for med in ("game", "film", "tv"):
        rows = [r for r in releases if not r.get("retired") and (r.get("medium") or "game") == med
                and (r.get("tracksN") or 0) >= 4 and (Path(tracks_dir) / f"{r['id']}.json").exists()]
        rows.sort(key=lambda r: -(r.get("playsTotal") or 0))
        top = rows[:200]
        step = max(1, len(top) // max(1, per_medium))
        picks += top[::step][:per_medium]
    return picks


def run_sample(per_medium=14, vocab_path=MOODS_PATH, data_path=None, tracks_dir=None, out_path=None,
               state_path=None, client=None, workers=4, log=print, call=call_model):
    """A vocabulary tried on a few albums into a review file (each album's
    old and new moods, track by track), the catalog left exactly as it is."""
    data_path, tracks_dir = Path(data_path or collect.DATA_PATH), Path(tracks_dir or TRACKS_DIR)
    client = client if client is not None else make_client()
    if client is None:
        log("moods: ANTHROPIC_API_KEY not set, sample skipped")
        return None
    vocab, version = load_vocab(vocab_path), vocab_version(vocab_path)
    system = system_prompt(vocab)
    picks = sample_rows(collect.load_data(data_path)["releases"], tracks_dir, per_medium)

    def one(r):
        old_tracks = json.loads((tracks_dir / f"{r['id']}.json").read_text(encoding="utf-8"))
        row, tracks = copy.deepcopy(r), copy.deepcopy(old_tracks)
        try:
            res = tag_album(client, row, tracks, vocab, system, call, version=version)
        except Exception as e:
            res = {"ok": False, "in": 0, "out": 0, "why": str(e)}
        return r, row, old_tracks, tracks, res

    entries, tin, tout = [], 0, 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for r, row, old_tracks, tracks, res in pool.map(one, picks):
            tin, tout = tin + res["in"], tout + res["out"]
            entries.append({"id": r["id"], "album": r.get("albumTitle") or r["title"], "work": r.get("game"),
                            "medium": r.get("medium") or "game", "ok": res["ok"], "why": res.get("why"),
                            "old": r.get("moods"), "new": row.get("moods") if res["ok"] else None,
                            "newN": row.get("moodsN") if res["ok"] else None,
                            "tracks": [{"title": o.get("title"), "old": o.get("moods") or [], "new": n.get("moods") or []}
                                       for o, n in zip(old_tracks, tracks)]})
    spent = cost(tin, tout)
    Path(out_path or SAMPLE_PATH).write_text(json.dumps({"vocabVersion": version, "albums": entries}, indent=1,
                                                        ensure_ascii=False) + "\n", encoding="utf-8")
    state = load_state(state_path or STATE_PATH)
    state["inputTokens"] += tin
    state["outputTokens"] += tout
    state["cost"] = round(state["cost"] + spent, 4)
    state["runs"] = (state["runs"] + [{"at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "kind": "sample",
                                       "tagged": 0, "sampled": len(entries), "inputTokens": tin, "outputTokens": tout,
                                       "cost": round(spent, 4)}])[-RUNS_KEPT:]
    save_state(state, state_path or STATE_PATH)
    ok = sum(1 for e in entries if e["ok"])
    log(f"moods sample (vocabulary v{version}): {ok} of {len(entries)} albums tagged into the review file, "
        f"${spent:.4f}; the catalog is unchanged")
    return entries


def batch_requests(rows, tracks_dir, vocab):
    """One request per album, or per chunk of a long album. Custom ids stay
    short and plain (row ids can be Japanese); the index maps them back."""
    terms = [m for m, _ in vocab]
    system, schema = system_prompt(vocab), schema_for(terms)
    requests, index = [], {}
    for i, r in enumerate(rows):
        tracks = json.loads((Path(tracks_dir) / f"{r['id']}.json").read_text(encoding="utf-8"))
        for start, part in chunks(tracks):
            cid = f"a{i}-t{start}"
            index[cid] = [r["id"], start, len(part)]
            requests.append({"custom_id": cid, "params": {
                "model": MODEL, "max_tokens": 16000, "system": system,
                "messages": [{"role": "user", "content": album_prompt(r, part, start, len(tracks))}],
                "output_config": {"format": {"type": "json_schema", "schema": schema}}}})
    return requests, index


def batch_submit(vocab_path=MOODS_PATH, data_path=None, tracks_dir=None, batch_path=None, client=None,
                 cap=None, log=print):
    """Every album not yet tagged by this vocabulary, in one Message Batch."""
    data_path, tracks_dir = Path(data_path or collect.DATA_PATH), Path(tracks_dir or TRACKS_DIR)
    batch_path = Path(batch_path or BATCH_PATH)
    if batch_path.exists() and not json.loads(batch_path.read_text(encoding="utf-8")).get("applied"):
        log("moods batch: one is already submitted and not yet applied; collect it first")
        return None
    client = client if client is not None else make_client()
    if client is None:
        log("moods: ANTHROPIC_API_KEY not set, batch skipped")
        return None
    vocab, version = load_vocab(vocab_path), vocab_version(vocab_path)
    rows = untagged(collect.load_data(data_path)["releases"], tracks_dir, version=version)
    rows = rows[:cap] if cap else rows
    requests, index = batch_requests(rows, tracks_dir, vocab)
    batch = client.messages.batches.create(requests=requests)
    record = {"id": batch.id, "vocab": Path(vocab_path).name, "version": version,
              "submitted": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "albums": len(rows), "requests": len(requests), "applied": False, "index": index}
    batch_path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    log(f"moods batch {batch.id}: {len(rows)} albums in {len(requests)} requests submitted (vocabulary v{version})")
    return record


def batch_collect(data_path=None, tracks_dir=None, batch_path=None, state_path=None, client=None,
                  max_wait=5.5 * 3600, poll=60, log=print, sleep=time.sleep):
    """Wait for the submitted batch, then apply it: an album is tagged only
    when every one of its chunks came back and parsed; the rest keep their
    old moods and a later run tags them. The spend is recorded at batch price."""
    data_path, tracks_dir = Path(data_path or collect.DATA_PATH), Path(tracks_dir or TRACKS_DIR)
    batch_path = Path(batch_path or BATCH_PATH)
    if not batch_path.exists():
        log("moods batch: nothing submitted")
        return None
    record = json.loads(batch_path.read_text(encoding="utf-8"))
    if record.get("applied"):
        log(f"moods batch {record['id']}: already applied")
        return None
    client = client if client is not None else make_client()
    if client is None:
        log("moods: ANTHROPIC_API_KEY not set, collect skipped")
        return None
    waited = 0
    batch = client.messages.batches.retrieve(record["id"])
    while batch.processing_status != "ended":
        if waited >= max_wait:
            log(f"moods batch {record['id']}: still {batch.processing_status} after {waited // 60} minutes; collect again later")
            return None
        sleep(poll)
        waited += poll
        batch = client.messages.batches.retrieve(record["id"])
    vocab_path = Path(__file__).resolve().parent / record["vocab"]
    vocab, version = load_vocab(vocab_path), record["version"]
    terms = [m for m, _ in vocab]
    replies, tin, tout, lost = {}, 0, 0, Counter()
    for res in client.messages.batches.results(record["id"]):
        if res.result.type == "succeeded":
            msg = res.result.message
            replies[res.custom_id] = next((b.text for b in msg.content if b.type == "text"), "")
            tin += msg.usage.input_tokens
            tout += msg.usage.output_tokens
        else:
            lost[res.result.type] += 1
    by_row = {}
    for cid, (rid, start, n) in record["index"].items():
        by_row.setdefault(rid, []).append((cid, start, n))
    data = collect.load_data(data_path)
    rows = {r["id"]: r for r in data["releases"]}
    tagged = unparsed = 0
    for rid, parts in by_row.items():
        r, tags = rows.get(rid), {}
        for cid, start, n in parts:
            got = parse_reply(replies.get(cid), range(start, start + n), terms) if cid in replies else None
            if got is None:
                tags = None
                break
            tags.update(got)
        if r is None or tags is None:
            unparsed += r is not None and all(c in replies for c, _, _ in parts)
            continue
        path = tracks_dir / f"{rid}.json"
        tracks = json.loads(path.read_text(encoding="utf-8"))
        for i, t in enumerate(tracks, 1):
            if tags.get(i):
                t["moods"] = tags[i]
            else:
                t.pop("moods", None)
        set_album_moods(r, tracks, terms, version)
        path.write_text(json.dumps(tracks, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tagged += 1
    spent = cost(tin, tout) * BATCH_DISCOUNT
    remaining = len(untagged(data["releases"], tracks_dir, version=version))
    if tagged:
        data["updatedAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        data_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    summary = {"tagged": tagged, "skipped": unparsed, "failed": sum(lost.values()), "inputTokens": tin,
               "outputTokens": tout, "cost": spent}
    save_state(record_run(load_state(state_path or STATE_PATH), "batch", summary, remaining), state_path or STATE_PATH)
    record.update(applied=True, tagged=tagged, unparsed=unparsed, lost=dict(lost), cost=round(spent, 4))
    batch_path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    log(f"moods batch {record['id']}: {tagged} of {len(by_row)} albums tagged (vocabulary v{version}), "
        f"{unparsed} replies rejected, {sum(lost.values())} requests lost {dict(lost)}; "
        f"{tin} in / {tout} out tokens, ${spent:.4f} at batch price; {remaining} not yet on v{version}")
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kind", choices=["daily", "backfill", "derive", "sample", "batch-submit", "batch-collect"],
                    nargs="?", default="daily")
    ap.add_argument("--vocab", default=str(MOODS_PATH), help="the vocabulary file (sample, batch-submit, backfill)")
    ap.add_argument("--cap", type=int, default=None)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--retag", action="store_true", help="tag albums that already carry moods (backfill only)")
    args = ap.parse_args()
    if args.kind == "derive":
        derive()
        sys.exit(0)
    if args.kind == "sample":
        run_sample(per_medium=args.cap or 14, vocab_path=args.vocab, workers=max(args.workers, 4))
        sys.exit(0)
    if args.kind == "batch-submit":
        batch_submit(vocab_path=args.vocab, cap=args.cap)
        sys.exit(0)
    if args.kind == "batch-collect":
        batch_collect()
        sys.exit(0)
    cap = args.cap if args.cap is not None else (DAILY_CAP if args.kind == "daily" else 500)
    run(args.kind, cap=cap, workers=args.workers, retag=args.retag and args.kind == "backfill", vocab_path=args.vocab)
