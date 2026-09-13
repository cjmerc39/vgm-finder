"""Screen re-walk (MATCHER-FIX-SPEC Phase 2). Dispatched by hand through
.github/workflows/rewalk.yml, one step at a time:

  evaluate  Capped runs with a committed cursor. Walks every film and show
            at the current vote bars, then sweeps for anything the walk
            missed (a title that crossed a page boundary while it ran, a row
            the daily run added below the bars), searches YouTube Music
            exactly as the collector does, and writes the accepted
            candidates to one shard file per run. No row changes.
  resolve   One offline pass over every shard. Hands albums out across the
            whole catalog at once, with game-owned albums reserved, compares
            the outcome with every film and TV row, and writes plan.json plus
            the review: corrections, additions, orphans, unverified rows, and
            the weakMatch and songsAlbum counts. Then stops for sign-off.
            "resolve-partial" writes plan-partial.json from whatever has been
            evaluated so far, without moving the step on.
  apply     After sign-off. Applies plan.json to data/releases.json,
            re-checking every action against the data as it is by then.

The cursor lives in collector/rewalk/state.json rather than
backfill-state.json, whose loader rebuilds the file from a fixed key list;
the backfill checked sets are replaced with the evaluated titles at apply.
Game rows are never read for matching or modified.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backfill
import collect

REWALK_DIR = collect.ROOT / "collector" / "rewalk"
TRACKS_DIR = collect.DATA_PATH.parent / "tracks"
EVALUATE_PHASES = ("film", "tv", "sweep", "pending")
PHASES = EVALUATE_PHASES + ("evaluated", "resolved", "applied")
KINDS = {"film": ("movie", "FILM_BAR", "filmPage"), "tv": ("tv", "TV_BAR", "tvPage")}
SRC = {"film": backfill.TMDB_SRC_FILM, "tv": backfill.TMDB_SRC_TV}
_KEEP = ("title", "url", "art", "rule", "klass", "credited", "extra", "gap", "worded",
         "weak", "season", "composers", "rank", "artists", "plays")
_REAL_KEYS = ("credited composer", "exact title", "fewer extra words", "closer year")


# ---------------- state and shards ----------------

def load_state(folder=REWALK_DIR):
    try:
        d = json.loads((Path(folder) / "state.json").read_text(encoding="utf-8"))
        if isinstance(d, dict) and d.get("phase") in PHASES:
            return {"phase": d["phase"], "filmPage": int(d.get("filmPage", 1)),
                    "tvPage": int(d.get("tvPage", 1)), "shard": int(d.get("shard", 0)),
                    "pending": [list(p) for p in d.get("pending", [])]}
    except (OSError, ValueError):
        pass
    return {"phase": "film", "filmPage": 1, "tvPage": 1, "shard": 0, "pending": []}


def save_state(state, folder=REWALK_DIR):
    Path(folder).mkdir(parents=True, exist_ok=True)
    (Path(folder) / "state.json").write_text(json.dumps(state, indent=1) + "\n", encoding="utf-8")


def load_evaluations(folder=REWALK_DIR):
    """Every shard, oldest first, keyed (medium, TMDb id). A later record for
    the same title replaces an earlier one."""
    out = {}
    for path in sorted(Path(folder).glob("eval-*.json")):
        for rec in json.loads(path.read_text(encoding="utf-8")):
            out[(rec["medium"], rec["id"])] = rec
    return out


def tmdb_id_of(row):
    for s in row.get("sources", []):
        m = re.search(r"themoviedb\.org/(?:movie|tv)/(\d+)", s.get("url", ""))
        if m:
            return m.group(1)
    return None


def row_slot(row):
    """The resolver slot a film or TV row occupies."""
    tid = tmdb_id_of(row)
    if tid is None:
        return None
    if row.get("medium") == "film":
        return ("film", tid)
    m = re.search(r" Season (\d+) Soundtrack$", row.get("title", ""))
    return ("tv", tid, int(m.group(1)) if m else None)


# ---------------- evaluate ----------------

def details_entry(medium, tid):
    """A discover-shaped entry from a title's details, for the sweep."""
    kind = "movie" if medium == "film" else "tv"
    d = dict(collect._tmdb_get(f"{kind}/{tid}"))
    d["genre_ids"] = [g["id"] for g in d.get("genres") or [] if g.get("id") is not None]
    if medium == "tv":
        d["_seasons"] = {str(x["season_number"]): x.get("air_date")
                         for x in d.get("seasons") or [] if x.get("season_number")}
    return d


