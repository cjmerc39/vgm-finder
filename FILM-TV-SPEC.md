# FILM-TV-SPEC.md, expansion spec for Claude Code

## One-liner
Extend vgm-finder from video game soundtracks to film and TV scores, using
the same pattern the game catalog already uses (domain catalog for
candidates, YouTube Music for verification, tracks and plays pulled at
collection time). Ship the performance work first, because the catalog is
about to triple.

## Context (read this first)
vgm-finder is a single-file PWA on GitHub Pages. `collector/collect.py`
runs daily and folds releases append-only into `data/releases.json`;
`collector/backfill.py` walks the classics with a committed cursor;
`index.html` renders the JSON with personal state in localStorage. The
catalog half (queue, library, ratings, per-track likes, playlists,
companion publisher) is medium-agnostic and must not change in this pass.

What exists that you must reuse, not reinvent:
- The IGDB leg. `parse_igdb` in collect.py (daily 14-day window) and the
  IGDB leg of backfill.py (rating_count floor, cursor, per-run caps) are the
  template for film and TV. TMDb plays the role IGDB plays.
- The YTM matcher (`_match_album*` family, `_hit_from`, `ytm_resolve`,
  `fill_tracks`). Film rows go through the same strict matcher. Do not
  loosen thresholds for film.
- `merge()` and its dedupe (slug, numeral fold, fuzzy at 0.92, year suffix
  for same-name different-era). Medium has to enter this before any film row
  lands, see Data model.

Two philosophies carry over: deterministic and append-only in the collector,
and a real YTM album or nothing for film and TV. The game catalog has a
search-only "canon" tier (`NOALBUM_BAR`). Film and TV do not get one.

## Process (do these in order)
1. Read this whole spec, then read the repo: README, ROADMAP, VGM-RADAR-SPEC,
   collect.py, backfill.py, index.html, both test files. Ask questions
   BEFORE coding.
2. **Report back, do not skip.** In plain English:
   - Current row count, file size, and how many bytes are tracklists.
   - How `merge()` would treat a film titled the same as a game today.
   - Which front-end functions assume game fields (`game`, `console`,
     `company`, `genres`, `coTier`).
   - A migration plan for the data file split in Phase A, including how
     TRACKNO (append-only row numbers) and personal state ids survive it.
3. Get sign-off on the plan.
4. Phase A: performance and schema. Ship it, verify on a phone, get sign-off.
5. Phase B: film and TV collection. Discovery first (see Phase B), then build.
6. Run the backfill for real, in capped runs, until "backfill complete".

## Phase A: performance and schema (ship before any film row exists)

### A1. Split tracklists out of releases.json
- `data/releases.json` keeps every row minus `tracks`. Rows keep
  `ytmPlaylistId` and gain `tracksN` (count) so the row can show a count
  without loading the tracklist.
- Tracklists move to `data/tracks/<id>.json`, one file per release, loaded
  on demand when a row is expanded or the album view opens, and when
  playlist recipes or liked-songs views need them (load only the ids they
  reference, cache in memory for the session).
- The collector writes both. `fill_tracks` output goes to the per-release
  file; the row gets `tracksN`. Existing rows migrate in one deterministic
  script committed to `collector/` and run once by the Action.
- Front-end tests get a fixture with a few `data/tracks/*.json` files and
  cover: expand loads the file, liked-songs view loads only referenced ids,
  a missing tracks file degrades to the row's search link, not an error.

### A2. Stop re-sorting the world on every render
- `sorted()` currently sorts all rows on every `renderAll()`. Compute the
  base order once after load and cache it; invalidate only when `R` changes
  (it never does after boot). Views filter and re-sort the cached array.
- `byId` is a linear find. Build an id index at boot.

### A3. Page the list
- Render the first 60 rows of any list, then a "more" sentinel that appends
  the next 60 when it scrolls into view (IntersectionObserver, with a plain
  button fallback). Search results page the same way.
- Year headers in the feed stay correct across pages.
- Expanding a row, hearting a track, or logging a listen must not reset
  paging or scroll position (the album view already guards scrollTop; keep
  that behaviour).

### A4. Navigation
- A sticky back-to-top control that appears after one screen of scroll and
  scrolls `main` to the top. Respect prefers-reduced-motion.
- A year jump: tapping the current year header (or a small year control in
  the feed controls) opens a picker of years present in the current list
  and scrolls to that year's header, loading pages as needed. Cheap
  implementation is fine; it only needs to work reliably on iPhone Safari.

### A5. Schema: `medium`
- Every row gains `medium`: `"game"`, `"film"`, or `"tv"`. The migration
  script sets all existing rows to `"game"`.
- Rename nothing else. `game` stays the field name for the parent work
  because too much depends on it; document in the README that for film and
  TV rows `game` holds the film or show title. The front end labels it by
  medium (see Phase B).
- `merge()`: medium becomes part of the dedupe key. Two items with different
  mediums never merge, regardless of title similarity. The slug for non-game
  rows is prefixed (`film-`, `tv-`) so ids cannot collide and remain stable.
