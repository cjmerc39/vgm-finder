# PLAYLIST-SPEC.md, recipe engine and mood tags

## One-liner
Let the app build playlists from rules instead of only from hand-picked
tracks, and give it a vocabulary of mood tags so "rainy evening" is a rule
like any other. Two phases: the recipe engine first (no AI, no keys), then
mood tagging in the collector.

## Context
The app already has three fixed recipes (`plLiked`, `plQueue`, `plRated`
in `playlistDefs()`), two facet filters (`plYear`, `plGenre`), custom
hand-built playlists (`S.cpls`), a JSON export shape (`plTrack` /
`plExportObj`), the local companion, and one-tap publish to YT Music. This
spec generalises the three fixed recipes into user-defined ones and leaves
everything downstream (export, companion, publish) untouched.

Data available per track: title, `videoId`, `plays`. Per album: `game`,
`composers`, `company`, `medium`, `genres`, `date`, `console`, `tier`,
`playsTotal`, `ytmPlaylistId`. Per album from personal state: rating,
hearted tracks, queue status, listen date, notes, hidden.

## Phase 1: recipe engine (build first, ships alone)

### 1.1 What a recipe is
A saved object in `S.recipes`, each with `id`, `name`, and:
- **source**: `catalog` | `library` | `queue` (library means anything with
  a rating or a listen date).
- **filters**, all optional, all AND-ed:
  - medium (`all` / `game` / `screen` / `film` / `tv`, same values as the
    filters sheet)
  - genre (medium-keyed, same store as the filters sheet)
  - year range (from, to)
  - composer (free text, folded contains-match against `composers`)
  - rating (`any`, `>=3`, `>=4`, `5`)
  - hearted only (boolean, track level)
  - console and company tier (game medium only, same semantics as the feed)
- **track selection**: `all tracks` | `top N per album` (N from 1 to 5,
  ranked by `plays` the way `top3Of` already does) | `hearted only`.
- **limit**: total track cap, default 50, max 200.
- **order**: `most played` | `album order` | `newest album` | `shuffle`.
  Shuffle is seeded per export so a re-export is stable within a session.

### 1.2 Behaviour
- Recipes re-evaluate live. Rating something new changes what a recipe
  produces; nothing is frozen at save time.
- A recipe with zero tracks shows as empty and cannot be exported or
  published, same guard as today.
- Recipes appear in the playlists view alongside the three built-ins and
  the custom playlists, with the same export, publish, and delete
  affordances. The three built-ins stay as they are; do not reimplement
  them as recipes.
- Name defaults to a generated description of the rules (for example
  "4★ film scores, top 2 each") and is editable.

### 1.3 UI
- In the playlists view, a `new recipe` button opens a full-height sheet
  (the existing sheet component, same as the filters sheet).
- The sheet is a list of rows: source, medium, genre, years, composer,
  rating, hearted, tracks per album, limit, order. Each row opens its own
  sub-sheet or inline segment; no native `<select>`.
- A live count at the top of the sheet: "N tracks from M albums", updated
  as rules change, so a recipe is never saved blind.
- Footer: `cancel` and `save`.
- Editing an existing recipe reuses the same sheet.

### 1.4 Export
- No change to `plTrack` or the export JSON shape. A recipe exports exactly
  like a built-in, including `videoId`, `ytmPlaylistId`, and `searchQuery`.
