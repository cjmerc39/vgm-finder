"""Titles you are waiting for, searched again every day.

A film or show whose soundtrack is not on YT Music yet (Spider-Man 3,
Heroes, Castlevania 2017) leaves no row, and nothing revisits it: the daily
window has moved on and the backfill walks each vote band once. This keeps
a short list of such titles in collector/wanted.json and searches every one
again on each run, exactly as the daily leg searches its window, with the
same title gate and one-album-one-row guard. The run an album finally
appears the row is added by itself, its tracklist is read, and the entry is
stamped `got`, so it is never searched again.

An unattended check is stricter than a leg in one way: an album matched on
plays alone, with no composer in common, is reported and left alone rather
than taken. For a title that has gone years without a soundtrack that
match is the likeliest wrong answer (the Castlevania show's search finds
the Konami game's album), and a real one can be pinned in
screen-overrides.json.

One entry is one TMDb title:
  {"medium": "tv", "tmdb": "1639", "name": "Heroes", "asked": "2026-09-19"}
and gains `checked`, `checks`, and, when it lands, `got` and `rows`. The
stored `name` is a guard: a title whose TMDb record reads as something else
is reported and left alone, so a mistyped id never quietly watches the
wrong film. A title that has since gained a row another way is stamped
`got` without a search. Screen titles only; a game's album is found by the
game legs, which walk every day.

  python collector/check_wanted.py --add tv/1639 --add film/559   # ask for a title
  python collector/check_wanted.py --dry-run                      # search, write nothing
  python collector/check_wanted.py                                # the daily step
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect
import rewalk

WANTED_PATH = collect.ROOT / "collector" / "wanted.json"
TRACKS_DIR = collect.DATA_PATH.parent / "tracks"


def load_wanted(path=WANTED_PATH):
    if not Path(path).exists():
        return {"titles": []}
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    return {"titles": [t for t in d.get("titles") or []
                       if isinstance(t, dict) and t.get("medium") in ("film", "tv") and t.get("tmdb")]}


def save_wanted(wanted, path=WANTED_PATH):
    Path(path).write_text(json.dumps(wanted, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def waiting(wanted):
    return [t for t in wanted["titles"] if not t.get("got")]


def rows_for(releases, medium, tid):
    """Visible rows for a title that wear an album."""
    return [r["id"] for r in releases if not r.get("retired") and r.get("medium") == medium
            and rewalk.tmdb_id_of(r) == str(tid) and (r.get("ytmAlbumUrl") or "")]


def _fold(name):
    return collect._numfold(collect.normalize_title(name or ""))


def _same_title(stored, entry):
    """The TMDb record still reads as the title that was asked for, with or
    without a studio's name in front: TMDb calls the show Marvel's Luke
    Cage, and the list may well say Luke Cage."""
    want = _fold(stored)
    if not want:
        return True
    names = [entry.get("title"), entry.get("name"), entry.get("original_title"), entry.get("original_name")]
    forms = {f for n in names if n for f in (_fold(n), collect.without_studio(_fold(n), folded=True)) if f}
    return want in forms or collect.without_studio(want, folded=True) in forms


def bundle(medium, entry):
    """The parser bundle for one title, as the daily leg's page would carry it."""
    kind = "movie" if medium == "film" else "tv"
    tid = str(entry["id"])
    names, aliases = collect.tmdb_credits(kind, tid)
    data = {"results": [entry], "genres": collect._tmdb_genre_map(kind),
            "composers": {tid: names}, "aliases": {tid: aliases}}
    if medium == "tv":
        data["seasons"] = {tid: entry.get("_seasons") or collect.tmdb_seasons(tid)}
    return data


def search(medium, tid, resolve=None, album_fn=None, overrides=None, details=None):
    """One wanted title searched as the daily leg searches its window.
    -> (merge items, the TMDb entry). No accepted album means no items."""
    entry = (details or rewalk.details_entry)(medium, tid)
    items, _ = collect._screen_batch_data(bundle(medium, entry), resolve or collect.ytm_resolve,
                                          medium, album_fn or collect.ytm_album, None, overrides)
    return items, entry


def _winnowed(items, releases, name, log):
    """The albums a wanted title may actually take -> (items, why none).
    An unattended check is stricter than a leg: an album matched on plays
    alone (no composer in common) is the likeliest wrong answer for a title
    that has gone years without one, and the Castlevania show's search
    finds the Konami game's album, so a weak match is reported and left for
    a pin. An album another row already wears is never taken either."""
    owner = {r["ytmAlbumUrl"]: r["id"] for r in releases if r.get("ytmAlbumUrl") and not r.get("retired")}
    keep, why = [], None
    for i in items:
        held = owner.get(i.get("ytmAlbumUrl"))
        if held:
            why = f"{i['albumTitle']} is already worn by {held}"
            log(f"  {name}: {why}, nothing to add")
        elif i.get("weakMatch"):
            why = f"{i['albumTitle']} matches on plays alone"
            log(f"  {name}: {why}, not taken; pin it in screen-overrides.json if it is right")
        else:
            keep.append(i)
    return keep, (None if keep else why)


