# FILTER-SHEET-ADDENDUM-2.md, medium-first filters sheet

## Why
After Phase B the filters sheet stacks scope, console, every genre, and
then medium at the bottom, for a catalog where scope and console only
apply to games and genre vocabularies differ per medium. Medium moves to
the top and decides what else the sheet shows. Layout change only; no
collector work, no data changes, one state value added.

## Process
1. Read this addendum and the current filters sheet code (the `CSHEET`
   filters content, `feedRows`, the chip label builder, and the library
   equivalents).
2. Build, test in jsdom, verify on the phone at 390px, get sign-off.

## Filters sheet, feed
Top to bottom:

1. **Medium segment**, always first: `all` | `games` | `film + tv`.
   Segmented row, one on at a time. Rendered only when at least one
   non-game row exists in the catalog (true today); if none exist the
   sheet behaves as if `games` were selected and hides the segment.
2. Content below the segment depends on the selection:
   - **all**: nothing else. No scope, console, or genre. The sheet body
     is just the segment plus the footer.
   - **games**: scope segment (`all` | `big studios` | `indie`), console
     toggle, then the game genre list with counts (genres present among
     game rows only).
   - **film + tv**: a second segment `both` | `film` | `tv`, then the
     genre list with counts for the rows matching that sub-selection
     (film genres, tv genres, or the union when `both`). No scope, no
     console.
3. **Footer**: `clear` left (resets medium to `all`, scope to `all`,
   console off, genre to `all`, sub-segment to `both`; sheet stays open),
   `done` right (closes). Changes apply immediately behind the sheet.

Switching medium does not wipe the other selections; they are stored but
inert. Example: pick `games`, turn on `indie`, switch to `film + tv`,
switch back to `games`: `indie` is still on. Only `clear` resets.

Genre selection is per medium: `feedGenre` is keyed by medium in memory
so a game genre pick does not leak into the film list. Store it as a
small object `{game: "rpg", screen: "thriller"}` or equivalent; the
existing single-value form migrates to `{game: <old value>}`.

## State
- `feedMedium` gains the value `screen` (film + tv together). Full set:
  `all`, `game`, `screen`, `film`, `tv`. `film` and `tv` are the
  sub-segment states; `screen` is `both`. `validateState` accepts old
  values unchanged.
- No other new keys. Bump the state version if the genre storage shape
  changes; old backups must import.

## Chip label
`filters` when everything is at defaults. Otherwise, in this order,
lowercase, comma separated: medium (omit when `all`), scope (games only,
omit when `all`), `console` (games only, when on), genre (omit when
`all`). Examples:
- `filters · games`
- `filters · games, indie, console`
- `filters · games, rpg`
- `filters · film + tv`
- `filters · film, thriller`
- `filters · tv`
Filled when the label is anything other than `filters`. Truncation rule
from the first addendum still applies (label gives way first, chip row
never wraps).

Scope, console, and game genre never appear in the label unless medium is
`games`, even if stored on. Film/TV genre never appears unless medium is
`screen`, `film`, or `tv`.

## feedRows
Filtering follows the label exactly: game-only filters apply only when
medium is `game`; the film/TV genre applies only under `screen`, `film`,
or `tv`; under `all` only search and hidden state apply. Random respects
the same rules.

## Library
Same sheet, same rules, driven by `libMedium` with the same value set.
The playlists view's genre chip uses the medium-keyed genre store too.

## Tests (jsdom)
- Sheet renders only the medium segment under `all`; scope, console, and
  game genres under `games`; the sub-segment and film/TV genres under
  `film + tv`; never all at once.
- Genre lists contain only genres present in the selected medium, with
  correct counts; `both` shows the union.
- Switching medium keeps inert selections; `clear` resets everything and
  keeps the sheet open; `done` closes.
- Genre selection is independent per medium.
- Label matches the examples above for each combination; inert filters
  never appear in the label.
- `feedRows` ignores inert filters (an `indie` selection under `film`
  filters nothing).
- Old state with a single-value `feedGenre` and any prior `feedMedium`
  loads and migrates.
- Random under `film + tv` never returns a game row.

## Do not
- No cycling buttons: every state is visible as a segment.
- No merged genre list under `all`.
- No native `<select>`.
- Do not change chip or sheet styling, only content and order.
- No em dashes in copy or comments.