def evaluate_title(medium, entry, worn, resolve, album_fn):
    """One title searched and judged exactly as the collector does. Keeps
    every accepted candidate, and the verdict on any album a row already
    wears: that verdict is what later tells a correction from an
    unverified row."""
    kind = "movie" if medium == "film" else "tv"
    tid = str(entry["id"])
    names, aliases = collect.tmdb_credits(kind, entry["id"])
    data = {"composers": {tid: names}, "aliases": {tid: aliases}}
    if medium == "tv":
        data["seasons"] = {tid: entry["_seasons"] if "_seasons" in entry
                           else collect.tmdb_seasons(entry["id"])}
    info = collect.film_info(entry, data) if medium == "film" else collect.tv_info(entry, data)
    rec = {"medium": medium, "id": tid, "name": info["name"], "original": info["original"],
           "date": info["date"], "years": info["years"], "composers": info["composers"],
           "aliases": info["aliases"], "genres": collect._tmdb_genres(entry, collect._tmdb_genre_map(kind)),
           "poster": entry.get("poster_path"), "votes": entry.get("vote_count"),
           "accepted": [], "seen": {}}
    if medium == "tv":
        rec["seasons"] = info["seasons"]
    if not info["name"] or not info["date"]:
        rec["skipped"] = "no title or date on TMDb"
        return rec
    for c in collect.screen_classify(collect.screen_search(resolve, info), info, album_fn):
        if c["accepted"]:
            rec["accepted"].append({k: c.get(k) for k in _KEEP})
        if c.get("url") in worn:
            rec["seen"][c["url"]] = "accepted" if c["accepted"] else c["verdict"]
    return rec


def _discover(medium, page):
    kind, bar_name, _ = KINDS[medium]
    return collect._tmdb_get(f"discover/{kind}", page=page,
                             **{"vote_count.gte": getattr(backfill, bar_name),
                                "sort_by": "vote_count.desc"})


def sweep_pending(releases, done):
    """Every title at the bars right now plus every film and TV row, minus
    what is already evaluated. Catches titles that crossed a page boundary
    while the walk ran, rows the daily run added below the bars, and the 43
    titles the first walk looked up but never recorded."""
    pending, queued = [], set()
    for medium in ("film", "tv"):
        page, pages = 1, 1
        while page <= pages:
            d = _discover(medium, page)
            pages = min(int(d.get("total_pages") or 1), 500)
            for x in d.get("results") or []:
                key = (medium, str(x["id"]))
                if key not in done and key not in queued:
                    queued.add(key)
                    pending.append(list(key))
            page += 1
    for r in releases:
        if r.get("medium") in ("film", "tv"):
            key = (r["medium"], tmdb_id_of(r))
            if key[1] and key not in done and key not in queued:
                queued.add(key)
                pending.append(list(key))
    return pending


