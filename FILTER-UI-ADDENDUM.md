# FILTER-UI-ADDENDUM.md, addendum to FILM-TV-SPEC

## Why
After Phase A the feed's control row is eleven chips across five wrapping
rows on an iPhone, mixing sorts, scope filters, and two actions (year jump,
random). The first release renders below the middle of the screen. This
addendum replaces that with one row that fits without wrapping or sideways
scrolling. It is a layout change only. No collector work, no data changes,
no new state beyond what is listed.

Do this before Phase B, so the medium chips land in the new layout instead
of the old one.

## Process
1. Read this addendum and the current `renderControls`, `renderSheet`,
   `pickerHtml`, and the sheet CSS in index.html. The playlist picker sheet
   is the component to reuse; do not build a second sheet.
2. Before any UI work: confirm personal state survived Phase A. Open the
   deployed app in a fresh Safari tab on the phone and check that Queue,
   Library, liked songs, and custom playlists show what they showed before
   the update. Report the counts. If anything is 0 that was not 0 before,
   stop and fix that first.
3. Build, test in jsdom, verify on the phone at 390px wide, get sign-off.

## Feed control row
One row, left aligned, never wraps, never scrolls. Exactly three chips,
in this order. Existing chip styling; the selected/filled style is used
only as described.

1. **Sort chip.** Label is the current sort's name with a trailing ▾:
   `newest ▾`, `oldest ▾`, `a–z ▾`, `added ▾`, `most played ▾`. Never
   filled (a sort is always active, so filled would carry no information).
   Tap opens the sheet (see Sheets) with the five sorts as full-width rows;
   the current one shows a leading ✓.
2. **Filters chip.** Label is `filters` when nothing is on. When anything
   is on, the label lists what is on, lowercase, comma separated, in this
   order: company tier, console, genre, medium. Examples: `filters · indie`,
   `filters · indie, console`, `filters · rpg`, `filters · film, jazz`.
   Filled when anything is on. If the label would exceed the chip's max
   width, truncate with an ellipsis; the sheet is the full view. Tap opens
   the sheet with three sections in this order:
   - **Scope**: `all` / `big studios` / `indie` as a segmented row (one on
     at a time), then `console` as a toggle row. These are game-only
     filters: when the medium selection excludes games they render
     disabled with a one-line note "games only".
   - **Genre**: a list of genres present in the current medium selection,
     each with a count, `all` at the top, current one with ✓. If the list
     exceeds the sheet height it scrolls inside the sheet; the sheet itself
     does not grow past 70% of the viewport.
   - **Medium** (Phase B only; hidden until a non-game row exists):
     `all` / `games` / `film` / `tv` segmented row.
   Footer: `clear` on the left (resets scope, console, genre, medium to
   defaults, sheet stays open), `done` on the right (closes). Changes apply
   immediately behind the sheet, same as chips do today, so the list is
   already updated when the sheet closes.
3. **Year chip.** Label `year ▾`. Tap opens the sheet with the years present
   in the current filtered list, newest first, each with a count. Picking
   one closes the sheet and scrolls to that year's header, loading pages as
   needed. This replaces the current year dropdown. Keep the tap-on-year-
   header behaviour if it already exists; otherwise do not add it.

Random leaves the row. It becomes a small ▸ button in the header, right of
"synced <date>", same size and weight as the sync text, aria-label
"Random soundtrack". Behaviour unchanged.

Search stays where it is. The medium chips built in Phase A are removed
from the row and live only inside the filters sheet.

## Library control row
Same treatment, so the two views feel like one app:
- **Sort chip**: `heard on ▾` / `rating ▾` / `released ▾`, sheet with ✓.
- **♥ only** stays as a toggle chip (it is one state, a sheet would be
  slower than a tap).
- **songs** and **playlists** mode chips stay as they are.
- In songs and playlists modes, the row is unchanged from today except that
  the playlists year and genre selects become `year ▾` and `genre ▾` sheet
  chips using the same sheet.

## Sheets
- Reuse the existing sheet and scrim (the playlist picker). One sheet
  component, parameterised by content; `SHEET` or a sibling variable tracks
  which one is open. Only one sheet at a time.
- Rows are full width, at least 44px tall, label left, count or ✓ right.
- Swipe down on the sheet or tap the scrim closes it. Escape closes it on
  desktop.
- Respect prefers-reduced-motion for the slide.
- Sheet state is not persisted. Everything the sheet changes is already in
  `S` (feedSort, feedCo, feedConsole, feedGenre, feedMedium, libSort,
  libLiked, plYear, plGenre) and is persisted exactly as today.

## Header collapse (optional, do last, ask first)
Collapse the search box and control row when scrolling down in the list,
reveal on any scroll up, the way Spotify's header behaves. Ask before
building; if it fights iPhone Safari's own toolbar behaviour on the deployed
page, drop it rather than tune it.

## Tests (jsdom)
- Row renders exactly three chips in the feed, never a fourth, at every
  combination of state.
- Filters chip label: empty when defaults, filled and listing the active
  filters in the specified order otherwise, truncation when long.
- Sort sheet: picking a sort updates `S.feedSort`, re-renders the list,
  closes the sheet.
- Filters sheet: scope, console, genre, medium changes apply immediately;
  `clear` resets all four and keeps the sheet open; `done` closes it;
  game-only filters render disabled when medium excludes games.
- Year sheet: lists only years present in the current filtered list with
  correct counts; picking one scrolls to that header (assert the header is
  the scroll target and that paging loaded up to it).
- Library sort chip behaves the same as the feed sort chip.
- Random in the header still opens a random YTM link and respects filters.
- Old state (v3 and earlier) still loads; no new state keys are required.

## Do not
- Do not add a sideways-scrolling chip row anywhere.
- Do not use native `<select>` for anything the sheet now covers.
- Do not change chip typography, colours, or the row's spacing tokens.
- Do not use em dashes in copy or comments.
