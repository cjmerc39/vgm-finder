# Roadmap

Deferred by choice, not forgotten. Ordered roughly by pull.

(Track likes → YT Music playlists shipped 2026-07-30: per-track ♥s,
the Liked-songs view, the Playlists builder in Library, and
`companion/make_playlists.py`. Usage lives in the README.)

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
