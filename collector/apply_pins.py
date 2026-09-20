"""Rows for screen-overrides.json pins whose title has no row yet.

A pin takes effect when a leg revisits its title: the daily window, the
backfill, or a re-walk. A title the backfill has already checked and that no
longer airs is never revisited, so a pin added for it later (Money Heist,
whose only album the title gate turns away) would wait forever. This builds
the pinned row now, from the title's stored re-walk record, exactly as a
re-walk addition is built and merged. It never touches a row that exists and
never takes an album another row wears.

A title the re-walk never evaluated (under its vote bar, like The Great
British Bake Off) has no stored record. With TMDB_API_KEY set, such a title
is looked up and searched exactly as the re-walk's evaluate step does, and
the record is kept in collector/rewalk/eval-pins.json so later runs and the
re-walk read it too. Without the key it is listed and skipped. The pins.yml
workflow runs this with the key, then fill_tracklists.py.

  python collector/apply_pins.py --dry-run         # list what would be added
  python collector/apply_pins.py [--tmdb 71446]    # add, then fill_tracklists.py reads the new albums
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect
import rewalk


PINS_SHARD = rewalk.REWALK_DIR / "eval-pins.json"   # sorts after eval-NNNN, so its records win


def evaluate_pinned(medium, tid, releases):
    """One title looked up on TMDb and searched as the re-walk does."""
    return rewalk.evaluate_title(medium, rewalk.details_entry(medium, tid), rewalk._worn(releases),
                                 collect.ytm_resolve, collect.ytm_album)


def fetch_records(releases, overrides, evaluations, only=None, fetch=evaluate_pinned, shard=PINS_SHARD,
                  log=print):
    """Records for pinned titles with no row and no stored record, fetched
    and added to evaluations and to the pins shard. -> how many."""
    sets = collect.screen_override_sets(overrides)
    worn = collect.claimed_albums(releases)
    kept = json.loads(Path(shard).read_text(encoding="utf-8")) if Path(shard).exists() else []
    fetched = 0
    for slot, p in sets["pins"].items():
        medium, tid = slot[0], slot[1]
        if (only and tid not in only) or (medium, tid) in evaluations or collect.YTM_BROWSE + p["album"] in worn:
            continue
        rec = fetch(medium, tid, releases)
        evaluations[(medium, tid)] = rec
        kept = [x for x in kept if (x["medium"], x["id"]) != (medium, tid)] + [rec]
        fetched += 1
        log(f"  looked up {p.get('name')} ({medium} {tid}) on TMDb: {rec.get('name')}, first aired {rec.get('date')}")
    if fetched:
        Path(shard).write_text(json.dumps(kept, ensure_ascii=False) + "\n", encoding="utf-8")
    return fetched


def apply_pins(releases, overrides, evaluations, seen_at, only=None, album_fn=None, log=print):
    """Merge a row for every pin whose album no row wears. only: TMDb ids to
    limit it to. -> ids of the rows added."""
    sets = collect.screen_override_sets(overrides)
    added = []
    for slot, p in sets["pins"].items():
        medium, tid = slot[0], slot[1]
        if only and tid not in only:
            continue
        url = collect.YTM_BROWSE + p["album"]
        if url in collect.claimed_albums(releases):
            continue  # its row exists, or another row wears the album: nothing to add
        rec = evaluations.get((medium, tid))
        if not rec:
            log(f"  {p.get('name')} ({medium} {tid}): no stored record, skipped")
            continue
        album = rewalk._pin_candidate(p, rec, medium, album_fn or collect.ytm_album)
        item = rewalk.addition_item({"title": rec, "album": album, "slot": list(slot)})
        before = {r["id"] for r in releases}
        collect.merge(releases, [item], rewalk.SRC[medium], seen_at)
        new = [r for r in releases if r["id"] not in before]
        if new and new[0].get("ytmAlbumUrl") == url:
            added.append(new[0]["id"])
            log(f"  added {new[0]['id']}: {album['title']}")
        else:
            log(f"  {p.get('name')} ({medium} {tid}): merge folded it into an existing row, check by hand")
    return added


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tmdb", nargs="*", default=None, help="only these TMDb ids")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    data = collect.load_data(collect.DATA_PATH)
    seen_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    overrides, evaluations = collect.load_screen_overrides(), rewalk.load_evaluations()
    only = set(args.tmdb) if args.tmdb else None
    if os.environ.get("TMDB_API_KEY") and not args.dry_run:
        fetch_records(data["releases"], overrides, evaluations, only=only)
    added = apply_pins(data["releases"], overrides, evaluations, seen_at, only=only)
    print(f"pins: {len(added)} row(s) {'would be ' if args.dry_run else ''}added")
    if added and not args.dry_run:
        collect.DATA_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
