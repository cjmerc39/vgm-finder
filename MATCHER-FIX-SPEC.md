# MATCHER-FIX-SPEC.md, film and TV matcher corrections and re-walk

## Why
The discovery investigation found that the film/TV matcher rejects correct
albums for five distinct reasons, ranks a subtitle match above an exact
one, and has left at least three rows wearing the wrong album. Separately,
the daily TV leg only looks at premiere dates, so new seasons of existing
shows never enter the feed, which defeats the reason TV rows are per
season.

Fix the matcher, then re-walk everything already checked and correct wrong
rows, then fix the daily window and the bookkeeping. The vote bars stay
where they are until the re-walk yield is known: walking 9,600 more titles
with the current matcher would repeat the same mistakes at a larger scale,
and checked titles are never revisited.

## Process
1. Read this spec, the investigation report, the screen matcher in
   collect.py, backfill.py, and the probe added during the investigation.
2. Report the plan, including how the re-walk identifies and corrects rows
   that already hold the wrong album. Wait for sign-off.
3. Phase 1 (matcher), Phase 2 (re-walk), Phase 3 (daily window and
   bookkeeping), in that order, each verified before the next.

## Phase 1: matcher corrections

Each change below gets a fixture built from the real album data the
investigation captured, plus the knockoffs already in the fixtures.

1. **Exact title plus soundtrack wording needs no composer corroboration.**
   When the album title normalizes to exactly the TMDb title and carries
   soundtrack wording, accept it. Recovers Jurassic Park and Back to the
   Future Part II.
2. **Bare-title acceptance, narrow.** When the album title normalizes to
   exactly the TMDb title with no soundtrack wording at all, accept it
   only when the composer is credited, or when the album has meaningful
   play counts and the year is within two. This is the class where the
   album is credited to the show rather than the composer (Infinity Train).
   Tag these rows with a `weakMatch: true` flag so they can be audited or
   swept later. Nothing in the UI needs to show it.
3. **Franchise prefix and suffix tolerance.** Accept an album whose
   normalized title contains the TMDb title with an additional franchise
   prefix or suffix when the credited composer appears in the artists and
   the album year is within two years of the release. Recovers The Empire
   Strikes Back, Return of the Jedi.
4. **TMDb title longer than the album title.** Accept when the album title
   is a subset of the TMDb title after stripping episode markers
   ("Episode I - "), with the same composer and year conditions as 3.
   Recovers Episodes I to III.
5. **Ranking: exact beats extended, always.** An exact normalized title
   match outranks any prefix, suffix, or subtitle match regardless of year
   proximity. This is what let "Back To The Future, Pt. 3" beat the real
   Back to the Future album.
6. **Global resolution order.** Within a run, resolve exact matches for all
   candidates before extended matches, so an album that exactly matches one
   title is never claimed by a different title through the tolerant rules.
   This is what keeps "The Lost World: Jurassic Park" with The Lost World.
7. **Abbreviation normalization.** `Pt.` and `Pt` normalize to `Part`,
   `Vol.` to `Volume`, before the sequel-numeral guard runs, so numeral
   tails are caught in either spelling.
8. **Non-English titles.** Run a second YTM query using TMDb's
   `original_title` when it differs from `title`. Recovers the Ip Man
   sequels, whose only albums are Chinese-titled with the composer credited
   in Japanese. Composer corroboration will not fire on these, so they land
   under rule 2 with `weakMatch`.

Rules that do not change: no search-only rows, one album to one row, the
tribute and karaoke blacklist, the sequel numeral guard.

### Phase 1 verification
Run the probe, unchanged in shape, over the full list from the
investigation plus the existing 40-title simulation set. Report per title:
accepted or rejected, which rule fired, and for accepted rows whether the
album is correct by eye. Do not proceed to Phase 2 until that report is
signed off. Specifically confirm no regression: the knockoffs previously
rejected are still rejected.

## Phase 2: re-walk and correction

1. **Reset the checked sets** for film and TV so every previously checked
   title is evaluated again under the new matcher. Preserve
   `backfill-state.json` structure; add whatever cursor the re-walk needs.
