"""Scores versus songs, judged offline from what is already on disk.

Every visible film or TV row whose tracklist carries artists (see
fill_artists.py) is judged again with collect.judge_tracks: a "song" mark
on each track credited to someone other than the score composer, scoresN
on the row, and songsAlbum when fewer than half of the named tracks are
score. No network. Re-run it after any rule change.

Rows the re-walk evaluated first take their credits' provenance from the
stored records: composers TMDb never listed, where the album's own acts
stood in, are marked composersFrom "album" so the judgment treats those
acts as album acts, and TMDb's aliases land on the row as composerAliases.
The songs pins of collector/screen-overrides.json are applied after the
rule, the same way the daily fill applies them.

  python collector/judge_songs.py                 # judge, write, summarize
  python collector/judge_songs.py --dry-run       # summarize only
  python collector/judge_songs.py --show film-bohemian-rhapsody film-deadpool
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect

TRACKS_DIR = collect.DATA_PATH.parent / "tracks"


def backfill_credits(releases, evaluations):
    """composersFrom and composerAliases from the re-walk's records, for rows
    born before the daily path carried them. Returns how many rows changed."""
    by_url = {}
    for rec in evaluations.values():
        for c in rec.get("accepted") or []:
            by_url.setdefault(c["url"], rec)
    changed = 0
    for r in releases:
        if r.get("medium") not in ("film", "tv"):
            continue
        rec = by_url.get(r.get("ytmAlbumUrl"))
        if rec is None:
            continue
        before = (r.get("composersFrom"), list(r.get("composerAliases") or []))
        if not rec.get("composers") and r.get("composers"):
            r["composersFrom"] = "album"
        else:
            r.pop("composersFrom", None)
        if rec.get("aliases"):
            r["composerAliases"] = list(rec["aliases"])
        else:
            r.pop("composerAliases", None)
        changed += before != (r.get("composersFrom"), list(r.get("composerAliases") or []))
    return changed


def judge_all(releases, tracks_dir, write=True, songs_pins=None):
    """-> summary dict; writes changed track files when write is set. The
    songs pins of screen-overrides.json are applied after the rule."""
    tracks_dir = Path(tracks_dir)
    if songs_pins is None:
        songs_pins = collect.screen_override_sets(collect.load_screen_overrides())["songs"]
    out = {"judged": 0, "unjudged": 0, "flaggedBefore": 0, "flaggedAfter": 0,
           "newlyFlagged": [], "cleared": [], "noScore": 0, "filesWritten": 0, "pinned": 0}
    for r in releases:
        if r.get("medium") not in ("film", "tv") or r.get("retired"):
            continue
        path = tracks_dir / f"{r['id']}.json"
        if not (r.get("tracksN") or 0) > 0 or not path.exists():
            continue
        raw = path.read_text(encoding="utf-8")
        tracks = json.loads(raw)
        before = bool(r.get("songsAlbum"))
        out["flaggedBefore"] += before
        tally = collect.judge_tracks(r, tracks, songs_pins)
        if tally is None:
            out["unjudged"] += 1
            out["flaggedAfter"] += before
            continue
        out["judged"] += 1
        out["pinned"] += bool(tally.get("pinned"))
        after = bool(r.get("songsAlbum"))
        out["flaggedAfter"] += after
        if after and not before:
            out["newlyFlagged"].append(r["id"])
        if before and not after:
            out["cleared"].append(r["id"])
        if r.get("scoresN") == 0:
            out["noScore"] += 1
        text = json.dumps(tracks, indent=2, ensure_ascii=False) + "\n"
        if text != raw:
            out["filesWritten"] += 1
            if write:
                path.write_text(text, encoding="utf-8")
    return out


def run(data_path=None, tracks_dir=None, evaluations=None, write=True, log=print, songs_pins=None):
    data_path = Path(data_path or collect.DATA_PATH)
    tracks_dir = Path(tracks_dir or TRACKS_DIR)
    data = collect.load_data(data_path)
    releases = data["releases"]
    if evaluations is None:
        try:
            import rewalk
            evaluations = rewalk.load_evaluations()
        except Exception:
            evaluations = {}
    before = json.dumps(releases, sort_keys=True, ensure_ascii=False)
    credits = backfill_credits(releases, evaluations) if evaluations else 0
    out = judge_all(releases, tracks_dir, write=write, songs_pins=songs_pins)
    out["creditsBackfilled"] = credits
    if write and json.dumps(releases, sort_keys=True, ensure_ascii=False) != before:
        data_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log(f"songs: {out['judged']} rows judged, {out['unjudged']} still without track artists, "
        f"{credits} rows given credit provenance, {out['pinned']} verdicts pinned by screen-overrides.json")
    log(f"songsAlbum: {out['flaggedBefore']} before, {out['flaggedAfter']} after "
        f"({len(out['newlyFlagged'])} newly flagged, {len(out['cleared'])} cleared); "
        f"{out['noScore']} albums keep no score track; {out['filesWritten']} track files "
        f"{'written' if write else 'would change'}")
    return out


def show(ids, data_path=None, tracks_dir=None, log=print):
    data_path = Path(data_path or collect.DATA_PATH)
    tracks_dir = Path(tracks_dir or TRACKS_DIR)
    rows = {r["id"]: r for r in collect.load_data(data_path)["releases"]}
    pins = collect.screen_override_sets(collect.load_screen_overrides())["songs"]
    for rid in ids:
        r = rows.get(rid)
        if not r:
            log(f"{rid}: no such row")
            continue
        path = tracks_dir / f"{rid}.json"
        tracks = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        tally = collect.judge_tracks(dict(r), [dict(t) for t in tracks], pins)
        log(f"{rid}: composers={r.get('composers')} from={r.get('composersFrom') or 'tmdb'} "
            f"aliases={r.get('composerAliases')} albumArtists={r.get('albumArtists')} genres={r.get('genres')}")
        log(f"  score names: {tally and tally['names']} | named {tally and tally['named']}, "
            f"score {tally and tally['score']}, songsAlbum {tally and tally['songs']}"
            + (f", pinned {tally['pinned']}" if tally and tally.get("pinned") else ""))
        for t in tracks:
            log(f"  {'song ' if t.get('song') else 'score'}  {t.get('title')}  |  {', '.join(t.get('artists') or [])}  |  {t.get('plays')}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--show", nargs="*", default=None, help="row ids to print track by track")
    args = ap.parse_args()
    if args.show:
        show(args.show)
    else:
        run(write=not args.dry_run)
