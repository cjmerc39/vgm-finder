"""Screen re-walk (MATCHER-FIX-SPEC Phase 2). Dispatched by hand through
.github/workflows/rewalk.yml, one step at a time:

  evaluate  Capped runs with a committed cursor. Walks every film and show
            at the current vote bars, then sweeps for anything the walk
            missed (a title that crossed a page boundary while it ran, a row
            the daily run added below the bars), searches YouTube Music
            exactly as the collector does, and writes the album results,
            the album pages read and the accepted candidates to one shard
            file per run. Last, every album a row
            wears that its own title turned away on a year condition is
            re-read from the album page and judged again. No row changes.
  resolve   One offline pass over every shard. Judges every title again
            from its stored results under the current matcher, then hands
            albums out across the
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
EVALUATE_PHASES = ("film", "tv", "sweep", "pending", "verify")
PHASES = EVALUATE_PHASES + ("evaluated", "resolved", "applied")
KINDS = {"film": ("movie", "FILM_BAR", "filmPage"), "tv": ("tv", "TV_BAR", "tvPage")}
SRC = {"film": backfill.TMDB_SRC_FILM, "tv": backfill.TMDB_SRC_TV}
_KEEP = ("title", "url", "art", "rule", "klass", "credited", "extra", "gap", "worded",
         "weak", "season", "volume", "year", "seasonFrom", "composers", "rank", "artists", "plays",
         "trackStats", "yearFrom")
_REAL_KEYS = ("credited composer", "exact title", "fewer extra words", "closer year")
YTM_ALBUM = "https://music.youtube.com/browse/"


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
    m = re.search(r"(?: Season (\d+))?(?: Vol\. (\d+))? Soundtrack$", row.get("title", ""))
    season, volume = (m.group(1), m.group(2)) if m else (None, None)
    return ("tv", tid, int(season) if season else None, int(volume) if volume else None)


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
    rec["albums"] = {}
    rec["results"] = [_trim_result(r) for r in collect.screen_search(resolve, info)
                      if r.get("resultType") == "album" and r.get("browseId")]
    return judge_record(rec, worn, _album_store(rec, album_fn))


def _trim_result(r):
    """A search result as screen_classify reads it, and nothing more."""
    thumbs = sorted((t for t in r.get("thumbnails") or [] if t.get("url")), key=lambda t: t.get("width") or 0)
    return {"resultType": "album", "browseId": r["browseId"], "title": r.get("title") or "",
            "year": r.get("year"), "thumbnails": thumbs[-1:],
            "artists": [{"name": a["name"]} for a in r.get("artists") or [] if a.get("name")]}


def _trim_album(album):
    """An album page as the plays check, the year fill and track_stats read it."""
    if not album:
        return None
    return {"title": album.get("title"), "year": album.get("year"),
            "artists": [{"name": a["name"]} for a in album.get("artists") or [] if a.get("name")],
            "tracks": [{"title": t.get("title"), "views": t.get("views"),
                        "artists": [{"name": a["name"]} for a in t.get("artists") or [] if a.get("name")]}
                       for t in album.get("tracks") or []]}


def _album_store(rec, album_fn):
    """Album pages read for a title, fetched once and kept in its record so
    resolve can judge the title again without YouTube Music. With no fetch
    function an album never read raises, so a later judgment reports it
    unknown rather than empty."""
    store = rec.setdefault("albums", {})

    def get(browse_id):
        if browse_id not in store:
            if album_fn is None:
                raise KeyError(browse_id)
            store[browse_id] = _trim_album(album_fn(browse_id))
        return store[browse_id]
    return get


def judge_record(rec, worn, album_fn):
    """A title's stored search results judged under the current matcher: the
    accepted candidates, song-compilation evidence, and the verdict on every
    album a row wears. Evaluate runs it on a fresh search and resolve runs
    it again on the stored one, so a matcher fix needs no second walk. An
    album whose year the search got wrong (yearVerified) is judged with the
    year on its album page."""
    medium = rec["medium"]
    info = {k: rec.get(k) for k in ("medium", "name", "original", "years", "composers", "aliases")}
    verified = rec.get("yearVerified") or []
    results = []
    for r in rec.get("results") or []:
        if YTM_ALBUM + r["browseId"] in verified:
            try:
                r = dict(r, year=(album_fn(r["browseId"]) or {}).get("year") or r.get("year"))
            except Exception:
                pass
        results.append(r)
    judged = collect.screen_classify(results, info, album_fn)
    # song-compilation evidence: where no candidate for a slot credits the
    # composer, read the top candidate's tracklist once. YouTube Music
    # credits most studio scores to Various Artists at album level, so the
    # track artists are the only honest signal.
    groups = {}
    for c in judged:
        if c["accepted"]:
            groups.setdefault((c["season"], c.get("volume")) if medium == "tv" else None, []).append(c)
    for group in groups.values():
        if any(c["credited"] for c in group):
            continue
        top = min(group, key=collect._rank_key)
        try:
            top["trackStats"] = track_stats(album_fn(top["url"].rsplit("/", 1)[1]),
                                            (info["composers"] or []) + (info["aliases"] or []))
        except Exception:
            pass  # no stats: the track-based songs call stays unknown
    rec["accepted"], rec["seen"] = [], {}
    for c in judged:
        if c["accepted"]:
            rec["accepted"].append({k: c.get(k) for k in _KEEP})
        if c.get("url") in worn:
            rec["seen"][c["url"]] = "accepted" if c["accepted"] else c["verdict"]
    return rec


def track_stats(album, names):
    """Tracks, tracks with a named artist other than Various Artists, the
    distinct named artists, and tracks a credited composer performs or is
    named on. Classical labels put the composer in the title and the
    orchestra in the artists: "Zimmer: Dear Clarice" (Hannibal)."""
    if not names:
        # TMDb names no composer for most shows: the album's own credited
        # artists stand in (Fringe's Chris Tilton), never Various Artists
        names = [a.get("name") for a in (album or {}).get("artists") or []
                 if a.get("name") and a["name"].lower() not in ("various artists", "various")]
    named = composer = 0
    distinct = set()
    tracks = (album or {}).get("tracks") or []
    for t in tracks:
        artists = [a.get("name") for a in t.get("artists") or [] if a.get("name")]
        real = [a for a in artists if a.lower() != "various artists"]
        if real:
            named += 1
            distinct.update(real)
            title = t.get("title") or ""
            byline = [title.split(":", 1)[0]] if ":" in title else []
            composer += bool(names) and collect._credited(real + byline, names)
    return {"tracks": len(tracks), "named": named, "distinct": len(distinct), "composerTracks": composer}


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
            elif phase == "verify":
                current = load_evaluations(folder)
                current.update({(x["medium"], x["id"]): x for x in records})
                verified = verify_worn_years(releases, current, fetch_album)
                records.extend(verified)
                print(f"re-walk verify: {len(verified)} titles had a worn album re-read for its year")
                state["phase"] = "evaluated"
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
                    state["phase"] = "verify"
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


def _worn(releases):
    return {r["ytmAlbumUrl"] for r in releases
            if r.get("medium") in ("film", "tv") and r.get("ytmAlbumUrl")}


def verify_worn_years(releases, evaluations, album_fn):
    """A row is never retired or corrected on a year one search got wrong.
    Every album a row wears that its own title turned away on a condition
    involving the year is read from its album page, marked yearVerified,
    and the title judged again with the page's year. Returns the updated
    title records; a later shard record supersedes the earlier one, so
    nothing already written is edited."""
    worn = _worn(releases)
    out = {}
    for r in releases:
        url = r.get("ytmAlbumUrl")
        if r.get("medium") not in ("film", "tv") or r.get("retired") or not url:
            continue
        slot = row_slot(r)
        key = (slot[0], slot[1]) if slot else None
        rec = out.get(key) or evaluations.get(key)
        verdict = rec["seen"].get(url) if rec else None
        if (not isinstance(verdict, str) or "year" not in verdict or "results" not in rec
                or url in (rec.get("yearVerified") or [])):
            continue
        rec = dict(rec, albums=dict(rec.get("albums") or {}),
                   yearVerified=list(rec.get("yearVerified") or []) + [url])
        store = _album_store(rec, album_fn)
        store(url.rsplit("/", 1)[1])  # read the page now, so the judgment has its year
        out[key] = judge_record(rec, worn, store)
    return list(out.values())


def rejudge(releases, evaluations):
    """Every stored title judged again under the current matcher, offline.
    Records written before results were stored pass through unchanged."""
    worn = _worn(releases)
    out = {}
    for key, rec in evaluations.items():
        if rec.get("gone") or rec.get("skipped") or "results" not in rec:
            out[key] = rec
            continue
        rec = dict(rec, albums=dict(rec.get("albums") or {}))
        out[key] = judge_record(rec, worn, _album_store(rec, None))
    return out


# ---------------- resolve ----------------

def songs_by_tracks(c):
    """The track-based songs call: True, False, or None when the album's
    tracks were never read. At least three distinct named track artists
    and the composer on fewer than half of the named tracks. Albums whose
    every track says Various Artists carry no evidence and count as score."""
    if c.get("credited"):
        return False
    s = c.get("trackStats")
    if not s:
        return None
    if not s["named"]:
        return False
    return s["distinct"] >= 3 and s["composerTracks"] * 2 < s["named"]


def _songs(c):
    by_tracks = songs_by_tracks(c)
    return {"songsAlbum": bool(by_tracks), "songsAlbumLiteral": collect.is_songs_album(c),
            "songsUnknown": by_tracks is None}


def _weak_artist_ok(c, rec):
    """The plays-only path is for albums credited to Various Artists or to
    the work itself (Infinity Train, The Intouchables), Disney included beside
    its cast (High School Musical). A bare title by any
    other act is a cover: the Royal Philharmonic's Bohemian Rhapsody, a
    dance act's Frozen."""
    artists = c.get("artists") or []
    names = [collect._screen_base(n) for n in (rec.get("name"), rec.get("original")) if n]
    return bool(artists) and all(
        a.lower() in ("various artists", "disney") or any(n and n in collect._screen_base(a) for n in names)
        for a in artists)


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

    # every TV row moves to the slot its own album fills (season and volume
    # from the title, or a volume's season from its release year) and takes
    # that slot's id and title: CJ's volume decision, re-id'd this once. A row
    # whose target another row keeps stays put and is listed as blocked.
    moved = {}
    for slot, r in rows_by_slot.items():
        if slot[0] != "tv":
            continue
        rec = evaluations.get(("tv", slot[1])) or {}
        own = next((c for c in rec.get("accepted", []) if c["url"] == r.get("ytmAlbumUrl")), None)
        if own is None:
            continue
        want, how = collect.screen_slot({"medium": "tv", "id": slot[1], "seasons": rec.get("seasons")}, own)
        if want != slot:
            moved[r["id"]] = (slot, want, how)
    taken = {slot: r for slot, r in rows_by_slot.items() if r["id"] not in moved}
    pending, placed, progress = sorted(moved.items()), {}, True
    while pending and progress:
        progress = False
        for item in list(pending):
            rid, (old, want, how) = item
            if want not in taken:
                taken[want] = rows_by_slot[old]
                placed[rid] = (old, want, how)
                pending.remove(item)
                progress = True
    blocked = []
    for rid, (old, want, how) in pending:
        blocked.append({"row": rid, "wants": list(want), "heldBy": taken[want]["id"]})
        if old in taken:
            duplicates.append({"row": rid, "slot": list(old), "sameSlotAs": taken[old]["id"]})
        else:
            taken[old] = rows_by_slot[old]
    reids = []
    for rid, (old, want, how) in sorted(placed.items()):
        r = taken[want]
        title = collect.screen_row_title(evaluations[("tv", want[1])]["name"], want[2], want[3])
        reids.append({"row": rid, "newId": "tv-" + collect.slugify(title), "title": title,
                      "from": list(old), "slot": list(want), "seasonFrom": how,
                      "album": {"title": r.get("albumTitle"), "url": r.get("ytmAlbumUrl")}})
    rows_by_slot = taken

    slots, weak_dropped = {}, []
    for (medium, tid), rec in sorted(evaluations.items()):
        if rec.get("gone") or rec.get("skipped"):
            continue
        cands = []
        title_info = {"medium": medium, "id": tid, "seasons": rec.get("seasons")}
        for c in rec["accepted"]:
            if c.get("weak") and not _weak_artist_ok(c, rec):
                weak_dropped.append({"title": rec["name"], "album": c["title"], "artists": c.get("artists")})
                continue
            slot = collect.screen_slot(title_info, c)[0]
            row = rows_by_slot.get(slot)
            if row and row.get("ytmAlbumUrl") == c["url"]:
                c = dict(c, worded=True, rank=-1)  # the incumbent takes a dead heat
            cands.append(c)
        slots.update(collect.screen_slots(title_info, cands))
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
            unchanged.append(dict(base, weakMatch=bool(win.get("weak")), credited=bool(win.get("credited")),
                                  artists=win.get("artists"), rule=win.get("rule"),
                                  seasonFrom=win.get("seasonFrom"), **_songs(win)))
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
                                    weakMatch=bool(win.get("weak")), **_songs(win)))
        else:
            orphans.append(dict(base, reason=reason))

    additions = []
    for slot, win in sorted(winners.items(), key=lambda kv: [str(x) for x in kv[0]]):
        if slot in rows_by_slot:
            continue
        rec = evaluations[(slot[0], slot[1])]
        additions.append({"slot": list(slot), "album": _album(win), "weakMatch": bool(win.get("weak")),
                          **_songs(win),
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
            "unverified": len(unverified), "unchanged": len(unchanged), "reids": len(reids),
            "reidsBlocked": len(blocked),
            "duplicateSlotRows": len(duplicates), "albumClaimsSettled": len(conflicts),
            "weakMatch": sum(1 for x in final if x["weakMatch"]),
            "songsAlbum": sum(1 for x in final if x["songsAlbum"]),
            "songsAlbumLiteral": sum(1 for x in final if x["songsAlbumLiteral"]),
            "songsAlbumUnknown": sum(1 for x in final if x["songsUnknown"]),
            "weakDroppedByArtistGuard": len(weak_dropped),
            "yearFromAlbumPage": sum(1 for c in winners.values() if c.get("yearFrom")),
            "tvSeasonRowsBefore": sum(1 for s in rows_by_slot if s[0] == "tv"),
            "tvSeasonRowsAfter": sum(1 for s in rows_by_slot if s[0] == "tv") - sum(
                1 for o in orphans if o["slot"][0] == "tv") + sum(1 for a in additions if a["slot"][0] == "tv"),
        },
        "hitRates": {"before": {"film": rate("film", rows_by_slot), "tv": rate("tv", rows_by_slot)},
                     "after": {"film": rate("film", winners), "tv": rate("tv", winners)}},
        "reids": reids, "reidsBlocked": blocked,
        "corrections": corrections, "additions": additions, "orphans": orphans,
        "unverified": unverified, "duplicateSlotRows": duplicates, "weakDropped": weak_dropped,
        "unchanged": [{k: u[k] for k in ("row", "slot", "album", "weakMatch", "songsAlbum", "songsAlbumLiteral",
                                         "credited", "artists", "rule", "seasonFrom")}
                      for u in unchanged],
        "conflicts": [{"album": url, "winner": _label(w, rows_by_slot), "loser": _label(lo, rows_by_slot)}
                      for url, w, lo in conflicts],
    }
    return plan