def evaluate(releases, state, folder=REWALK_DIR, resolve=None, album_fn=None, cap=None):
    """One capped evaluate run. Shard and cursor are written together on
    every exit, a failure included, and a page cursor only moves once every
    title on the page is recorded, so a stopped run replays cleanly."""
    resolve = resolve or collect.ytm_resolve
    album_fn = album_fn or collect.ytm_album
    cap = backfill.YTM_CAP if cap is None else cap
    done = set(load_evaluations(folder))
    worn = {r["ytmAlbumUrl"] for r in releases
            if r.get("medium") in ("film", "tv") and r.get("ytmAlbumUrl")}
    calls = [0]

    def counted(fn):
        def wrapper(*args, **kwargs):
            calls[0] += 1
            return fn(*args, **kwargs)
        return wrapper

    search, fetch_album = counted(resolve), counted(album_fn)
    records = []

    def run_title(medium, entry):
        rec = evaluate_title(medium, entry, worn, search, fetch_album)
        records.append(rec)
        done.add((medium, rec["id"]))

    stopped = None
    try:
        while calls[0] < cap and state["phase"] in EVALUATE_PHASES:
            phase = state["phase"]
            if phase in KINDS:
                page_key = KINDS[phase][2]
                d = _discover(phase, state[page_key])
                results = d.get("results") or []
                page_done = True
                for entry in results:
                    if (phase, str(entry["id"])) in done:
                        continue
                    if calls[0] >= cap:
                        page_done = False
                        break
                    run_title(phase, entry)
                if page_done:
                    if not results or state[page_key] >= min(int(d.get("total_pages") or 1), 500):
                        state["phase"] = "tv" if phase == "film" else "sweep"
                    else:
                        state[page_key] += 1
            elif phase == "sweep":
                state["pending"] = sweep_pending(releases, done)
                state["phase"] = "pending"
            else:
                while state["pending"] and calls[0] < cap:
                    medium, tid = state["pending"][0]
                    if (medium, tid) not in done:
                        try:
                            entry = details_entry(medium, tid)
                        except requests.HTTPError as exc:
                            if exc.response is None or exc.response.status_code != 404:
                                raise
                            records.append({"medium": medium, "id": tid, "gone": True,
                                            "accepted": [], "seen": {}})
                            done.add((medium, tid))
                        else:
                            run_title(medium, entry)
                    state["pending"].pop(0)
                if not state["pending"]:
                    state["phase"] = "evaluated"
    except Exception as exc:
        stopped = repr(exc)
        print(f"::warning::re-walk evaluate stopped early, progress kept: {exc}")
    finally:
        if records:
            state["shard"] += 1
            Path(folder).mkdir(parents=True, exist_ok=True)
            (Path(folder) / f"eval-{state['shard']:04d}.json").write_text(
                json.dumps(records, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
        save_state(state, folder)
    films = sum(1 for k in done if k[0] == "film")
    shows = sum(1 for k in done if k[0] == "tv")
    print(f"re-walk evaluate: {len(records)} titles this run, {calls[0]} YouTube Music calls, "
          f"{films} films and {shows} shows evaluated, phase {state['phase']}"
          + (f", {len(state['pending'])} pending" if state["phase"] == "pending" else ""))
    if state["phase"] == "evaluated":
        print("evaluation complete: dispatch resolve next")
    else:
        print("evaluation in progress: dispatch evaluate again")
    return records, stopped


# ---------------- resolve ----------------

def real_key(c):
    return (not c["credited"], collect._CLASS_RANK[c["klass"]], c["extra"],
            c["gap"] if c["gap"] is not None else 99)


def _why_outranked(win, cur):
    if cur:
        for label, a, b in zip(_REAL_KEYS, real_key(win), real_key(cur)):
            if a != b:
                return f"outranked on {label}"
    return "outranked"


def _album(c):
    return {k: c.get(k) for k in _KEEP}


def _label(slot, rows_by_slot):
    row = rows_by_slot.get(slot)
    return row["id"] if row else "new " + "/".join(str(x) for x in slot)


def plan_rewalk(releases, evaluations):
    """The whole-catalog resolution and its comparison with today's rows.
    A row's current album wins any dead heat on the real ranking keys, so a
    correct row is never churned onto an equally good album; a row is
    corrected only on evidence (its album now fails a rule, is outranked,
    or belongs to another title) and is left unverified when today's search
    did not show its album at all."""
    game = {r["ytmAlbumUrl"]: r["id"] for r in releases
            if (r.get("medium") or "game") == "game" and r.get("ytmAlbumUrl")}
    rows_by_slot, duplicates, no_slot = {}, [], []
    for r in releases:
        if r.get("medium") not in ("film", "tv") or r.get("retired"):
            continue
        slot = row_slot(r)
        if slot is None:
            no_slot.append(r)
        elif slot in rows_by_slot:
            duplicates.append({"row": r["id"], "slot": list(slot), "sameSlotAs": rows_by_slot[slot]["id"]})
        else:
            rows_by_slot[slot] = r

    slots = {}
    for (medium, tid), rec in sorted(evaluations.items()):
        if rec.get("gone") or rec.get("skipped"):
            continue
        cands = []
        for c in rec["accepted"]:
            slot = ("film", tid) if medium == "film" else ("tv", tid, c["season"])
            row = rows_by_slot.get(slot)
            if row and row.get("ytmAlbumUrl") == c["url"]:
                c = dict(c, worded=True, rank=-1)  # the incumbent takes a dead heat
            cands.append(c)
        slots.update(collect.screen_slots({"medium": medium, "id": tid}, cands))
    winners, conflicts = collect.resolve_screen(slots, reserved=set(game))
    holder = {c["url"]: slot for slot, c in winners.items()}

    corrections, orphans, unverified, unchanged = [], [], [], []
    for r in no_slot:
        unverified.append({"row": r["id"], "album": {"title": r.get("albumTitle"), "url": r.get("ytmAlbumUrl")},
                           "reason": "row has no TMDb source"})
    for slot, row in sorted(rows_by_slot.items(), key=lambda kv: kv[1]["id"]):
        rec = evaluations.get((slot[0], slot[1]))
        cur = row.get("ytmAlbumUrl")
        win = winners.get(slot)
        base = {"row": row["id"], "slot": list(slot), "album": {"title": row.get("albumTitle"), "url": cur}}
        if rec is None or rec.get("gone") or rec.get("skipped"):
            reason = "title not evaluated" if rec is None else ("gone from TMDb" if rec.get("gone") else rec["skipped"])
            unverified.append(dict(base, reason=reason))
            continue
        if win and cur and win["url"] == cur:
            unchanged.append(dict(base, weakMatch=bool(win.get("weak")), songsAlbum=collect.is_songs_album(win)))
            continue
        seen = rec["seen"].get(cur) if cur else None
        if cur and cur in game:
            reason = f"album also worn by game row {game[cur]}"
        elif not cur:
            reason = "row had no album"
        elif seen is None:
            unverified.append(dict(base, reason="current album not in today's search",
                                   wouldBe=win["title"] if win else None))
            continue
        elif seen == "accepted":
            other = holder.get(cur)
            if other and other != slot:
                reason = f"album belongs to {_label(other, rows_by_slot)}"
            elif win:
                reason = _why_outranked(win, next((c for c in rec["accepted"] if c["url"] == cur), None))
            else:
                unverified.append(dict(base, reason="album accepted but left unassigned"))
                continue
        else:
            reason = seen  # the rule that now rejects the album the row wears
        if win:
            corrections.append(dict(base, newAlbum=_album(win), reason=reason,
                                    weakMatch=bool(win.get("weak")), songsAlbum=collect.is_songs_album(win)))
        else:
            orphans.append(dict(base, reason=reason))

    additions = []
    for slot, win in sorted(winners.items(), key=lambda kv: [str(x) for x in kv[0]]):
        if slot in rows_by_slot:
            continue
        rec = evaluations[(slot[0], slot[1])]
        additions.append({"slot": list(slot), "album": _album(win), "weakMatch": bool(win.get("weak")),
                          "songsAlbum": collect.is_songs_album(win),
                          "title": {k: rec.get(k) for k in ("medium", "id", "name", "date", "seasons",
                                                            "genres", "poster", "votes")}})

    def rate(medium, slots_with):
        ids = {tid for (m, tid), rec in evaluations.items()
               if m == medium and not rec.get("gone") and not rec.get("skipped")}
        hits = {s[1] for s in slots_with if s[0] == medium}
        return {"titles": len(ids), "withAlbum": len(ids & hits),
                "rate": round(len(ids & hits) / len(ids), 3) if ids else None}

    final = unchanged + corrections + additions
    plan = {
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "counts": {
            "corrections": len(corrections), "additions": len(additions), "orphans": len(orphans),
            "unverified": len(unverified), "unchanged": len(unchanged),
            "duplicateSlotRows": len(duplicates), "albumClaimsSettled": len(conflicts),
            "weakMatch": sum(1 for x in final if x["weakMatch"]),
            "songsAlbum": sum(1 for x in final if x["songsAlbum"]),
            "tvSeasonRowsBefore": sum(1 for s in rows_by_slot if s[0] == "tv"),
            "tvSeasonRowsAfter": sum(1 for s in rows_by_slot if s[0] == "tv") - sum(
                1 for o in orphans if o["slot"][0] == "tv") + sum(1 for a in additions if a["slot"][0] == "tv"),
        },
        "hitRates": {"before": {"film": rate("film", rows_by_slot), "tv": rate("tv", rows_by_slot)},
                     "after": {"film": rate("film", winners), "tv": rate("tv", winners)}},
        "corrections": corrections, "additions": additions, "orphans": orphans,
        "unverified": unverified, "duplicateSlotRows": duplicates,
        "unchanged": [{"row": u["row"], "album": u["album"], "weakMatch": u["weakMatch"],
                       "songsAlbum": u["songsAlbum"]} for u in unchanged],
        "conflicts": [{"album": url, "winner": _label(w, rows_by_slot), "loser": _label(lo, rows_by_slot)}
                      for url, w, lo in conflicts],
    }
    return plan


def print_review(plan, sample=30):
    c = plan["counts"]
    print("===== re-walk review =====")
    for k in ("corrections", "additions", "orphans", "unverified", "unchanged", "weakMatch", "songsAlbum",
              "duplicateSlotRows", "albumClaimsSettled", "tvSeasonRowsBefore", "tvSeasonRowsAfter"):
        print(f"{k}: {c[k]}")
    print("hit rates:", json.dumps(plan["hitRates"]))
    for name in ("corrections", "orphans", "unverified", "additions"):
        items = plan[name]
        print(f"--- {name} ({len(items)}), first {min(sample, len(items))}")
        for x in items[:sample]:
            if name == "additions":
                print(f"   {x['slot']} {x['title']['name']!r} <- {x['album']['title']!r}"
                      f"{' [weak]' if x['weakMatch'] else ''}{' [songs]' if x['songsAlbum'] else ''}")
            elif name == "corrections":
                print(f"   {x['row']}: {x['album']['title']!r} -> {x['newAlbum']['title']!r} ({x['reason']})")
            else:
                print(f"   {x['row']}: {x['album']['title']!r} ({x['reason']})")


# ---------------- apply ----------------

def _set_flag(row, key, on):
    if on and not row.get(key):
        row[key] = True
        return True
    if not on and key in row:
        row.pop(key)
        return True
    return False


def addition_item(a):
    t, al, slot = a["title"], a["album"], a["slot"]
    medium = slot[0]
    n = slot[2] if medium == "tv" else None
    name = t["name"]
    item = {"title": f"{name} Season {n} Soundtrack" if n else f"{name} Soundtrack",
            "albumTitle": al["title"], "medium": medium, "game": name,
            "composers": list(al.get("composers") or []), "genres": t.get("genres"),
            "url": f"https://www.themoviedb.org/{'movie' if medium == 'film' else 'tv'}/{t['id']}",
            "date": ((t.get("seasons") or {}).get(str(n)) if n else None) or t["date"],
            "ytmAlbumUrl": al["url"],
            "art": al.get("art") or (f"{collect.TMDB_IMG}{t['poster']}" if t.get("poster") else None)}
    if a.get("weakMatch"):
        item["weakMatch"] = True
    if a.get("songsAlbum"):
        item["songsAlbum"] = True
    return item


def apply_plan(releases, plan, evaluations, backfill_state_path, tracks_dir, seen_at):
    """Apply a reviewed plan. Each action is re-checked against the rows as
    they are now; anything that moved since resolve is skipped and listed
    as stale rather than forced. Nothing is ever deleted, so every TRACK
    number stays where it is."""
    by_id = {r["id"]: r for r in releases}
    out = {"retired": [], "corrected": [], "added": [], "flagged": 0, "stale": []}

    def stale(kind, ref, why):
        out["stale"].append({"kind": kind, "ref": ref, "why": why})

    # orphans first: retiring a row frees its album for the row it belongs to
    for o in plan["orphans"]:
        r = by_id.get(o["row"])
        if not r or r.get("retired") or r.get("ytmAlbumUrl") != o["album"]["url"]:
            stale("orphan", o["row"], "row changed since resolve")
            continue
        r["retired"] = True
        out["retired"].append(o["row"])

    # corrections: every old album comes off before any new one goes on, so
    # albums moving along a chain of rows never trip the one-album rule midway
    ready = []
    for c in plan["corrections"]:
        r = by_id.get(c["row"])
        if not r or r.get("retired") or r.get("ytmAlbumUrl") != c["album"]["url"]:
            stale("correction", c["row"], "row changed since resolve")
            continue
        ready.append((r, c, r.get("ytmAlbumUrl")))
        r["ytmAlbumUrl"] = None
    for r, c, old in ready:
        new = c["newAlbum"]
        if new["url"] in collect.claimed_albums(releases):
            r["ytmAlbumUrl"] = old
            stale("correction", c["row"], "new album already worn by another row")
            continue
        r["ytmAlbumUrl"] = new["url"]
        r["albumTitle"] = new["title"]
        if new.get("art"):
            r["art"] = new["art"]
        if new.get("composers"):
            r["composers"] = list(new["composers"])
        for key in ("tracks", "tracksN", "playsTotal", "ytmPlaylistId"):
            r.pop(key, None)  # the next tracklist fill fetches the new album's tracks
        track_file = Path(tracks_dir) / f"{r['id']}.json"
        if track_file.exists():
            track_file.unlink()
        _set_flag(r, "weakMatch", c["weakMatch"])
        _set_flag(r, "songsAlbum", c["songsAlbum"])
        out["corrected"].append({"row": r["id"], "old": c["album"]["title"], "new": new["title"]})

    # additions go through merge like any collected item
    wanted = {}
    for a in plan["additions"]:
        if a["album"]["url"] in collect.claimed_albums(releases):
            stale("addition", a["slot"], "album already worn by another row")
            continue
        item = addition_item(a)
        wanted[item["ytmAlbumUrl"]] = a["slot"]
        before = {x["id"] for x in releases}
        collect.merge(releases, [item], SRC[item["medium"]], seen_at)
        new_rows = [x for x in releases if x["id"] not in before]
        if new_rows and new_rows[0].get("ytmAlbumUrl") == item["ytmAlbumUrl"]:
            out["added"].append(new_rows[0]["id"])
        else:
            stale("addition", a["slot"], "merge folded it into an existing row")

    # flags on rows whose album did not change
    for u in plan["unchanged"]:
        r = by_id.get(u["row"])
        if not r or r.get("retired") or r.get("ytmAlbumUrl") != u["album"]["url"]:
            stale("flag", u["row"], "row changed since resolve")
            continue
        out["flagged"] += _set_flag(r, "weakMatch", u["weakMatch"]) | _set_flag(r, "songsAlbum", u["songsAlbum"])

    # one album, one row among film and TV rows (two game-era pairs predate this)
    owners = {}
    for r in releases:
        url = r.get("ytmAlbumUrl")
        if not url or r.get("retired"):
            continue
        prior = owners.get(url)
        if prior and (r.get("medium") in ("film", "tv") or prior[1] in ("film", "tv")):
            raise RuntimeError(f"one album, one row broken: {url} on {prior[0]} and {r['id']}")
        owners.setdefault(url, (r["id"], r.get("medium") or "game"))

    # the checked sets become the re-walked titles
    bstate = backfill.load_state(backfill_state_path)
    bstate["tmdbFilmChecked"] = sorted(int(k[1]) for k in evaluations if k[0] == "film")
    bstate["tmdbTvChecked"] = sorted(int(k[1]) for k in evaluations if k[0] == "tv")
    Path(backfill_state_path).write_text(json.dumps(bstate, indent=2) + "\n", encoding="utf-8")
    return out


# ---------------- entry point ----------------

def main(argv=None, data_path=None, folder=None, backfill_state_path=None, tracks_dir=None):
    argv = sys.argv[1:] if argv is None else argv
    step = argv[0] if argv else "evaluate"
    data_path = Path(data_path or collect.DATA_PATH)
    folder = Path(folder or REWALK_DIR)
    data = collect.load_data(data_path)
    releases = data["releases"]
    state = load_state(folder)

    if step == "evaluate":
        if state["phase"] not in EVALUATE_PHASES:
            print(f"evaluation already complete (phase {state['phase']})")
            return 0
        evaluate(releases, state, folder)
        return 0

    if step in ("resolve", "resolve-partial"):
        partial = step == "resolve-partial"
        if not partial and state["phase"] not in ("evaluated", "resolved"):
            print(f"::error::evaluation not complete (phase {state['phase']}); use resolve-partial to peek")
            return 1
        plan = plan_rewalk(releases, load_evaluations(folder))
        name = "plan-partial.json" if partial else "plan.json"
        (folder / name).write_text(json.dumps(plan, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        if not partial:
            state["phase"] = "resolved"
            save_state(state, folder)
        print_review(plan)
        print("review stop: nothing has been applied" + (" (partial plan)" if partial else ""))
        return 0

    if step == "apply":
        if state["phase"] != "resolved":
            print(f"::error::nothing to apply (phase {state['phase']})")
            return 1
        plan = json.loads((folder / "plan.json").read_text(encoding="utf-8"))
        seen_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        out = apply_plan(releases, plan, load_evaluations(folder),
                         backfill_state_path or backfill.STATE_PATH, tracks_dir or TRACKS_DIR, seen_at)
        data["updatedAt"] = seen_at
        data_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (folder / "applied.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n",
                                             encoding="utf-8")
        state["phase"] = "applied"
        save_state(state, folder)
        print(f"re-walk applied: {len(out['corrected'])} corrected, {len(out['added'])} added, "
              f"{len(out['retired'])} retired, {out['flagged']} flags changed, {len(out['stale'])} stale")
        for s in out["stale"]:
            print(f"   stale {s['kind']} {s['ref']}: {s['why']}")
        return 0

    print(f"::error::unknown step {step!r}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