2. **Correct wrong rows.** A row that already holds an album is not
   immutable in this pass. When the re-walk finds a better match for a row
   under the new ranking, replace the album, art, tracks, `playsTotal`, and
   composer on that row, and free the old album so its rightful row can
   claim it. Log every correction (row id, old album, new album) so the
   set is reviewable.
3. **Audit the whole catalog, not just the known three.** The three wrong
   rows were found by spot-checking four franchises, so the real count is
   unknown. The re-walk must re-evaluate every film and TV row, not only
   those without an album.
4. **Report silent drops.** The one-album-one-row guard dropped 28 rows
   during the first backfill without logging which. Log every drop with
   both row ids from now on, and include the list in the run summary.
5. Capped runs with a committed cursor, same pattern as the original
   backfill. Report the final tally: rows corrected, rows added, rows
   dropped, and the film and TV hit rates before and after.

Game rows are out of scope. Do not re-walk or modify them.

## Phase 3: daily collection and bookkeeping

1. **TV window.** The daily TV leg currently filters on a show's premiere
   date, so a new season of an older show never appears. Change it to
   discover recent season releases rather than recent shows: use TMDb's
   season air dates (for example `discover/tv` with
   `first_air_date` replaced by an air-date window on seasons, or the
   changes/season endpoints if that is what actually works). Report what
   TMDb supports here before building, since this is the one place the
   spec is guessing.
   Verification: a show that premiered years ago but released a season
   within the window must appear.
2. **Bookkeeping crash safety.** One run lost two TMDb connections, threw
   away its record of what it had checked, and still advanced its cursor,
   leaving 23 films and 20 shows looked up but unrecorded. Make the checked
   set and the cursor advance together or not at all. Re-mark those 43
   titles as unchecked as part of Phase 2's reset, which handles them
   anyway.
3. **Weak match visibility.** Add a count of `weakMatch` rows to the run
   summary so the class stays observable.

## Bars
`FILM_BAR` and `TV_BAR` stay at 1000 and 500 for now. After the re-walk
reports its yield, propose new bars with the expected row count and run
count, and wait for sign-off before any lower-band walk. Infinity Train,
Scavengers Reign, and Common Side Effects sit below the TV bar and are the
motivating cases, so include them as named test titles in that proposal.

## Tests
- Collector: a fixture per numbered matcher rule above, each with the real
  album data from the investigation, plus the existing knockoffs to prove
  no regression. Cover the ranking rule and the global resolution order
  explicitly, including the Jurassic Park and Lost World pair.
- Correction path: a row holding a wrong album is corrected and the freed
  album becomes claimable by the right row, in either processing order.
- Crash safety: a simulated failure mid-run leaves the checked set and
  cursor consistent.
- `weakMatch` is set only by rule 2 and never by an exact or
  composer-corroborated match.

## Do not
- Do not lower the vote bars in this work.
- Do not touch game rows.
- Do not relax the tribute, karaoke, or "music inspired by" blacklist.
- Do not add search-only rows for any medium.
- No em dashes in copy or comments.

## Amendments approved 2026-09-13 (plan sign-off)
1. Rule 1 keeps its guard: composer credited, or the album year within two.
   Without it a re-recording ("Music from Rogue One: A Star Wars Story",
   2022) passes as exact.
2. `weakMatch` is set only when rule 2 accepts without a composer credit.
   Jurassic Park and Back to the Future Part II recover through rule 2's
   composer path and are not weak. Play threshold 100,000 total plays.
3. Ranking is credited composer first, then exact over extended, then fewer
   extra words, then year. Otherwise an uncredited exact upload beats a
   real album whose series wording the matcher did not know.
4. Rule 3 measures TV albums against season air dates, not the premiere.
5. Rule 4 strips episode markers only, never a general subset.
6. Rule 8 adds Chinese and Japanese soundtrack wording and composer aliases
   from TMDb `also_known_as`; "Book N" is a TV season marker.
7. Orphan rows (wrong album, no correct album exists) are retired with
   `retired: true` plus a front-end change that hides them except where
   the user has personal state for them.
8. A review stop between resolve and apply, reporting corrections,
   additions, orphans, and unverified rows.
9. The lookup cap stays at 250 per run.