- Publish path unchanged.
- Recipes that need tracklists must load them (Phase A's per-album files)
  before counting or exporting, with the existing in-flight guard so an
  export never ships a half-loaded list.

### 1.5 Random mix (built-in)
A fourth built-in alongside liked, queue and 4-star: `random mix`. It is a
recipe with a fixed shape and a reshuffle button:
- source `catalog`, respecting the feed's current medium selection and
  hidden state, nothing else
- track selection `top 1 per album`, so each album contributes its most
  played track, which keeps a random mix from being 40 minutes of ambient
  cues from one game
- limit 30, order `shuffle`, reseeded on every tap of `reshuffle`
- export and publish exactly like the other built-ins; the published
  playlist name is "Scorekeep · Random Mix" (or the app's name at the time)
  and re-publishing replaces its contents rather than creating a new one
- one tap from the playlists view; no configuration. If the user wants a
  configured random playlist, that is a saved recipe with order `shuffle`.

### 1.6 State
- `S.recipes` is a new array. Bump the state version; old backups import
  with an empty array. Recipes are included in export and import backups.

### 1.7 Tests
- Each filter narrows correctly, alone and combined.
- `top N per album` ranks by plays and falls back to `topTracks` when a
  tracklist is missing.
- Limit and order applied in the right sequence (filter, select, order,
  limit).
- Live re-evaluation: rate an album, recipe output changes.
- Empty recipe cannot export or publish.
- Backup round trip preserves recipes; an old backup without them imports.
- Export JSON for a recipe is byte-identical in shape to a built-in's.
- Random mix: one track per album, respects medium and hidden state, reshuffle changes the order and selection, re-publish replaces contents.

## Phase 2: mood tags (build after Phase 1 ships)

### 2.1 Where tagging happens
In the collector, never in the browser. The app stays a static page with no
API key in it. A new step in the daily workflow tags albums that have no
tags yet, using the Anthropic API with `ANTHROPIC_API_KEY` from Actions
secrets. Missing key warns and skips, same as the Twitch and TMDb keys.

### 2.2 Vocabulary
- A fixed list in `collector/moods.json`, committed, sixteen terms. CJ
  approved the list before the first run. The model may only choose from
  it; free text is rejected and the album is left untagged for that run.
- The list (confirmed by CJ, 2026-09-14): wonder, transcendent, nostalgic,
  tender, peaceful, joyful, powerful, tense, sad, heroic, eerie, driving,
  playful, mournful, romantic, mysterious.

### 2.3 Granularity
- Tags are per track, generated one album at a time: one API call per
  album, the whole tracklist in the prompt, a tag list back per track.
  Albums are where mood varies least; tracks are where the playlists live.
- Each track gets 1 to 3 tags. An album-level tag set is derived as the
  union of its track tags, for filtering at album level.
- Tracks with no confident tag get none. Untagged is a valid state and must
  not block anything.

### 2.4 Mechanics
- Model: Claude Haiku, cheapest tier that does this well. Prompt asks for
  JSON only, parsed strictly; a malformed response is retried once then the
  album is skipped and retried on a later run.
- Tags are written into the per-album tracks file (`data/tracks/<id>.json`)
  as a `moods` array per track, plus `moods` on the row in
  `releases.json` for album-level filtering.
- The daily run tags only new albums, with a per-run cap (propose a number
  after measuring; the cap exists so a bad day cannot run up a bill).
- A one-time backfill script tags the existing catalog in capped batches
  with a committed cursor, exactly like `backfill.py`. Report estimated
  cost before running it.
- Tagging is never re-run for an album that already has tags unless a
  `--retag` flag is passed.

### 2.5 Front end
- Mood becomes a filter row in the recipe sheet (multi-select from the
  vocabulary, OR within moods, AND with everything else).
- Mood chips appear in the expanded row and album view, tappable to open a
  feed filtered to that mood.
- No mood row in the main filters sheet until the catalog is mostly
  tagged; the recipe sheet is enough at first.

### 2.6 Tests
- Vocabulary enforcement: a response with an off-list tag is rejected.
- Malformed JSON retried once, then skipped, and the album is picked up on
  the next run.
- Cap respected; cursor advances; re-running does not retag.
- Recipes filter by mood correctly, including albums with partial tagging.
- A missing key skips tagging without failing the collect run.

## Do not
- Do not call any AI API from `index.html`.
- Do not put an API key anywhere in the deployed page or in state backups.
- Do not change the export JSON shape, the companion, or the publish flow.
- Do not replace the three built-in playlists with recipes.
- Do not let the model invent tags outside the vocabulary.
- No em dashes in copy or comments.

## Sequence
1. Phase 1, report the plan first as usual, then build, test, ship.
2. Confirm the mood vocabulary with CJ.
3. Phase 2 on new albums only, verify the tags on a few albums by hand.
4. Cost estimate, then the one-time backfill in capped runs.
