# VGM-RADAR-SPEC.md, v1 build spec for Claude Code

## One-liner
A single-file, mobile-first PWA on GitHub Pages that tracks notable new video
game soundtrack releases from curated sources, one tap from each entry to
YouTube Music. Sibling project to snap-workbench and home-bar. Reuse their
patterns, conventions, and test style. Repo name placeholder: `vgm-radar`.

## Context (read this first)
CJ listens to VGM on YouTube Music and has no good way to keep up with what's
coming out. This app is the answer: open it, see what's new, tap a row, listen.

Two halves, strictly separated:
1. **Collector**: a Python script run by a GitHub Actions cron that gathers
   releases from curated sources and commits them into `data/releases.json`.
2. **Front end**: `index.html` renders that JSON. The front end never scrapes
   or calls any external API itself. It reads one same-origin JSON file.

v1 philosophy: curated and quiet. Only sources where a human editor already
decided a release was worth writing about. Low volume, high trust. The
firehose (Steam soundtracks, Bandcamp, VGMdb calendar) and notability scoring
are Phase 2, listed at the bottom. Build the schema so Phase 2 slots in
without rework, but do not build Phase 2 now.

## Process (do these in order)
1. Read this whole spec. Ask questions BEFORE coding.
2. **Discovery phase, do not skip.** Before writing any collector code, fetch
   each candidate source live and verify what actually exists:
   - VGMO (Video Game Music Online): `https://www.vgmonline.net/feed/`
     (WordPress site, expect standard RSS; confirm item structure and whether
     release posts are distinguishable from features/reviews).
   - Original Sound Version: check whether the site is alive and has a feed.
   - r/gamemusic weekly top: `https://www.reddit.com/r/gamemusic/top.json?t=week`
     (community curation rather than editorial; if used, tag the source type
     so the front end can badge it differently).
   - Look for 1 or 2 additional editorial VGM news feeds during discovery.
   Report back: which sources are live, what their real structure looks like,
   and the proposed parse plan for each. Minimum bar to proceed: 2 working
   sources. Get sign-off on the source list before building.
3. Build the collector with fixture-based tests.
4. Build the front end with jsdom tests.
5. Wire the Action, trigger it manually once for real, verify the JSON commit
   and the Pages deploy end to end.

## Repo layout
- `index.html` (everything app-side inline: HTML, CSS, JS; no framework, no
  build step)
- `data/releases.json` (committed, append-only history)
- `collector/collect.py` (keep dependencies minimal and pinned; feedparser
  and requests are fine)
- `collector/fixtures/` (saved copies of real source responses, used by tests)
- `.github/workflows/collect.yml` (daily cron around 06:00 ET plus
  workflow_dispatch for manual runs; runs collector, commits only if the JSON
  changed)
- `vgm-radar.test.js` (jsdom harness, mirror snap-workbench.test.js style)
- `README.md` (one screen: what this is, run collector locally, run tests)

## Data model (`data/releases.json`)
```json
{
  "updatedAt": "2026-07-28T10:00:00Z",
  "releases": [
    {
      "id": "stable-slug-from-normalized-title",
      "title": "Album title as published",
      "game": "Game name if parseable, else null",
      "composers": [],
      "date": "YYYY-MM-DD",
      "sources": [
        { "name": "vgmo", "url": "https://...", "seenAt": "ISO timestamp" }
      ],
      "ytmSearchUrl": "https://music.youtube.com/search?q=...",
      "ytmAlbumUrl": null,
      "art": null,
      "notable": true
    }
  ]
}
```
Notes on fields:
- `id` must be stable across runs (derive from normalized title, not from
  source URLs, so two sources reporting the same album collide on purpose).
- `date` is the best known release date; fall back to the article publish
  date when the source doesn't state one.
- `ytmSearchUrl` is built deterministically: URL-encoded
  `"<title> <game> soundtrack"` (drop null parts, collapse whitespace).
