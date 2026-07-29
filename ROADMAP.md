# Roadmap

Deferred by choice, not forgotten. Ordered roughly by pull.

## YT Music playlists from the app
Build playlists on YouTube Music from the catalog — e.g. "my queue as a
playlist", "top tracks of everything I rated 4+", a liked-albums mix.
Reality check: creating playlists requires an *authenticated* YT Music
session; the shared JSON and the static app can't hold credentials. The
likely shape is a small local companion script (ytmusicapi with CJ's
browser auth, run on the PC like the tracklist fills) fed by an export
from the app — the export/import lifeboat already speaks the right JSON.

## Stats / year recap
Listens per month, average rating, top composers and games. The diary
records (date, rating, liked) were shaped for this from day one — no
migration needed, purely additive view.

## Themed lists
User-curated lists (per CATALOG-SPEC's "not in this pass"). Cheap once
wanted: personal state already keys by stable release ids.

## Smaller knobs
- Deeper catalog: raise `IGDB_BAR` / `NOALBUM_BAR` / `STEAM_TARGET` in
  collector/backfill.py and dispatch until "backfill complete".
- Apple Music secondary links (declined for now — YTM-only listener).
- Franchise-artist credit cleanup ("Assassin's Creed" listed among
  composers on some YTM albums).
