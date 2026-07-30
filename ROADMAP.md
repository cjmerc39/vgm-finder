# Roadmap

Deferred by choice, not forgotten. Ordered roughly by pull.

## Next up: track likes → YT Music playlists

Two features, built in this order because the second eats the first's
output. (Slated for the next working session.)

### 1. Like individual songs
Today hearts live at the release level. Add a per-track heart:

- **UI**: a small ♥ toggle on every track row — in the expanded panel's
  top-3 list and on the full album page. Same filled/outline treatment as
  the release heart. No sheet, no ritual: one tap toggles.
- **State** (additive, no migration): `entries[releaseId].likedTracks`,
  an array of track *titles* (titles survive tracklist refetches;
  indexes don't — refetches reorder and repatch). Normalize on compare
  (the app's `fold()`), store the display title as-is.
- **Library**: a "Liked songs" view or filter chip in Library listing
  every liked track (release art + game + track title), each row a tap
  to its YTM link (`watch?v=…&list=…` when the track has a videoId,
  search fallback otherwise).
- **Export/import lifeboat**: nothing to do — `likedTracks` rides inside
  `entries`, which the lifeboat already carries whole.
- **Tests**: toggle persists across reload; refetched tracklist keeps
  likes matched by title; export→wipe→import round-trips likedTracks.

### 2. Playlists → YT Music
Build playlists from personal state and get them into CJ's real YT Music
account. Constraint (unchanged): playlist creation needs an
*authenticated* YTM session — **credentials must never live in the static
app or any committed/shared JSON**. Shape:

- **In-app builder**: a "Playlists" section (Library tab) that composes
  track lists from what the app already knows:
  - *Liked songs* — everything from feature 1.
  - *Queue albums* — top-3s (or full tracklists) of queued releases.
  - *Rated 4+ mix* — top tracks of every release rated ≥4.
  - *By year / by genre* — facet-filtered variants of the above.
  Preview the tracklist in-app before export.
- **Export**: one button per playlist → downloads
  `playlist-<name>.json`: `{ name, tracks: [{ game, title, videoId?,
  ytmPlaylistId?, searchQuery }] }`. videoIds come from the catalog's
  tracklists (audio-only ids); tracks without one carry their
  `game + title` search query for the companion to resolve.
- **Local companion script** (`companion/make_playlists.py`, run on the
  PC exactly like the tracklist fills):
  1. One-time setup: `ytmusicapi browser` → paste request headers →
     writes `browser.json` (gitignored; never committed).
  2. `python companion/make_playlists.py playlist-*.json` → for each
     file: create (or update, matched by name) a private YTM playlist;
     add tracks by videoId; search-resolve the rest with the collector's
     strict matcher and report anything it couldn't confidently place.
  3. Idempotent re-runs: keep a `# vgm-finder` marker in the playlist
     description and sync additions instead of duplicating.
- **Not doing**: OAuth inside the PWA, server-side anything, or storing
  auth in localStorage. The phone exports; the PC publishes.

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
