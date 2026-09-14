"""Per-track artists for film and TV rows, so scores-only can judge each
track instead of each album.

For every visible film or TV row wearing an album and a tracklist, the
album page's track artists are written into data/tracks/<id>.json as an
"artists" list on each track (empty when YouTube Music names none), and
the album's own credited artists onto the row as "albumArtists". Pages
the re-walk stored in collector/rewalk are read offline; the rest are
fetched. Rows already carrying both are skipped, so a stopped run resumes
where it left off. Nothing is judged here: judge_songs.py reads these.

  python collector/fill_artists.py            # everything left, paced
  python collector/fill_artists.py --cap 50   # a taste
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect

TRACKS_DIR = collect.DATA_PATH.parent / "tracks"
PAUSE = 0.3   # seconds between page fetches: a walk, not a crawl


def names_of(track):
    return [a["name"] for a in track.get("artists") or [] if isinstance(a, dict) and a.get("name")]


def pending(releases, tracks_dir, need_album=True):
    """Rows still to fill. A sidecar worker (need_album off) judges by the
    track file alone, since the album's acts land in its sidecar."""
    out = []
    for r in releases:
        if r.get("medium") not in ("film", "tv") or r.get("retired"):
            continue
        if "/browse/" not in (r.get("ytmAlbumUrl") or "") or not (r.get("tracksN") or 0) > 0:
            continue
        path = Path(tracks_dir) / f"{r['id']}.json"
        if not path.exists():
            continue
        tracks = json.loads(path.read_text(encoding="utf-8"))
        if ("albumArtists" in r or not need_album) and all("artists" in t for t in tracks):
            continue
        out.append((r, path, tracks))
    return out


def apply_sidecars(data_path, paths):
    """Album acts collected by sidecar workers onto their rows."""
    data = collect.load_data(Path(data_path))
    rows = {r["id"]: r for r in data["releases"]}
    n = 0
    for p in paths:
        for rid, acts in json.loads(Path(p).read_text(encoding="utf-8")).items():
            if rid in rows and rows[rid].get("albumArtists") != acts:
                rows[rid]["albumArtists"] = acts
                n += 1
    Path(data_path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return n


def attach(tracks, page):
    """Track artists from an album page onto a stored tracklist: by position
    when the counts agree, else by normalized title. Returns how many tracks
    found their artists."""
    ptracks = [t for t in (page or {}).get("tracks") or [] if t.get("title")]
    found = 0
    if len(ptracks) == len(tracks):
        for t, p in zip(tracks, ptracks):
            t["artists"] = names_of(p)
            found += 1
    else:
        by_title = {}
        for p in ptracks:
            by_title.setdefault(collect.normalize_title(p["title"]), names_of(p))
        for t in tracks:
            hit = by_title.get(collect.normalize_title(t["title"]))
            t["artists"] = hit if hit is not None else []
            found += hit is not None
    for t in tracks:
        t.setdefault("artists", [])
    return found


def stored_pages(folder=None):
    """Album pages the re-walk kept, keyed by browse id."""
    try:
        import rewalk
    except ImportError:
        return {}
    pages = {}
    for rec in rewalk.load_evaluations(folder or rewalk.REWALK_DIR).values():
        for bid, page in (rec.get("albums") or {}).items():
            if page and page.get("tracks"):
                pages.setdefault(bid, page)
    return pages


def run(data_path=None, tracks_dir=None, album_fn=None, cap=None, pause=PAUSE, pages=None, log=print,
        shard=None, sidecar=None):
    """shard=(i, n) takes every n-th pending row; with a sidecar path the
    album acts go there instead of releases.json, so parallel workers never
    write the same file. apply_sidecars folds them in afterwards."""
    data_path = Path(data_path or collect.DATA_PATH)
    tracks_dir = Path(tracks_dir or TRACKS_DIR)
    album_fn = album_fn or collect.ytm_album
    data = collect.load_data(data_path)
    todo = pending(data["releases"], tracks_dir, need_album=sidecar is None)
    if shard:
        todo = [x for k, x in enumerate(todo) if k % shard[1] == shard[0]]
    pages = stored_pages() if pages is None else pages
    side = {}
    if sidecar and Path(sidecar).exists():
        side = json.loads(Path(sidecar).read_text(encoding="utf-8"))
    log(f"artists: {len(todo)} rows to fill, {len(pages)} pages stored offline")
    done = fetched = failed = 0
    dirty = False

    def save():
        if sidecar:
            Path(sidecar).write_text(json.dumps(side, ensure_ascii=False) + "\n", encoding="utf-8")
        else:
            data_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    for i, (r, path, tracks) in enumerate(todo):
        if cap is not None and done >= cap:
            break
        bid = r["ytmAlbumUrl"].rsplit("/", 1)[1]
        page = pages.get(bid)
        if page is None:
            try:
                page = album_fn(bid)
                fetched += 1
            except Exception as e:
                failed += 1
                log(f"  skip {r['id']}: {e}")
                time.sleep(pause)
                continue
            time.sleep(pause)
        attach(tracks, page)
        acts = [a["name"] for a in (page or {}).get("artists") or [] if isinstance(a, dict) and a.get("name")]
        if sidecar:
            side[r["id"]] = acts
        else:
            r["albumArtists"] = acts
        path.write_text(json.dumps(tracks, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        done += 1
        dirty = True
        if done % (20 if sidecar else 100) == 0:
            save()
            dirty = False
            log(f"  {done} done ({fetched} fetched, {failed} failed), {len(todo) - i - 1} left")
    if dirty:
        save()
    log(f"artists: {done} rows filled ({fetched} pages fetched, {failed} failed), {len(todo) - done} remaining")
    return {"done": done, "fetched": fetched, "failed": failed, "remaining": len(todo) - done}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cap", type=int, default=None)
    ap.add_argument("--pause", type=float, default=PAUSE)
    ap.add_argument("--shard", default=None, help="I/N: this worker takes every N-th pending row")
    ap.add_argument("--sidecar", default=None, help="JSON file for this worker's album acts (parallel runs)")
    ap.add_argument("--merge", nargs="*", default=None, help="sidecar files to fold into releases.json")
    args = ap.parse_args()
    if args.merge is not None:
        print(f"merged album acts onto {apply_sidecars(collect.DATA_PATH, args.merge)} rows")
    else:
        shard = tuple(int(x) for x in args.shard.split("/")) if args.shard else None
        run(cap=args.cap, pause=args.pause, shard=shard, sidecar=args.sidecar)