def print_review(plan, sample=30):
    c = plan["counts"]
    print("===== re-walk review =====")
    for k in ("corrections", "additions", "orphans", "unverified", "unchanged", "reids", "reidsBlocked", "weakMatch",
              "weakDroppedByArtistGuard", "yearFromAlbumPage", "songsAlbum", "songsAlbumLiteral",
              "songsAlbumUnknown",
              "duplicateSlotRows", "albumClaimsSettled", "tvSeasonRowsBefore", "tvSeasonRowsAfter"):
        print(f"{k}: {c[k]}")
    print("hit rates:", json.dumps(plan["hitRates"]))
    print(f"--- re-ids ({len(plan.get('reids', []))})")
    for x in plan.get("reids", [])[:sample]:
        print(f"   {x['row']} -> {x['newId']} ({x['seasonFrom']}; {x['album']['title']!r})")
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


def addition_item(a, songs_policy="tracks"):
    t, al, slot = a["title"], a["album"], a["slot"]
    medium = slot[0]
    n, v = (slot[2], slot[3]) if medium == "tv" else (None, None)
    name = t["name"]
    item = {"title": collect.screen_row_title(name, n, v),
            "albumTitle": al["title"], "medium": medium, "game": name,
            "composers": list(al.get("composers") or []), "genres": t.get("genres"),
            "url": f"https://www.themoviedb.org/{'movie' if medium == 'film' else 'tv'}/{t['id']}",
            "date": ((t.get("seasons") or {}).get(str(n)) if n else None) or t["date"],
            "ytmAlbumUrl": al["url"],
            "art": al.get("art") or (f"{collect.TMDB_IMG}{t['poster']}" if t.get("poster") else None)}
    if a.get("weakMatch"):
        item["weakMatch"] = True
    if a.get("songsAlbumLiteral" if songs_policy == "literal" else "songsAlbum"):
        item["songsAlbum"] = True
    return item


