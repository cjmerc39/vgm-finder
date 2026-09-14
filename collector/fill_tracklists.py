"""Tracklists for film and TV rows that have none yet. Dispatched by hand
through .github/workflows/tracklists.yml until it reports "tracklists
complete".

Walks 3 and 4 added rows with albums but no tracklists, so they show no top
tracks and never count for most played. Each run reads up to TRACKLIST_CAP
album pages from YouTube Music (plus the audio playlist where a track links
a video edition) for visible film and TV rows wearing an album and carrying
no tracksN, and writes each list to data/tracks/<id>.json through the
split convention: tracksN absent means never checked, 0 means checked and
empty. tracksN is the cursor, so a run that stops early or a fetch that
fails leaves the row for the next run; nothing else is touched.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect

TRACKLIST_CAP = 250
TRACKS_DIR = collect.DATA_PATH.parent / "tracks"


def pending(releases):
    """Visible film and TV rows wearing an album with no tracklist check."""
    return [r for r in releases
            if r.get("medium") in ("film", "tv") and not r.get("retired")
            and "/browse/" in (r.get("ytmAlbumUrl") or "") and "tracksN" not in r and "tracks" not in r]


def run(data_path=None, tracks_dir=None, album_fn=None, playlist_fn=None, cap=TRACKLIST_CAP, now=None):
    data_path = Path(data_path or collect.DATA_PATH)
    tracks_dir = Path(tracks_dir or TRACKS_DIR)
    album_fn = album_fn or collect.ytm_album
    playlist_fn = collect.ytm_playlist if playlist_fn is None else playlist_fn
    data = collect.load_data(data_path)
    releases = data["releases"]
    todo = pending(releases)
    looked = collect.fill_tracks(todo, album_fn, lambda query: None, cap=cap,
                                 playlist_fn=playlist_fn or None, tracks_dir=tracks_dir)
    done = [r for r in todo if "tracksN" in r]
    filled = sum(1 for r in done if r["tracksN"] > 0)
    empty = len(done) - filled
    remaining = len(pending(releases))
    if done:
        data["updatedAt"] = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
        data_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    summary = {"looked": looked, "filled": filled, "empty": empty, "failed": looked - len(done),
               "remaining": remaining}
    print(f"tracklists: {looked} albums read, {filled} with tracks, {empty} empty, "
          f"{summary['failed']} failed and left for the next run, {remaining} rows remaining")
    print("tracklists complete" if remaining == 0 else "tracklists in progress: dispatch again")
    return summary


if __name__ == "__main__":
    run()