- `ytmAlbumUrl`, `art` stay null in v1. They exist so Phase 2 (ytmusicapi
  resolution, IGDB art) fills them without a schema migration.
- `notable` is always true in v1 because every source is curated. The field
  exists for Phase 2 scoring.

## Collector rules
- Deterministic. No AI calls anywhere in the pipeline.
- Append-only. Never delete or rewrite existing entries. When a new item
  dedupes against an existing entry, merge: add the new source to `sources`,
  keep the earliest `date`, keep the existing `id`.
- Dedupe key: lowercase the title, strip punctuation, strip suffixes like
  "original soundtrack", "OST", "original score", collapse whitespace. Apply
  a fuzzy match threshold for near-misses across sources.
- Fail loudly, fail partially: one source erroring logs clearly in the Action
  output but doesn't kill the others. All sources failing exits nonzero so
  the Action run shows red.
- Politeness: send a real User-Agent identifying the repo, one request per
  feed per run.

## Front end (`index.html`)
- Mobile-first. iPhone Safari is the primary target. PWA add-to-home-screen
  with an inline manifest and icons, same approach as the sibling repos.
- Fetches `data/releases.json`, renders newest first.
- Row contents: title, game, composer(s), date, source chip(s).
- Tap anywhere on a row: open the YT Music link (`ytmAlbumUrl` when present,
  else `ytmSearchUrl`) in a new tab.
- Per-row actions: star, mark listened, hide. Personal state lives in
  localStorage under a `vgm-v1` key. The shared JSON never carries personal
  state.
- Filter chips: All / Unlistened / Starred. A search box filters across
  title, game, and composers.
- New-since-last-visit: store a lastSeen timestamp in localStorage and badge
  anything newer.
- Architecture mirrors home-bar: one state object `S`, small mutation
  functions for every change, plain innerHTML view renderers re-run through
  `renderAll()`. No render path gets its own mutation logic.
- Empty and error states explain what happened and what to do next. Errors
  never apologize and are never vague.

## Design direction (execute with restraint)
Ground it in the subject: the Sound Test screen from old options menus, the
original way everyone binged VGM. Near-black background with a slight blue
lean, warm CRT-amber accent, cream ink, dim slate for secondary text. One
characterful display face reserved for the wordmark and track numbers only
(pixel-adjacent or a chunky grotesque), a clean quiet body face for
everything else. The signature element: each release renders with an
incrementing TRACK NNN index like a sound test menu, and the listened toggle
reads as a small play-state glyph. Spend the boldness there and keep the rest
disciplined, fast, and legible in daylight. Respect prefers-reduced-motion
and keep focus states visible. Do not reuse the walnut/brass language from
home-bar; each app in this family gets its own identity.

## Tests
- Collector: pytest against `collector/fixtures/` copies of real responses.
  Cover parsing per source, dedupe and merge behavior, append-only guarantees
  (an existing entry survives a re-run untouched), and slug stability.
- Front end: `vgm-radar.test.js` in jsdom against a fixture releases.json.
  Cover rendering, filters, search, localStorage round-trip, new-since
  badging, and YT search URL construction including encoding edge cases
  (colons, ampersands, Japanese titles).
- Each half runs locally with one command. Document both in the README.

## Phase 2 backlog (do not build now, do not block on it)
- Firehose sources behind the same dedupe: Steam soundtrack new releases,
  Bandcamp video-game-music tag, VGMdb release calendar (note: VGMdb sits
  behind Cloudflare, unofficial scrapers need an authenticated cookie).
- Notability scoring: 2 or more independent sources means notable; a
  single-source item lands in a separate "Radar" tab instead of the main list.
- ytmusicapi resolution of real album links at collection time, with the
  search link kept as fallback.
- IGDB enrichment (cover art, platforms) via free Twitch developer creds.
- Optional weekly digest (the Action opens a GitHub issue or sends an email
  summarizing the week's finds).