- `ytm_search_url`: for film use `"<title> <game> soundtrack"` as today; for
  tv use `"<title> <game> soundtrack"` too, but the discovery step should
  check whether "original score" matches better on YTM for either medium
  and report.
- Front end: a medium chip row in the feed controls (`all` / `games` /
  `film` / `tv`), persisted in state as `feedMedium`, default `all`. The
  same chip in the library. The subtitle label reads the medium: game
  rows unchanged, film rows `<film> · <composers>`, tv rows
  `<show> · <composers>`. Big studios / indie and console filters apply to
  game rows only and hide themselves when the medium chip excludes games.
  Genres: TMDb genres populate `genres` so the genre select keeps working;
  keep the list per medium so game genres and film genres do not mix in one
  dropdown.
- "most played" feed sort: sum of track plays, using `plays` already in the
  tracklists. Since tracks now live in separate files, the collector writes
  `playsTotal` on the row at fill time so the sort needs no track loads.
  Rows without a value sink to the bottom.

### A6. State migration
- Bump state version. `feedMedium` and `libMedium` default to `all`.
  `validateState` accepts old state without them. Backups from before this
  pass import cleanly.

## Phase B: film and TV collection

### B1. Discovery (report before building)
- Get a TMDb API key (free, `https://www.themoviedb.org/settings/api`),
  stored as `TMDB_API_KEY` in Actions secrets, same handling as the Twitch
  pair: missing key warns and skips, the rest still runs.
- Fetch live and report: the `discover/movie` and `discover/tv` endpoints
  with `vote_count.gte` floors, `primary_release_date` windows, and what
  fields come back (genres, release dates, poster paths, original title,
  original language).
- Check how TMDb credits composers. Report whether `credits` reliably
  exposes an "Original Music Composer" job for film and TV, because the
  composer is the second search term on YTM and the subtitle on the row.
- Run 20 film and 20 TV titles across the eras through the existing YTM
  matcher by hand and report hit rate and the false positives you saw. If
  the matcher needs a film-specific guard (for example, rejecting
  "Music Inspired By" and karaoke/cover results), propose it before adding
  it. `_COVERS_ARTISTS` and `_OFFICIAL_WORDING` are the existing hooks.
- Propose the daily window for film and TV (IGDB uses 14 days and a hype
  floor; film scores often release the same week as the film, TV scores
  often weeks after the season ends, so TV probably needs a longer window).

### B2. Daily collection (collect.py)
- Two new SOURCES entries, `tmdb-film` and `tmdb-tv`, type `catalog`, same
  shape as the IGDB entry. Each fetches recent releases above a modest
  `vote_count` floor (proposed during discovery), checks each against YTM
  with the strict matcher, and yields an item only on a real album match.
- Items carry `medium`, `game` (film or show title), `composers`,
  `genres`, `art` (YTM thumbnail first, TMDb poster as fallback),
  `date` (album date when YTM has one, else the film's release date).
- Fixtures: saved TMDb responses in `collector/fixtures/`, tests cover
  parsing, the medium prefix on ids, no-merge across mediums, and the
  composer-in-query behaviour.

### B3. Backfill (backfill.py)
- Two new legs mirroring the IGDB leg: film by `vote_count desc` with
  `FILM_BAR = 1000`, TV by `vote_count desc` with `TV_BAR = 500`. Both are
  module constants so raising or lowering is a one-line change and a
  re-dispatch. Per-run caps and the cursor pattern stay identical;
  `backfill-state.json` gains `tmdbFilmOffset` and `tmdbTvOffset`.
- Every candidate is checked once against YTM and recorded as checked
  whether or not it matched, same as `gapChecked`.
- No search-only rows for film or TV. A famous film with no findable score
  album is skipped, not seeded.
- The ROADMAP "Deeper catalog" note gains the two new bars.

### B4. Front end (small, most of it landed in A5)
- Medium chips wired to real data. The colophon count reads
  "N soundtracks" rather than "N tracks".
- Source chips: `tmdb` gets the friendly label `catalog` in `SRC_LABEL`.
- The random button respects the current medium chip.
- The album view header shows medium, so a film score does not read as a
  game.

## Tests
- Collector: pytest, fixtures for TMDb film and TV, YTM search fixtures
  that include at least one karaoke/cover false positive per medium.
  Cover the migration script (round trip: split then rejoin equals the
  original), medium-aware merge, and `playsTotal`.
- Front end: jsdom, cover paging (first page, append on sentinel, search
  resets paging), year jump, back-to-top visibility, medium chips filtering
  each view, lazy track loading, and the "most played" sort with and
  without `playsTotal`.
- Both halves keep their one-command runs. Update the README.

## Do not
- Do not rebuild the catalog half or change the localStorage shape beyond
  the additive fields listed.
- Do not add MusicBrainz, Discogs, or any other database. TMDb plus YTM only.
- Do not change the visual identity. New controls use the existing chip and
  button styles.
- Do not use em dashes in any copy or comments.

## Phase C backlog (do not build now)
- Composer pages (all works by one composer across mediums).
- Stats and year recap, per ROADMAP.
- A "score vs songs" tag for film rows, if discovery shows YTM albums make
  it distinguishable.
