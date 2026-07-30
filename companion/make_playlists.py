"""Publish vgm-finder playlist exports to your YT Music account.

The static app can never sign in for you, so this runs on the PC:

  one-time:  pip install ytmusicapi
             ytmusicapi browser        # paste request headers -> browser.json
  each time: python companion/make_playlists.py playlist-*.json

browser.json lives next to this script (or pass --auth PATH). It is
gitignored and must never be committed or shared; the phone exports, the
PC publishes.

Re-runs are idempotent: playlists this script created carry a
"# vgm-finder" marker in their description, and a matching one is topped
up with missing tracks instead of duplicated. A same-named playlist
WITHOUT the marker is reported and left untouched — never edit something
made by hand.
"""
import argparse
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "collector"))
from collect import _COVERS_ARTISTS, _numfold, normalize_title  # the collector's strict folds

MARKER = "# vgm-finder"
DESCRIPTION = "Built by vgm-finder from your exported picks. " + MARKER


def _fold(text):
    return _numfold(normalize_title(text or ""))


def load_export(path):
    """One exported playlist file -> (name, tracks). Raises ValueError."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"unreadable: {e}")
    if not isinstance(data, dict):
        raise ValueError("not a vgm-finder playlist export")
    name, tracks = data.get("name"), data.get("tracks")
    if not isinstance(name, str) or not name.strip() or not isinstance(tracks, list):
        raise ValueError("not a vgm-finder playlist export")
    return name.strip(), [t for t in tracks
                          if isinstance(t, dict) and isinstance(t.get("title"), str) and t["title"]]


def resolve_video_id(yt, track):
    """Search-resolve a track that has no videoId. Strict, like the collector:
    the song title must fold-match exactly and the hit's album/artist line
    must name the game. Anything less returns None (reported, not guessed)."""
    game = _fold(track.get("game", ""))
    if not game:
        return None  # nothing to anchor on; guessing by title alone attaches covers
    query = track.get("searchQuery") or f"{track['game']} {track['title']}"
    want = _fold(track["title"])
    try:
        hits = yt.search(query, filter="songs", limit=10) or []
    except Exception:
        return None  # transient search trouble reads as unresolved, next run retries
    for hit in hits:
        if not hit.get("videoId"):
            continue
        artists = [a.get("name", "") for a in hit.get("artists", []) if isinstance(a, dict)]
        if any(a.lower() in _COVERS_ARTISTS for a in artists):
            continue
        if _fold(hit.get("title", "")) != want:
            continue
        album = (hit.get("album") or {}).get("name", "")
        if game not in _fold(" ".join([album] + artists)):
            continue
        return hit["videoId"]
    return None


def find_marked_playlist(yt, name):
    """-> (playlistId or None, present videoIds, same-name-but-unmarked?)."""
    unmarked = False
    for p in yt.get_library_playlists(limit=None) or []:
        if (p.get("title") or "").strip() != name:
            continue
        pid = p.get("playlistId")
        full = yt.get_playlist(pid, limit=None) or {}
        if MARKER in (full.get("description") or ""):
            present = [t.get("videoId") for t in (full.get("tracks") or []) if t.get("videoId")]
            return pid, present, False
        unmarked = True
    return None, [], unmarked


def sync_playlist(yt, name, tracks):
    """Create or top up the marked playlist for one export. Returns a report."""
    rep = {"name": name, "created": False, "skipped": False,
           "added": 0, "already": 0, "unresolved": []}
    ids, seen = [], set()
    for t in tracks:
        vid = t.get("videoId") or resolve_video_id(yt, t)
        if not vid:
            rep["unresolved"].append(f"{t.get('game', '?')} — {t['title']}")
            continue
        if vid not in seen:
            seen.add(vid)
            ids.append(vid)
    pid, present, unmarked = find_marked_playlist(yt, name)
    if pid is None and unmarked:
        rep["skipped"] = True  # a hand-made playlist wears this name; leave it alone
        return rep
    if pid is None:
        pid = yt.create_playlist(name, DESCRIPTION, privacy_status="PRIVATE")
        if not isinstance(pid, str):
            raise RuntimeError(f"create_playlist failed: {pid!r}")
        rep["created"] = True
    have = set(present)
    to_add = [v for v in ids if v not in have]
    rep["already"] = len(ids) - len(to_add)
    if to_add:
        yt.add_playlist_items(pid, to_add, duplicates=False)
        rep["added"] = len(to_add)
    return rep


def expand_args(patterns):
    out = []
    for p in patterns:  # Windows shells hand globs through unexpanded
        hits = sorted(glob.glob(p))
        out.extend(hits if hits else [p])
    return out


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")  # cp1252 consoles must not crash on ♥ or ★
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", help="playlist-*.json exports from the app")
    ap.add_argument("--auth", default=str(Path(__file__).resolve().parent / "browser.json"),
                    help="ytmusicapi browser-auth file (default: companion/browser.json)")
    args = ap.parse_args(argv)

    auth = Path(args.auth)
    if not auth.exists():
        print(f"no auth file at {auth}", file=sys.stderr)
        print("one-time setup:  pip install ytmusicapi  then  ytmusicapi browser", file=sys.stderr)
        print(f"and move the generated browser.json to {auth}", file=sys.stderr)
        return 2

    from ytmusicapi import YTMusic  # lazy: tests drive sync_playlist with a fake
    yt = YTMusic(str(auth))

    failures = 0
    for path in expand_args(args.files):
        try:
            name, tracks = load_export(path)
        except ValueError as e:
            print(f"SKIP {path}: {e}", file=sys.stderr)
            failures += 1
            continue
        rep = sync_playlist(yt, name, tracks)
        if rep["skipped"]:
            print(f"SKIP “{name}”: a same-named playlist exists without the {MARKER} marker "
                  "— rename or delete it and re-run")
            failures += 1
            continue
        verb = "created" if rep["created"] else "updated"
        print(f"{verb} “{name}”: {rep['added']} added, {rep['already']} already there")
        for miss in rep["unresolved"]:
            print(f"  couldn't confidently place: {miss}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
