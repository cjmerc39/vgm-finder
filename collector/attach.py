"""Hand-attach a YTM album to a row the strict matchers can never reach.

The matchers stay strict on purpose (covers acts, wrong-era steals,
movie-soundtrack traps); albums that are officially real but invisible to
the rules — VA credits with nonstandard wording (Mafia III's "Expanded
Game Score"), blacklisted compilation wording (KH's "ReMIX"), bare-name
band scores (Disco Elysium by Sea Power) — get attached here instead,
after a human has eyeballed the album:

  python collector/attach.py <row-id> <browseId> [--composers "A" ["B"…]]

The claimed-URL doctrine holds: this refuses to attach an album any other
row already wears, and refuses rows that already have one.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from collect import _patch_audio_ids, ytm_album, ytm_playlist, ytm_tracks_from

DATA = Path(__file__).resolve().parent.parent / "data" / "releases.json"


def attach(data, row_id, browse_id, composers=None, album_fn=ytm_album, playlist_fn=ytm_playlist):
    url = "https://music.youtube.com/browse/" + browse_id
    claimed = [r["id"] for r in data["releases"] if r.get("ytmAlbumUrl") == url]
    if claimed:
        raise SystemExit(f"{browse_id} is already worn by {claimed[0]} — one album, one row")
    row = next((r for r in data["releases"] if r["id"] == row_id), None)
    if row is None:
        raise SystemExit(f"no row with id {row_id!r}")
    if row.get("ytmAlbumUrl"):
        raise SystemExit(f"{row_id} already wears {row['ytmAlbumUrl']}")
    album = album_fn(browse_id)
    if not album or not album.get("tracks"):
        raise SystemExit("album fetch came back empty")
    tracks = ytm_tracks_from(album)
    plid = album.get("audioPlaylistId")
    if plid:
        row["ytmPlaylistId"] = plid  # &list= makes track links open the song, not the video
        if any(not t["videoId"] for t in tracks):
            try:
                _patch_audio_ids(tracks, playlist_fn(plid))
            except Exception:
                pass  # patch is best-effort: links fall back to search
    row["ytmAlbumUrl"] = url
    row["tracks"] = tracks
    if composers:
        row["composers"] = list(composers)
    thumbs = album.get("thumbnails") or []
    if thumbs:
        row["art"] = thumbs[-1]["url"]  # YTM thumbs outrank store/IGDB art
    row.pop("topTracks", None)
    return row, album


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("row_id")
    ap.add_argument("browse_id")
    ap.add_argument("--composers", nargs="*", default=None)
    a = ap.parse_args(argv)
    data = json.loads(DATA.read_text(encoding="utf-8"))
    row, album = attach(data, a.row_id, a.browse_id, a.composers)
    data["updatedAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    DATA.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    linked = sum(1 for t in row["tracks"] if t["videoId"])
    print(f"attached {album.get('title')!r} to {a.row_id}: {len(row['tracks'])} tracks ({linked} linked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
