# Scorekeep

A single-file, mobile-first PWA that tracks notable new video game soundtrack
releases from curated sources — open it, see what's new, tap a row, listen on
YouTube Music. Styled after the Sound Test screens where everyone first binged
VGM. Sibling of snap-workbench and home-bar.

Two halves, strictly separated: a Python collector runs on a daily GitHub
Actions cron and folds releases append-only into `data/releases.json`;
`index.html` (no framework, no build step) just renders that JSON. Stars,
listened marks, hides, and per-track ♥s are yours alone — they live in
`localStorage` (`vgm-v1`) and never touch the shared JSON.

The catalog is split for speed: `data/releases.json` carries every row
while each full tracklist lives in `data/tracks/<id>.json`, fetched only
when a view needs it. On the row, `tracksN` is the track count and the
completed-check marker (absent means never checked, 0 means checked and
nothing found), and `playsTotal` feeds the "most played" sort without
loading a single tracklist. Every row also carries `medium` (`game`,
`film`, or `tv`, ahead of the film/TV expansion); for film and TV rows
the `game` field holds the film or show title. The one-time split lives
in `collector/split_tracks.py` and stays in the daily workflow as an
idempotent no-op. The feed renders 60 rows per page with a MORE sentinel,
plus a year-jump picker and a back-to-top control.

| source | what it is | filter |
| --- | --- | --- |
| Steam Soundtracks | catalog: every album shipped on Steam | newest 25, released only |
| IGDB + YT Music | catalog: notable game releases that have a real album | last 14 days, hypes ≥ 5, strict album match |
| TMDb film + YT Music | catalog: film scores with a real album | last 14 days, 5+ votes, composer-vouched match |
| TMDb TV + YT Music | catalog: one row per season score album | last 60 days, 10+ votes, composer-vouched match |

The editorial and community feeds were dropped at CJ's request because
their headline rows had no album to play: r/gamemusic (2026-07-28),
NOWPLAYING (2026-07-30, rows deleted), and Blip Blop and VGMO (2026-09-18,
rows retired so TRACK numbers hold; VGMO's Final Symphony II, which has an
album, stays). Their parsers stay for the tests.

Film and TV rows follow the game rules with a screen-specific matcher:
the album must carry soundtrack wording, tribute and karaoke acts are
rejected, and the composer TMDb credits ("Original Music Composer" for
film, `aggregate_credits` for TV) has to appear among the album artists,
with the release era as fallback. A film with no findable score album is
skipped, never seeded. `TMDB_API_KEY` (free at themoviedb.org) rides in
Actions secrets; without it the two TMDb sources warn and skip.

On equal dates the list ranks editorial picks above catalog rows above
community rows (a few early community rows remain in the data from v1).
A resolver also backfills direct YouTube Music album links (`ytmAlbumUrl`)
for recent rows when an album title matches exactly after normalization —
rows with one open the album; everything else opens a YTM search. IGDB needs
`TWITCH_CLIENT_ID` / `TWITCH_CLIENT_SECRET` (free at dev.twitch.tv) in the
environment; without them that source warns and the rest still run.

Rows carry cover art (`art`): YTM album thumbnails when matched, Steam
header images, IGDB game covers as fallback. Steam rows also derive the
game name from the album title, so game/composer search actually hits.

`collector/backfill.py` (dispatch `.github/workflows/backfill.yml`) walks
the classics into the catalog: Steam's most-reviewed soundtracks plus
IGDB's top-rated games (200+ ratings) checked against YTM. Capped per run
with a committed cursor (`collector/backfill-state.json`) — dispatch until
it logs "backfill complete".

## Wanted list

Some titles have no soundtrack on YouTube Music at all (Spider-Man 3,
Heroes, Castlevania 2017), so they leave no row, and nothing revisits them:
the daily window has moved on and the backfill walks each vote band once.
`collector/wanted.json` is the short list of titles worth waiting for, and
`collector/check_wanted.py` (a daily step) searches every one again, with
the same title gate and one-album-one-row guards as the daily leg. The run
an album finally appears, the row is added by itself, its tracklist is
read, and the entry is stamped `got` and never searched again. Add a title
with `python collector/check_wanted.py --add film/559`; the stored name is
a guard, so a mistyped id is reported instead of quietly watching the wrong
film. Games are not on the list: the game legs walk every day anyway.

## Mood tags