def check(releases, wanted, seen_at, today=None, only=None, dry_run=False, resolve=None, album_fn=None,
          details=None, tracks=True, log=print):
    """Every waiting title searched, and a row added for each album that wins.
    -> {"landed": [(entry, [row ids])], "waiting": n, "skipped": [(entry, why)]}"""
    today = today or date.today().isoformat()
    overrides = collect.load_screen_overrides()
    landed, skipped = [], []
    for t in waiting(wanted):
        medium, tid = t["medium"], str(t["tmdb"])
        name = t.get("name") or tid
        if only and tid not in only:
            continue
        have = rows_for(releases, medium, tid)
        if have:  # it arrived another way: the daily leg, a pin, a re-walk
            if not dry_run:
                t["got"], t["rows"] = today, have
            landed.append((t, have))
            log(f"  {name}: already has a row ({', '.join(have)})")
            continue
        try:
            items, entry = search(medium, tid, resolve, album_fn, overrides, details)
        except Exception as e:
            skipped.append((t, f"lookup failed: {e}"))
            log(f"::warning::wanted: {name} ({medium} {tid}) not searched: {e}")
            continue
        if not _same_title(t.get("name"), entry):
            skipped.append((t, f"TMDb {medium} {tid} is {entry.get('title') or entry.get('name')!r}"))
            log(f"::warning::wanted: {t.get('name')!r} does not match TMDb {medium} {tid} "
                f"({entry.get('title') or entry.get('name')!r}); fix the id in wanted.json")
            continue
        if not dry_run:
            t["checked"], t["checks"] = today, int(t.get("checks") or 0) + 1
        items, refused = _winnowed(items, releases, name, log)
        if not items:
            if refused:
                skipped.append((t, refused))
            else:
                log(f"  {name}: still nothing on YT Music")
            continue
        if dry_run:
            landed.append((t, [i["albumTitle"] for i in items]))
            log(f"  {name}: would add {len(items)} row(s): "
                f"{', '.join(i['albumTitle'] for i in items)}")
            continue
        before = {r["id"] for r in releases}
        collect.merge(releases, items, rewalk.SRC[medium], seen_at)
        for dropped, owner in collect.drop_claimed_newcomers(releases, before):
            log(f"  {dropped}: dropped, {owner} already wears that album")
        new = [r["id"] for r in releases if r["id"] not in before]
        if not new:
            skipped.append((t, "merge folded it into an existing row"))
            log(f"  {name}: merge folded it into an existing row, check by hand")
            continue
        t["got"], t["rows"] = today, new
        landed.append((t, new))
        log(f"  {name}: added {', '.join(new)}")
        if tracks:
            fresh = [r for r in releases if r["id"] in new]
            collect.fill_tracks(fresh, album_fn or collect.ytm_album, lambda query: None,
                               cap=len(fresh), playlist_fn=collect.ytm_playlist, tracks_dir=TRACKS_DIR)
    return {"landed": landed, "waiting": len(waiting(wanted)), "skipped": skipped}


def add(wanted, specs, today=None, details=None):
    """--add film/559: an entry per spec, named from TMDb when a key is set."""
    today = today or date.today().isoformat()
    added = []
    for spec in specs:
        medium, _, tid = str(spec).partition("/")
        if medium not in ("film", "tv") or not tid.strip().isdigit():
            raise SystemExit(f"--add wants film/<id> or tv/<id>, not {spec!r}")
        tid = tid.strip()
        if any(t["medium"] == medium and str(t["tmdb"]) == tid for t in wanted["titles"]):
            print(f"  {medium} {tid} is already on the list")
            continue
        name = None
        try:
            entry = (details or rewalk.details_entry)(medium, tid)
            name = entry.get("title") or entry.get("name")
        except Exception as e:
            print(f"::warning::wanted: {medium} {tid} not named ({e}); add a name by hand")
        t = {"medium": medium, "tmdb": tid, "asked": today}
        if name:
            t["name"] = name
        wanted["titles"].append(t)
        added.append(t)
        print(f"  wanted: {name or tid} ({medium} {tid})")
    return added


def report(result, wanted, today=None, log=print):
    today = today or date.today().isoformat()
    landed = [t for t, _ in result["landed"]]
    still = waiting(wanted)
    oldest = min((t.get("asked") or today for t in still), default=None)
    days = (date.fromisoformat(today) - date.fromisoformat(oldest)).days if oldest else 0
    log(f"wanted: {len(landed)} landed, {len(still)} still not on YT Music"
        + (f", longest wait {days} day(s)" if still else "")
        + (f", {len(result['skipped'])} skipped" if result["skipped"] else ""))
    for t, rows in result["landed"]:
        log(f"  landed: {t.get('name') or t['tmdb']} -> {', '.join(rows)}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--add", action="append", default=[], metavar="film/559",
                    help="add a title to the list (repeatable)")
    ap.add_argument("--only", nargs="*", default=None, help="check only these TMDb ids")
    ap.add_argument("--dry-run", action="store_true", help="search, write nothing")
    args = ap.parse_args(argv)
    wanted = load_wanted()
    if args.add:
        if add(wanted, args.add) and not args.dry_run:
            save_wanted(wanted)
    data = collect.load_data(collect.DATA_PATH)
    seen_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    result = check(data["releases"], wanted, seen_at, only=set(args.only) if args.only else None,
                   dry_run=args.dry_run)
    report(result, wanted)
    if result["landed"] and not args.dry_run:
        data["updatedAt"] = seen_at
        collect.DATA_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if not args.dry_run:
        save_wanted(wanted)


if __name__ == "__main__":
    main()
