"""One-time migration for the film and TV expansion (Phase A).

Splits tracklists out of data/releases.json into data/tracks/<id>.json and
stamps medium: "game" on every existing row. Deterministic and idempotent:
a second run finds nothing to change and leaves every file untouched, so
the Action can run it unconditionally before the daily collect.

Run from anywhere: python collector/split_tracks.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect


def split(releases, tracks_dir):
    """Move each row's tracks into its own file and add medium.
    Returns how many rows changed."""
    changed = 0
    for r in releases:
        touched = False
        if "medium" not in r:
            r["medium"] = "game"
            touched = True
        if "tracks" in r:
            collect.write_tracklist(r, r.pop("tracks") or [], tracks_dir)
            touched = True
        if touched:
            changed += 1
    return changed


def rejoin(releases, tracks_dir):
    """Inverse of split, used by the round-trip test: fold the per-release
    files back into the rows (an absent file reads as a completed empty
    check, matching the tracksN convention)."""
    for r in releases:
        if "tracksN" not in r:
            continue
        path = Path(tracks_dir) / f"{r['id']}.json"
        r["tracks"] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        del r["tracksN"]
        r.pop("playsTotal", None)
    return releases


def run(data_path=collect.DATA_PATH, tracks_dir=None):
    data_path = Path(data_path)
    tracks_dir = Path(tracks_dir) if tracks_dir else data_path.parent / "tracks"
    data = collect.load_data(data_path)
    if not data["releases"]:
        print("nothing to migrate: no data")
        return 0
    changed = split(data["releases"], tracks_dir)
    if changed:
        data_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")
        print(f"migrated {changed} rows; tracklists live in {tracks_dir.as_posix()}")
    else:
        print("already migrated: nothing to do")
    return 0


if __name__ == "__main__":
    sys.exit(run())