The collector tags tracks with moods from a fixed twenty-word vocabulary
(`collector/moods.json`, version 2; version 1's sixteen words are kept in
`collector/moods-v1.json`) using Claude Haiku, one call per album; the app
never calls an AI API and carries no key. The daily run tags albums first
seen in the last 30 days, capped at 40 a run, and skips with a warning
when `ANTHROPIC_API_KEY` is not set. `python collector/moods.py backfill
--cap N` (the "Mood tags backfill" workflow) tags the rest until it
reports "moods complete"; `--retag` tags an album again, and the "Mood
vocabulary switch" workflow retags the catalog through a Message Batch at
half price. Tags land as a `moods` list on each track and, on the row, the
three most common across its tracks (ties by plays); a reply with a word
outside the vocabulary is retried once, then the album waits for a later
run. Every run's tokens and dollars go to `collector/moods-state.json`.

## Playlists → your real YT Music account

Track likes (the ♥ on any track row) and the Library's Playlists cards
compose playlists from your own state — liked songs, queued albums'
tracklists, a 4★ mix, each with year/genre variants, and a **random mix**:
the most-played track from each of 30 albums drawn from the feed's current
medium (hidden albums excluded), reshuffled on every tap, its size (30)
adjustable on the card. Its **scores only** toggle, on by default, drops
every track the collector marked as a song: a film or TV track credited
to someone other than the score composer (the album stays, its songs
leave). The same toggle sits under Medium in the feed and library filter
sheets, off by default, and hides songs from expanded rows, album pages
and the ♥ songs view; it reads on the chip ("filters · film, scores
only") and does nothing under games, which are scores by definition.
Custom playlists
sit above the recipes: **+ new playlist** names one and drops you on the
feed, and the **+** on any track row saves to it YT Music-style — the
first save opens a picker, then that playlist stays the target for ten
minutes of adds ("saved to X · change" to override).

**+ new recipe** builds a playlist from rules instead of picks: source
(catalog, library, queue), medium, genre, scores only (off by default), a
year range, a composer, a rating floor, hearted albums only, scope and
console for games, then how many tracks per album (all, the top N by
plays, or ♥ tracks only), a cap (four presets or any number from 1 to
200) and an order (most played, album, newest, shuffle). The sheet counts "N tracks from M albums" live
as you change rules, the name defaults to a description of them ("4★+
film scores only, top 2 each") and can
be typed over, and a saved recipe re-evaluates every time: rate something
new and it is in. Recipes and custom lists ride in backups and
publish/export exactly like the built-ins. The app exports each
one as `playlist-<name>.json`; a local companion publishes it, because
playlist creation needs an authenticated YTM session and credentials never
belong in a static page:

```
pip install ytmusicapi
ytmusicapi browser                # one-time: paste headers -> browser.json
mv browser.json companion/        # gitignored, never committed
python companion/make_playlists.py playlist-*.json
```

Idempotent: playlists it created carry a `# scorekeep` marker in their
description and get topped up, never duplicated; a same-named playlist
without the marker is reported and left alone. Playlists published before
the rename carry `vgm-finder · ` names and the old `# vgm-finder` marker:
both are still recognized, and such a playlist is topped up and renamed to
the `Scorekeep · ` prefix on its next publish. The random mix is the one
exception to topping up: its export carries `"replace": true`, so a
re-publish makes the playlist match the new draw instead of piling 30 more
tracks on. Tracks without a videoId are search-resolved with the
collector's strict matcher — anything it can't confidently place is listed
instead of guessed.

### Phone publish (one tap, no PC)

The Playlists view can send an export straight from the phone: a private
repo ([vgm-publisher](https://github.com/cjmerc39/vgm-publisher)) holds
`browser.json` as an Actions secret and runs the same companion script on
`repository_dispatch`. The app POSTs the export to that repo's dispatch
endpoint, so all it needs is a fine-grained GitHub token:

1. github.com → Settings → Developer settings → Personal access tokens →
   Fine-grained tokens → Generate new token.
2. Repository access: **only vgm-publisher**. Permissions: **Contents:
   read and write** (lets it dispatch) and **Actions: read** (lets the
   app report ✓/✗; skip it and publishes are fire-and-forget). Expiry:
   your call — a year is a fine trade against re-pasting.
3. Paste the token into the Playlists view's connect box.

The token lives in its own localStorage key, never rides along in state
backups, and "disconnect" forgets it. Kill switches: revoke the token
(GitHub → token settings) and sign out of the YTM session (Google
security → your devices) — either instantly disables publishing.

## Run the collector locally

```
pip install -r collector/requirements.txt
python collector/collect.py       # writes data/releases.json
python -m pytest collector companion   # collector + playlist-companion tests
```

## Run the front-end tests

```
npm i jsdom
node vgm-finder.test.js
```

## Icons

`icon-180/192/512.png` (an amber play glyph with scanlines) are generated by
`node make-icons.js` — no dependencies.

## Spec

The full build spec and data model are in `VGM-RADAR-SPEC.md`.