def apply_plan(releases, plan, evaluations, backfill_state_path, tracks_dir, seen_at,
               songs_policy="tracks"):
    """Apply a reviewed plan. Each action is re-checked against the rows as
    they are now; anything that moved since resolve is skipped and listed
    as stale rather than forced. Nothing is ever deleted, so every TRACK
    number stays where it is."""
    by_id = {r["id"]: r for r in releases}
    out = {"reids": [], "retired": [], "corrected": [], "added": [], "flagged": 0, "stale": []}

    def stale(kind, ref, why):
        out["stale"].append({"kind": kind, "ref": ref, "why": why})

    # re-ids first (CJ's volume decision, this once). A row keeps its place in
    # the file, so its TRACK number, and takes the id and title of the slot
    # its album fills; its tracklist file moves with it. A move waits until
    # its new id is free, so chains settle in any order; a move that never
    # frees up keeps its id and takes only the title.
    movers = []
    for t in plan.get("reids", []):
        r = by_id.get(t["row"])
        if not r or r.get("retired") or r.get("ytmAlbumUrl") != t["album"]["url"]:
            stale("reid", t["row"], "row changed since resolve")
            continue
        movers.append((r, t))
    remap, progress = {}, True
    while movers and progress:
        progress = False
        ids_now = {x["id"] for x in releases}
        for item in list(movers):
            r, t = item
            old = r["id"]
            if t["newId"] != old and t["newId"] in ids_now:
                continue
            r["title"], r["id"] = t["title"], t["newId"]
            ids_now.discard(old)
            ids_now.add(t["newId"])
            remap[t["row"]] = t["newId"]
            track = Path(tracks_dir) / f"{old}.json"
            if track.exists() and old != t["newId"]:
                track.replace(Path(tracks_dir) / f"{t['newId']}.json")
            out["reids"].append({"row": t["row"], "newId": t["newId"], "title": t["title"]})
            movers.remove(item)
            progress = True
    for r, t in movers:
        r["title"] = t["title"]
        stale("reid", t["row"], f"id {t['newId']} stays taken; title changed, id kept")
    by_id = {r["id"]: r for r in releases}

    def row_of(rid):
        return by_id.get(remap.get(rid, rid))

    # orphans first: retiring a row frees its album for the row it belongs to
    for o in plan["orphans"]:
        r = row_of(o["row"])
        if not r or r.get("retired") or r.get("ytmAlbumUrl") != o["album"]["url"]:
            stale("orphan", o["row"], "row changed since resolve")
            continue
        r["retired"] = True
        out["retired"].append(o["row"])

    # corrections: every old album comes off before any new one goes on, so
    # albums moving along a chain of rows never trip the one-album rule midway
    ready = []
    for c in plan["corrections"]:
        r = row_of(c["row"])
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
        _set_flag(r, "songsAlbum", c["songsAlbumLiteral" if songs_policy == "literal" else "songsAlbum"])
        out["corrected"].append({"row": r["id"], "old": c["album"]["title"], "new": new["title"]})

    # additions go through merge like any collected item
    wanted = {}
    for a in plan["additions"]:
        if a["album"]["url"] in collect.claimed_albums(releases):
            stale("addition", a["slot"], "album already worn by another row")
            continue
        item = addition_item(a, songs_policy)
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
        r = row_of(u["row"])
        if not r or r.get("retired") or r.get("ytmAlbumUrl") != u["album"]["url"]:
            stale("flag", u["row"], "row changed since resolve")
            continue
        songs = u["songsAlbumLiteral" if songs_policy == "literal" else "songsAlbum"]
        out["flagged"] += _set_flag(r, "weakMatch", u["weakMatch"]) | _set_flag(r, "songsAlbum", songs)

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
        plan = plan_rewalk(releases, rejudge(releases, load_evaluations(folder)))
        name = "plan-partial.json" if partial else "plan.json"
        (folder / name).write_text(json.dumps(plan, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        if not partial:
            state["phase"] = "resolved"
            save_state(state, folder)
        print_review(plan)
        print("review stop: nothing has been applied" + (" (partial plan)" if partial else ""))
        return 0

    if step in ("apply", "apply-literal"):
        if state["phase"] != "resolved":
            print(f"::error::nothing to apply (phase {state['phase']})")
            return 1
        plan = json.loads((folder / "plan.json").read_text(encoding="utf-8"))
        seen_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        out = apply_plan(releases, plan, load_evaluations(folder),
                         backfill_state_path or backfill.STATE_PATH, tracks_dir or TRACKS_DIR, seen_at,
                         songs_policy="literal" if step == "apply-literal" else "tracks")
        data["updatedAt"] = seen_at
        data_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (folder / "applied.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n",
                                             encoding="utf-8")
        state["phase"] = "applied"
        save_state(state, folder)
        print(f"re-walk applied: {len(out['reids'])} re-id'd, {len(out['corrected'])} corrected, "
              f"{len(out['added'])} added, "
              f"{len(out['retired'])} retired, {out['flagged']} flags changed, {len(out['stale'])} stale")
        for s in out["stale"]:
            print(f"   stale {s['kind']} {s['ref']}: {s['why']}")
        return 0

    print(f"::error::unknown step {step!r}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
