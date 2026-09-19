const { JSDOM } = require('jsdom');
const fs = require('fs');
const html = fs.readFileSync('index.html', 'utf8');

const T = (n) => Date.parse(n); // shorthand: ISO -> ms
const LAST_VISIT = T('2026-07-25T00:00:00Z');
const TODAY = (() => { const d = new Date(), p = n => String(n).padStart(2, '0');
  return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()); })();

const FIXTURE = {
  updatedAt: '2026-07-28T10:00:00Z',
  releases: [
    { id: 'chrono-cross-the-radical-dreamers-edition', title: 'Chrono Cross: The Radical Dreamers Edition OST',
      albumTitle: 'Chrono Cross: The Radical Dreamers Edition (Original Soundtrack)',
      game: 'Chrono Cross', composers: ['Yasunori Mitsuda'], date: '2026-06-01', console: true,
      sources: [{ name: 'vgmo', type: 'editorial', url: 'https://vgmonline.net/a', seenAt: '2026-07-01T10:00:00Z' }],
      ytmSearchUrl: 'https://music.youtube.com/search?q=Chrono+Cross%3A+The+Radical+Dreamers+Edition+OST+soundtrack',
      ytmAlbumUrl: null, art: null, notable: true },
    { id: 'hades-ii', title: 'Hades II Original Soundtrack', game: 'Hades II', composers: ['Darren Korb'], date: '2026-07-20',
      company: 'Supergiant Games', console: true, ytmPlaylistId: 'OLAK5uy_plHades', genres: ['Role-playing (RPG)'],
      tracks: [{ title: 'No Escape', plays: '1.2M plays', videoId: 'vidNE' },
               { title: 'Quiet Interlude', plays: '10 plays', videoId: 'vidQI' },
               { title: 'The Painted World', plays: '900K plays', videoId: 'vidPW' },
               { title: 'Coral Crown', plays: '500K plays', videoId: 'vidCC' },
               { title: 'Bonus Reel', plays: null, videoId: null }],
      sources: [{ name: 'nowplaying', type: 'editorial', url: 'https://nowplaying.cool/h', seenAt: '2026-07-10T10:00:00Z' },
                { name: 'r/gamemusic', type: 'community', url: 'https://reddit.com/h', seenAt: '2026-07-11T10:00:00Z' }],
      ytmSearchUrl: 'https://music.youtube.com/search?q=Hades+II+Original+Soundtrack+soundtrack',
      ytmAlbumUrl: 'https://music.youtube.com/playlist?list=OLAK5uy_hades2',
      art: 'https://example.com/art/hades"><script>bad</script>.jpg', notable: true },
    { id: 'ratchet-clank-rift-apart', title: 'Ratchet & Clank: Rift Apart OST', game: null, composers: [], date: '2026-07-18', console: true,
      sources: [{ name: 'blipblop', type: 'editorial', url: 'https://blipblop.net/r', seenAt: '2026-07-12T10:00:00Z' }],
      ytmSearchUrl: 'https://music.youtube.com/search?q=Ratchet+%26+Clank%3A+Rift+Apart+OST+soundtrack',
      ytmAlbumUrl: null, art: null, notable: true },
    { id: 'ゼルダの伝説', title: 'ゼルダの伝説 ティアーズ オブ ザ キングダム OST', game: null, composers: [], date: '2026-07-15',
      topTracks: [{ title: 'メインテーマ', plays: null }, { title: 'ハイラル平原', plays: null }],
      sources: [{ name: 'igdb', type: 'catalog', url: 'https://www.igdb.com/games/z', seenAt: '2026-07-13T10:00:00Z' },
                { name: 'igdb', type: 'catalog', url: 'https://www.igdb.com/games/z2', seenAt: '2026-07-14T10:00:00Z' }],
      ytmSearchUrl: 'https://music.youtube.com/search?q=%E3%82%BC%E3%83%AB%E3%83%80%E3%81%AE%E4%BC%9D%E8%AA%AC+OST+soundtrack',
      ytmAlbumUrl: null, art: null, notable: true },
    { id: 'evil', title: '<img src=x onerror="window.__pwned=1">Evil OST', game: null, composers: [], date: '2026-07-18', console: false,
      sources: [{ name: 'r/gamemusic', type: 'community', url: 'https://reddit.com/e', seenAt: '2026-07-14T10:00:00Z' }],
      ytmSearchUrl: 'https://music.youtube.com/search?q=Evil+OST+soundtrack',
      ytmAlbumUrl: null, art: null, notable: true },
    { id: 'fresh-drop', title: 'Fresh Drop: A Brand New Soundtrack', game: 'Fresh Drop', composers: ['New Person'], date: '2026-07-28',
      company: 'Nintendo', console: true, genres: ['Platform'],
      sources: [{ name: 'nowplaying', type: 'editorial', url: 'https://nowplaying.cool/f', seenAt: '2026-07-27T09:00:00Z' }],
      ytmSearchUrl: 'https://music.youtube.com/search?q=Fresh+Drop%3A+A+Brand+New+Soundtrack+soundtrack',
      ytmAlbumUrl: null, art: null, notable: true },
  ],
};

function makeDom(fetchImpl, prefill, standalone) {
  const errors = [];
  const dom = new JSDOM(html, {
    runScripts: 'dangerously', url: 'https://example.com/',
    beforeParse(w) {
      w.fetch = fetchImpl;
      if (standalone) Object.defineProperty(w.navigator, 'standalone', { value: true, configurable: true });
      w.open = (url) => {
        w.__opened = url;
        w.__handle = { opener: 'leaky', closed: false, close(){ this.closed = true; } };
        return w.__handle;
      };
      if (typeof prefill === 'string') w.localStorage.setItem('vgm-v1', prefill);
      else if (prefill) w.localStorage.setItem('vgm-v1', JSON.stringify(prefill));
    },
  });
  dom.window.addEventListener('error', e => errors.push(e.message));
  return { w: dom.window, d: dom.window.document, errors };
}
const okFetch = (data) => async () => ({ ok: true, status: 200, json: async () => data });
const sleep = ms => new Promise(r => setTimeout(r, ms));

// boot the main dom with LEGACY v1 state: the migration is under test
const { w, d, errors } = makeDom(okFetch(FIXTURE),
  { v: 1, starred: { 'hades-ii': true }, listened: { 'chrono-cross-the-radical-dreamers-edition': true },
    hidden: { 'evil': true }, lastSeen: LAST_VISIT, filter: 'starred', showHidden: false });

(async () => {
  await sleep(120);
  const assert = (c, m) => { if (!c) { console.error('FAIL:', m); process.exitCode = 1; } else console.log('ok  :', m); };
  const rows = () => [...d.querySelectorAll('#list .row:not(.ghost)')];
  const rowById = (id) => d.querySelector(`#list .row[data-id="${id}"]`);
  const stored = () => JSON.parse(w.localStorage.getItem('vgm-v1'));
  const tab = (v) => d.querySelector(`#tabbar button[data-v="${v}"]`);
  const S = (expr) => w.eval(expr);
  const inSheet = (dd, sel) => dd.querySelector('#sheetwrap ' + sel);
  const sheetEl = (dd) => dd.querySelector('#sheetwrap #sheet');
  const pickFeedSort = async (k) => { d.querySelector('#c-sort').click(); inSheet(d, `[data-shsort="${k}"]`).click(); await sleep(20); };

  assert(errors.length === 0, 'no runtime errors on boot' + (errors.length ? ' -> ' + errors.join(' | ') : ''));

  // ---------- legacy migration ----------
  assert(stored().v === 3, 'v1 state migrated and persisted at a version old builds can still read');
  assert(stored().feedMedium === 'all' && stored().libMedium === 'all', 'medium chips default to all');
  assert(!('starred' in stored()) && !('listened' in stored()) && !('hidden' in stored()), 'legacy keys retired');
  assert(stored().entries['hades-ii'].liked === true, 'starred became liked');
  assert(stored().entries['chrono-cross-the-radical-dreamers-edition'].status === 'listened', 'listened became status listened');
  assert(stored().entries['chrono-cross-the-radical-dreamers-edition'].listenedOn === null, 'migrated listen has no invented date');
  assert(stored().entries['evil'].status === 'hidden', 'hidden stayed hidden');
  assert(stored().lastSeen > LAST_VISIT, 'lastSeen survived migration then advanced on visit');

  // ---------- feed basics survive ----------
  assert(rows().length === 5, 'feed shows 5 rows (hidden row excluded)');
  assert(rows()[0].dataset.id === 'fresh-drop', 'newest release renders first');
  assert(rows()[0].querySelector('.tno').textContent === 'TRACK 006', 'catalog numbers still pinned to append order');
  assert(rows()[1].dataset.id === 'hades-ii' && rows()[2].dataset.id === 'ratchet-clank-rift-apart',
    'date sort with editorial-over-community tiebreak intact');
  assert(d.querySelectorAll('#list .new').length === 1 && rowById('fresh-drop').querySelector('.new') !== null,
    'NEW badging preserved through migration');
  assert(w.__pwned === undefined && d.querySelector('#list script') === null, 'hostile titles still render inert');
  assert(rowById('chrono-cross-the-radical-dreamers-edition').classList.contains('heard'), 'migrated listen dims its feed row');

  // ---------- cover art ----------
  const hadesImg = rowById('hades-ii').querySelector('.rart img');
  assert(hadesImg !== null && hadesImg.getAttribute('loading') === 'lazy', 'art renders as a lazy image');
  assert(hadesImg.getAttribute('src').includes('hades'), 'art src comes from the shared data');
  assert(rowById('hades-ii').querySelectorAll('script').length === 0, 'hostile art URL renders inert');
  assert(rowById('fresh-drop').querySelector('.rart.noart') !== null, 'artless rows get the placeholder tile');

  // ---------- tabs and counts ----------
  assert(tab('feed').classList.contains('on'), 'feed tab active by default');
  assert(tab('feed').innerHTML.includes('1 NEW'), 'feed tab carries the new-since count');
  assert(tab('queue').textContent.includes('0'), 'queue count starts 0');
  assert(tab('library').textContent.includes('1'), 'library counts the migrated listen');

  // ---------- header: random chip in the right slot, one line ----------
  assert(d.querySelector('#topbar #hrandom') !== null && d.querySelector('#sync') === null,
    'the random chip owns the header right slot and synced moved out');
  assert(d.querySelector('#hrandom').textContent === 'random ▸', 'the chip keeps its original label');
  assert(/#topbar\{[^}]*flex-wrap:nowrap/.test(d.querySelector('style').textContent),
    'the header row cannot wrap with the chip present');
  // the rename: SCOREKEEP wordmark, Sound Test subtitle kept. Measured in
  // headless Edge at 390px with Silkscreen 19px/1px spacing: SCOREKEEP is
  // 151.5px and the row uses 387px of 390; VGM FINDER (10 characters) was
  // 164.4px and spilled 10px into the right padding. Nine characters is the
  // budget for this row.
  assert(d.querySelector('#topbar h1').textContent === 'SCOREKEEP', 'the header wordmark is SCOREKEEP');
  assert(d.querySelector('#topbar h1').textContent.length <= 9, 'the wordmark stays within the measured 390px budget');
  assert(d.querySelector('#topbar .sub').textContent === 'Sound Test', 'the Sound Test subtitle stays');
  assert(d.querySelector('title').textContent === 'Scorekeep', 'the page title is Scorekeep');
  assert(d.querySelector('#colophon').textContent.includes('synced jul 28'),
    'the synced date lives in the colophon next to collected daily');
  assert(d.querySelector('#colophon').textContent.includes('6 soundtracks'),
    'the colophon counts soundtracks, not tracks');

  // ---------- album-name labels ----------
  assert(rowById('chrono-cross-the-radical-dreamers-edition').querySelector('.rtitle').textContent
    === 'Chrono Cross: The Radical Dreamers Edition (Original Soundtrack)',
    'rows label by resolved album name');
  assert(rowById('fresh-drop').querySelector('.rtitle').textContent.startsWith('Fresh Drop'),
    'rows without a resolved album keep their title');

  // ---------- feed sort chip + sheet ----------
  assert(d.querySelectorAll('#subctl button').length === 3, 'feed control row is exactly three chips');
  assert(d.querySelector('#c-sort').textContent.trim() === 'newest ▾', 'sort chip names the active sort');
  assert(!d.querySelector('#c-sort').classList.contains('on'), 'sort chip never fills');
  d.querySelector('#c-sort').click();
  assert(d.querySelectorAll('#sheetwrap [data-shsort]').length === 5, 'sort sheet offers five sorts');
  assert(inSheet(d, '[data-shsort="date"] .shl').textContent.startsWith('✓'), 'current sort wears a leading check');
  inSheet(d, '[data-shsort="oldest"]').click(); await sleep(20);
  assert(sheetEl(d) === null, 'picking a sort closes the sheet');
  assert(rows()[0].dataset.id === 'chrono-cross-the-radical-dreamers-edition', 'oldest-first surfaces the back catalog');
  assert(stored().feedSort === 'oldest', 'feed sort persists');
  assert(d.querySelector('#c-sort').textContent.trim() === 'oldest ▾', 'chip label follows the sort');
  await pickFeedSort('az');
  assert(JSON.stringify(rows().map(r => r.dataset.id)) === JSON.stringify(
    ['chrono-cross-the-radical-dreamers-edition', 'fresh-drop', 'hades-ii', 'ratchet-clank-rift-apart', 'ゼルダの伝説']),
    'a–z sorts by the display label');
  await pickFeedSort('added');
  assert(rows()[0].dataset.id === 'fresh-drop', 'recently-added sort leads with the newest find');
  await pickFeedSort('date');
  assert(rows()[0].dataset.id === 'fresh-drop', 'newest-first restored');

  // ---------- year rails + company facets ----------
  assert(d.querySelectorAll('#list .yhead').length === 1
    && d.querySelector('#list .yhead').textContent === '2026', 'date sorts group rows under year rails');
  assert(d.querySelector('#c-filters').textContent === 'filters'
    && !d.querySelector('#c-filters').classList.contains('on'), 'filters chip reads neutral at defaults');
  d.querySelector('#c-filters').click();
  assert(d.querySelectorAll('#sheetwrap [data-shco]').length === 3, 'filters sheet offers the company tiers');
  inSheet(d, '[data-shco="big"]').click(); await sleep(20);
  assert(sheetEl(d) !== null, 'filter changes keep the sheet open');
  assert(rows().length === 1 && rows()[0].dataset.id === 'fresh-drop', 'big-studios facet keeps the Nintendo row');
  inSheet(d, '[data-shco="indie"]').click(); await sleep(20);
  assert(rows().length === 1 && rows()[0].dataset.id === 'hades-ii', 'indie facet keeps the Supergiant row');
  assert(stored().feedCo === 'indie', 'company facet persists');
  assert(d.querySelector('#c-filters').textContent === 'filters · indie'
    && d.querySelector('#c-filters').classList.contains('on'), 'filters chip fills and names the tier');
  inSheet(d, '#shconsole').click(); await sleep(20);
  assert(stored().feedConsole === true, 'console filter persists');
  assert(d.querySelector('#c-filters').textContent === 'filters · indie, console',
    'chip lists active filters in order');
  inSheet(d, '#shclear').click(); await sleep(20);
  assert(sheetEl(d) !== null, 'clear keeps the sheet open');
  assert(rows().length === 5 && stored().feedCo === 'all' && stored().feedConsole === false,
    'clear resets scope and console');
  assert(d.querySelector('#c-filters').textContent === 'filters', 'chip label returns to neutral');
  inSheet(d, '.shbody').scrollTop = 120;
  inSheet(d, '#shconsole').click(); await sleep(20);
  assert(inSheet(d, '.shbody').scrollTop === 120 && sheetEl(d).style.animation === 'none',
    'live-apply keeps the sheet scroll spot and skips the slide replay');
  assert(rows().length === 4 && rowById('ゼルダの伝説') === null,
    'console filter keeps confirmed console games, drops PC-only and unknown');
  inSheet(d, '#shconsole').click(); await sleep(20);
  assert(rows().length === 5, 'console filter toggles back off');

  // ---------- genre rows in the filters sheet + random listen ----------
  assert(inSheet(d, '#shgenrerow').textContent.includes('genre · all') && inSheet(d, '[data-shgenre]') === null,
    'the genre is one row naming its pick, no inline list');
  inSheet(d, '#shgenrerow').click(); await sleep(10);
  const platRow = inSheet(d, '[data-shgenre="Platform"]');
  assert(platRow !== null && platRow.querySelector('.shr').textContent === '1', 'genre rows carry counts');
  platRow.click(); await sleep(20);
  assert(rows().length === 1 && rows()[0].dataset.id === 'fresh-drop', 'genre facet filters the feed');
  assert(stored().feedGenre.game === 'Platform', 'genre choice persists in the game bucket');
  assert(d.querySelector('#c-filters').textContent === 'filters · platform', 'genre reads lowercase on the chip');
  assert(inSheet(d, '#shgenrerow').textContent.includes('genre · platform'), 'a pick returns to the filters with the row updated');
  inSheet(d, '#shgenrerow').click(); await sleep(10);
  inSheet(d, '[data-shgenre="all"]').click(); await sleep(20);
  assert(rows().length === 5, 'genre back to all');
  inSheet(d, '#shdone').click();
  assert(sheetEl(d) === null, 'done closes the filters sheet');
  w.__opened = null;
  w.eval('Math.random = () => 0');
  d.querySelector('#hrandom').click();
  assert(rowById('fresh-drop').getAttribute('aria-expanded') === 'true' && w.__opened === null,
    'header random expands a pick in-app instead of leaving the app');
  rowById('fresh-drop').click();

  // ---------- sheet handover and dismissal guards ----------
  d.querySelector('#c-sort').click();
  S(`addFlow('hades-ii', 'No Escape')`);
  assert(S('CSHEET') === null && inSheet(d, '#cp-name') !== null,
    'the save picker takes over an open control sheet cleanly');
  inSheet(d, '#scrim').click();
  assert(sheetEl(d) === null, 'one scrim tap closes the picker');
  d.querySelector('#c-filters').click();
  tab('library').click(); await sleep(20);
  assert(sheetEl(d) === null, 'switching views closes a control sheet');
  tab('feed').click(); await sleep(20);
  rowById('hades-ii').querySelector('[data-act="log"]').click();
  const lg1 = new w.Event('touchstart', { bubbles: true }); lg1.touches = [{ clientY: 80 }];
  sheetEl(d).dispatchEvent(lg1);
  const lg2 = new w.Event('touchend', { bubbles: true }); lg2.changedTouches = [{ clientY: 300 }];
  sheetEl(d).dispatchEvent(lg2);
  assert(sheetEl(d) !== null, 'swipe down never discards a logging draft');
  d.querySelector('#scrim').click();

  // ---------- expand, then listen ----------
  w.__opened = null;
  rowById('ratchet-clank-rift-apart').click();
  assert(rowById('ratchet-clank-rift-apart').getAttribute('aria-expanded') === 'true'
    && rowById('ratchet-clank-rift-apart').querySelector('.rx') !== null, 'row tap expands the detail panel');
  assert(w.__opened === null, 'expanding does not open YTM');
  rowById('ratchet-clank-rift-apart').querySelector('[data-act="listen"]').click();
  assert(w.__opened === 'https://music.youtube.com/search?q=Ratchet+%26+Clank%3A+Rift+Apart+OST+soundtrack',
    'listen opens the encoded YTM search URL untouched');
  rowById('ratchet-clank-rift-apart').click();
  assert(rowById('ratchet-clank-rift-apart').querySelector('.rx') === null, 'second tap collapses the panel');

  rowById('hades-ii').click();
  const hx = rowById('hades-ii').querySelector('.rx');
  assert(hx.textContent.includes('Supergiant Games'), 'expanded panel shows the studio');
  assert(hx.textContent.includes('TOP TRACKS') && hx.textContent.includes('No Escape')
    && hx.textContent.includes('1.2M plays'), 'top tracks list with play counts');
  const srcLink = hx.querySelector('a.xsrc');
  assert(srcLink && srcLink.getAttribute('href') === 'https://nowplaying.cool/h'
    && srcLink.getAttribute('target') === '_blank', 'coverage links go to the source articles');
  hx.querySelector('[data-act="listen"]').click();
  assert(w.__opened === 'https://music.youtube.com/playlist?list=OLAK5uy_hades2', 'album URL preferred when present');

  // iOS return-trip: the opened sheet is severed and closed when we regain focus
  assert(w.__handle.opener === null, 'opened window gets its opener severed');
  d.dispatchEvent(new w.Event('visibilitychange'));
  assert(w.__handle.closed === true, 'leftover sheet closes when the app becomes visible again');
  rowById('hades-ii').click();

  rowById('ゼルダの伝説').click();
  assert(rowById('ゼルダの伝説').querySelector('.rx').textContent.includes('FROM THE TRACKLIST'),
    'legacy topTracks rows keep the honest header');
  assert(rowById('ゼルダの伝説').querySelector('.xall') === null, 'no album page without a full tracklist');
  rowById('ゼルダの伝説').click();

  // ---------- the album page ----------
  rowById('hades-ii').click();
  const hx2 = rowById('hades-ii').querySelector('.rx');
  assert(hx2.textContent.includes('TOP TRACKS') && hx2.textContent.includes('No Escape'),
    'expanded top-3 derives from the full tracklist by plays');
  hx2.querySelector('[data-act="album"]').click();
  assert(d.querySelector('#album') !== null, 'All tracks opens the album page');
  assert(d.querySelector('#album .aart img') !== null, 'album art sits front and center');
  assert(d.querySelectorAll('#album .atrack').length === 5, 'every track listed in album order');
  assert(d.querySelector('#album .atrack[data-i="0"] .medal').textContent === '1', 'top track wears the 1');
  assert(d.querySelector('#album .atrack[data-i="2"] .medal').textContent === '2', 'second-most-played wears the 2');
  assert(d.querySelector('#album .atrack[data-i="1"] .medal') === null, 'low-play tracks get no medal');
  d.querySelector('#album .atrack[data-i="0"]').click();
  assert(w.__opened === 'https://music.youtube.com/watch?v=vidNE&list=OLAK5uy_plHades', 'tracks link to the song in album context, not the video');
  d.querySelector('#album .atrack[data-i="4"]').click();
  assert(w.__opened.startsWith('https://music.youtube.com/search?q=') && w.__opened.includes('Bonus%20Reel')
    && w.__opened.includes('Hades%20II'), 'unlinked tracks fall back to game + song search');
  d.querySelector('#album .aclose').click();
  assert(d.querySelector('#album') === null, 'close returns to the list');
  rowById('hades-ii').click();

  // friendly source labels, deduped per row
  assert(rowById('ゼルダの伝説').querySelector('.chip').textContent === 'catalog', 'igdb source displays as "catalog"');
  assert(rowById('ゼルダの伝説').querySelectorAll('.chip').length === 1, 'duplicate same-source chips collapse to one');

  // ---------- queue flow ----------
  w.__opened = null;
  rowById('fresh-drop').querySelector('[data-act="queue"]').click();
  assert(w.__opened === null, 'queueing does not open YTM');
  assert(stored().entries['fresh-drop'].status === 'queued', 'one tap queues');
  assert(stored().entries['fresh-drop'].queuedOn === TODAY, 'queue stamps today');
  rowById('ゼルダの伝説').querySelector('[data-act="queue"]').click();
  assert(tab('queue').textContent.includes('2'), 'queue tab counts 2');
  tab('queue').click();
  await sleep(20);
  assert(tab('queue').classList.contains('on') && stored().view === 'queue', 'queue tab activates and persists');
  assert(rows().length === 2, 'queue lists both queued rows');
  assert(rows()[0].dataset.id === 'fresh-drop', 'queue sorts by release date, newest first');
  assert(rows()[0].textContent.includes('queued'), 'queue rows show when they were queued');
  assert(rowById('ゼルダの伝説').querySelector('[data-act="queue"]') === null,
    'queue rows carry no remove button — nothing to fat-finger');
  tab('feed').click(); await sleep(20);
  rowById('ゼルダの伝説').querySelector('[data-act="queue"]').click();
  assert(stored().entries['ゼルダの伝説'] === undefined, 'unqueueing lives in the feed toggle and prunes the blank entry');
  tab('queue').click(); await sleep(20);
  assert(rows().length === 1, 'queue reflects the removal');

  // ---------- the logging ritual: two taps for a bare listen ----------
  rowById('fresh-drop').querySelector('[data-act="log"]').click();
  assert(d.querySelector('#sheet') !== null, 'log tap opens the sheet');
  assert(d.querySelector('#sh-date').value === TODAY, 'date prefilled to today');
  d.querySelector('#sh-save').click();
  await sleep(20);
  assert(d.querySelector('#sheet') === null, 'save closes the sheet');
  const fresh = stored().entries['fresh-drop'];
  assert(fresh.status === 'listened' && fresh.listenedOn === TODAY, 'bare save logs a listen dated today');
  assert(fresh.rating === null && fresh.liked === false && fresh.note === '', 'bare listen record still carries rating/liked/note fields');
  assert(fresh.queuedOn === null, 'listening clears the queue slot');
  assert(tab('queue').textContent.includes('0') && tab('library').textContent.includes('2'), 'counts follow the log');

  // ---------- full ritual: half stars, heart, note ----------
  tab('feed').click(); await sleep(20);
  rowById('ratchet-clank-rift-apart').querySelector('[data-act="log"]').click();
  d.querySelector('#sh-stars button[data-r="3.5"]').click();
  assert(S('SHEET.draft.rating') === 3.5, 'half-star tap sets 3.5');
  assert(d.querySelectorAll('#sh-stars .sfill')[3].style.width === '50%', 'fourth star renders half full');
  d.querySelector('#sh-heart').click();
  d.querySelector('#sh-note').value = 'rift apart <script>alert(1)</script> slaps';
  d.querySelector('#sh-note').dispatchEvent(new w.Event('input', { bubbles: true }));
  d.querySelector('#sh-date').value = '2026-07-26';
  d.querySelector('#sh-date').dispatchEvent(new w.Event('input', { bubbles: true }));
  d.querySelector('#sh-save').click();
  await sleep(20);
  const rr = stored().entries['ratchet-clank-rift-apart'];
  assert(rr.rating === 3.5 && rr.liked === true && rr.listenedOn === '2026-07-26', 'rating, heart, and edited date persist');
  assert(rr.note.includes('slaps'), 'note round-trips');

  // reopen for edit, clear the rating
  rowById('ratchet-clank-rift-apart').querySelector('[data-act="log"]').click();
  assert(S('SHEET.draft.rating') === 3.5 && d.querySelector('#sh-note').value.includes('slaps'), 'sheet reopens with saved values');
  d.querySelector('#sh-clear').click();
  assert(S('SHEET.draft.rating') === null, 'clear empties the rating');
  d.querySelector('#sh-save').click(); await sleep(20);
  assert(stored().entries['ratchet-clank-rift-apart'].rating === null, 'cleared rating persists');

  // ---------- library ----------
  tab('library').click(); await sleep(20);
  assert(rows().length === 3, 'library lists all listened rows');
  S(`editEntry('ratchet-clank-rift-apart', e => { e.rating = 3.5; })`);
  S(`editEntry('fresh-drop', e => { e.rating = 5; e.listenedOn = '2026-07-20'; })`);
  await sleep(20);
  assert(rows()[0].dataset.id === 'ratchet-clank-rift-apart', 'default sort: most recent listen first');
  assert(rows()[2].dataset.id === 'chrono-cross-the-radical-dreamers-edition', 'dateless migrated listen sinks');
  assert(d.querySelector('#c-libsort').textContent.trim() === 'heard on ▾', 'library sort chip names the sort');
  d.querySelector('#c-libsort').click();
  assert(inSheet(d, '[data-shlsort="listenedOn"] .shl').textContent.startsWith('✓'), 'current library sort checked');
  inSheet(d, '[data-shlsort="rating"]').click(); await sleep(20);
  assert(sheetEl(d) === null, 'library sort sheet closes on pick');
  assert(rows()[0].dataset.id === 'fresh-drop' && rows()[1].dataset.id === 'ratchet-clank-rift-apart',
    'rating sort: 5 before 3.5');
  assert(rows()[2].dataset.id === 'chrono-cross-the-radical-dreamers-edition', 'unrated sorts last on rating sort');
  assert(rowById('fresh-drop').querySelector('.minis').textContent === '★★★★★', 'five stars render');
  assert(rowById('ratchet-clank-rift-apart').querySelector('.minis').textContent === '★★★½', 'half star renders as ½');
  d.querySelector('#c-libsort').click();
  inSheet(d, '[data-shlsort="date"]').click(); await sleep(20);
  assert(rows()[0].dataset.id === 'fresh-drop' && rows()[2].dataset.id === 'chrono-cross-the-radical-dreamers-edition',
    'release-date sort uses the shared newest-first order');
  assert(rowById('ratchet-clank-rift-apart').querySelector('.rnote').textContent.includes('slaps'),
    'note shows on the library row');
  assert(rowById('ratchet-clank-rift-apart').querySelector('.rnote').textContent.includes('<script>')
    && d.querySelector('#list script') === null && w.__pwned === undefined,
    'note renders its markup as visible text, never as elements');
  // liked filter + per-row heart
  d.querySelector('#libliked').click(); await sleep(20);
  assert(rows().length === 1 && rows()[0].dataset.id === 'ratchet-clank-rift-apart', '♥ only filters to liked');
  rowById('ratchet-clank-rift-apart').querySelector('[data-act="like"]').click(); await sleep(20);
  assert(rows().length === 0 && d.querySelector('#list .state') !== null, 'unliking live empties the filter with a message');
  d.querySelector('#libliked').click(); await sleep(20);

  // ---------- clear a listen (reversibility) ----------
  rowById('fresh-drop').querySelector('[data-act="log"]').click();
  d.querySelector('#sh-unlog').click(); await sleep(20);
  assert(stored().entries['fresh-drop'].status === 'unsorted' && stored().entries['fresh-drop'].listenedOn === null,
    'clear this listen reverts status but keeps the entry');
  assert(stored().entries['fresh-drop'].rating === 5, 'rating survives a cleared listen');
  assert(tab('library').textContent.includes('2'), 'library count follows the cleared listen');

  // ---------- per-track likes: hearts on every track row ----------
  tab('feed').click(); await sleep(20);
  rowById('hades-ii').click();
  assert(rowById('hades-ii').querySelectorAll('.rx .tlike').length === 3, 'expanded top-3 rows each wear a heart');
  w.__opened = null;
  rowById('hades-ii').querySelector('.rx .tlike[data-t="No Escape"]').click(); await sleep(20);
  assert(JSON.stringify(stored().entries['hades-ii'].likedTracks) === JSON.stringify(['No Escape']),
    'one tap likes the track by title');
  assert(w.__opened === null, 'liking a track never leaves the app');
  assert(rowById('hades-ii').querySelector('.rx .tlike[data-t="No Escape"]').classList.contains('on'),
    'panel heart fills in place');
  rowById('hades-ii').querySelector('[data-act="album"]').click();
  assert(d.querySelector('#album .atrack[data-i="0"] .tlike').classList.contains('on'),
    'album page shows the same like');
  d.querySelector('#album .atrack[data-i="4"] .tlike').click(); await sleep(20);
  assert(stored().entries['hades-ii'].likedTracks.length === 2 && w.__opened === null,
    'album-page heart likes without playing the track');
  d.querySelector('#album .atrack[data-i="4"] .tlike').click(); await sleep(20);
  assert(JSON.stringify(stored().entries['hades-ii'].likedTracks) === JSON.stringify(['No Escape']),
    'second tap unlikes');
  d.querySelector('#album .aclose').click();
  rowById('hades-ii').click();
  rowById('ゼルダの伝説').click();
  rowById('ゼルダの伝説').querySelector('.rx .tlike').click(); await sleep(20);
  assert(stored().entries['ゼルダの伝説'].likedTracks.length === 1, 'legacy topTracks rows are likeable too');
  rowById('ゼルダの伝説').querySelector('.rx .tlike').click(); await sleep(20);
  assert(stored().entries['ゼルダの伝説'] === undefined, 'unliking the only fact prunes the entry');
  rowById('ゼルダの伝説').click();

  // ---------- liked songs view ----------
  tab('library').click(); await sleep(20);
  d.querySelector('#libsongs').click(); await sleep(20);
  assert(stored().libView === 'songs', 'songs view persists');
  assert(d.querySelector('#c-libsort') === null, 'the sort chip steps aside in songs view');
  assert(rows().length === 1 && rows()[0].classList.contains('song'), 'liked songs list the hearted tracks');
  assert(rows()[0].querySelector('.rtitle').textContent === 'No Escape'
    && rows()[0].querySelector('.rsub').textContent === 'Hades II'
    && rows()[0].querySelector('.rart img') !== null, 'song rows carry art, game, and track title');
  w.__opened = null;
  rows()[0].click();
  assert(w.__opened === 'https://music.youtube.com/watch?v=vidNE&list=OLAK5uy_plHades',
    'song row plays the track in album context');
  S(`toggleTrackLike('hades-ii', 'Bonus Reel')`); await sleep(20);
  w.__opened = null;
  d.querySelector('#list .row.song[data-t="Bonus Reel"]').click();
  assert(w.__opened.startsWith('https://music.youtube.com/search?q=') && w.__opened.includes('Bonus%20Reel')
    && w.__opened.includes('Hades%20II'), 'videoId-less songs fall back to game + title search');
  const qEl = d.getElementById('q');
  const qtype = (s) => { qEl.value = s; qEl.dispatchEvent(new w.Event('input', { bubbles: true })); };
  qtype('escape');
  assert(rows().length === 1 && rows()[0].dataset.t === 'No Escape', 'search sifts liked songs by title');
  qtype('');
  d.querySelector('#list .row.song[data-t="Bonus Reel"] .tlike').click(); await sleep(20);
  assert(rows().length === 1, 'row heart unlikes in place');
  S(`toggleTrackLike('hades-ii', 'No Escape')`); await sleep(20);
  assert(d.querySelector('#list .state').textContent.includes('NO LIKED SONGS'), 'empty songs view explains the ♡');
  S(`toggleTrackLike('hades-ii', 'No Escape')`); await sleep(20);

  // ---------- refetched tracklists reorder and repatch; likes follow the title ----------
  const REORDERED = JSON.parse(JSON.stringify(FIXTURE));
  const rh = REORDERED.releases.find(r => r.id === 'hades-ii');
  rh.tracks.reverse();
  rh.tracks.find(t => t.title === 'No Escape').videoId = 'vidNE2';
  const re2 = makeDom(okFetch(REORDERED), JSON.stringify(stored()));
  await sleep(120);
  const songRow2 = re2.d.querySelector('#list .row.song[data-t="No Escape"]');
  assert(songRow2 !== null, 'reordered refetch keeps the like matched by title');
  songRow2.click();
  assert(re2.w.__opened === 'https://music.youtube.com/watch?v=vidNE2&list=OLAK5uy_plHades',
    'the like rides the repatched videoId, not a stale index');

  // ---------- likedTracks ride the lifeboat ----------
  const dumpLT = S('JSON.stringify(buildExport())');
  S(`toggleTrackLike('hades-ii', 'No Escape')`);
  assert(stored().entries['hades-ii'].likedTracks.length === 0, 'stage: like removed before import');
  assert(S(`applyImport(${JSON.stringify(dumpLT)})`) === true
    && JSON.stringify(stored().entries['hades-ii'].likedTracks) === JSON.stringify(['No Escape']),
    'export→wipe→import round-trips likedTracks');
  assert(S(`applyImport('{"v":2,"entries":{"hades-ii":{"likedTracks":["No Escape","NO ESCAPE",7,"",null]}}}')`) === true
    && JSON.stringify(stored().entries['hades-ii'].likedTracks) === JSON.stringify(['No Escape']),
    'import sanitizes likedTracks: strings only, folded dupes collapse');
  assert(S(`applyImport(${JSON.stringify(dumpLT)})`) === true, 'state restored after sanitize check');

  // ---------- playlists: recipes, facets, export ----------
  d.querySelector('#libpl').click(); await sleep(20);
  assert(stored().libView === 'playlists', 'playlists view persists');
  assert(d.querySelectorAll('#list .plcard').length === 4, 'four built-in cards render');
  S(`editEntry('hades-ii', e => { e.status = 'queued'; e.rating = 4.5; })`);
  S(`editEntry('ゼルダの伝説', e => { e.status = 'queued'; })`); await sleep(20);
  const cardMeta = k => d.querySelector(`#list .plcard[data-plc="${k}"] .plmeta`).textContent;
  assert(cardMeta('liked').startsWith('1 track '), 'liked recipe counts the hearted track');
  assert(cardMeta('queue').startsWith('7 tracks'), 'queue recipe: full tracklists plus legacy top tracks');
  assert(cardMeta('rated').startsWith('3 tracks'), 'rated recipe takes the 4.5-star top-3');
  d.querySelector('#list .plcard[data-plc="liked"]').click(); await sleep(20);
  const plCard = () => d.querySelector('#list .plcard[data-plc="liked"]');
  assert(plCard().querySelector('.pltrack .t').textContent === 'No Escape'
    && plCard().querySelector('.pltrack .g').textContent === 'Hades II', 'card preview lists game + title');
  assert(plCard().querySelector('.plx').disabled === false, 'export offered when tracks exist');
  const exp1 = JSON.parse(S(`JSON.stringify(plExportObj('liked'))`));
  assert(exp1.app === 'scorekeep-playlist' && exp1.name === 'Scorekeep · Liked Songs', 'export carries the playlist name');
  assert(JSON.stringify(exp1.tracks[0]) === JSON.stringify({ game: 'Hades II', title: 'No Escape',
    videoId: 'vidNE', ytmPlaylistId: 'OLAK5uy_plHades', searchQuery: 'Hades II No Escape' }),
    'liked export track: videoId, album context, search fallback');
  const expQ = JSON.parse(S(`JSON.stringify(plExportObj('queue'))`));
  assert(expQ.tracks.length === 7 && expQ.tracks.filter(t => !t.videoId).every(t => t.searchQuery),
    'queue export: unlinked tracks still carry a search query');
  S(`setPlYear('2025')`); await sleep(20);
  assert(cardMeta('liked').startsWith('0 tracks') && cardMeta('queue').startsWith('0 tracks'),
    'year facet empties recipes with no matching releases');
  assert(plCard().querySelector('.plx').disabled === true, 'nothing to export at zero tracks');
  S(`setPlYear('all')`); await sleep(20);
  assert(d.querySelector('#c-plyear').textContent.trim() === 'year ▾', 'playlists year chip reads neutral at all');
  d.querySelector('#c-plgenre').click();
  assert(sheetEl(d) !== null && inSheet(d, '[data-shplgrow="game"]').textContent.includes('game genre · all'),
    'playlists genre chip opens the sheet, one row per medium');
  inSheet(d, '[data-shplgrow="game"]').click(); await sleep(10);
  inSheet(d, '[data-shplg-game="Role-playing (RPG)"]').click(); await sleep(20);
  assert(sheetEl(d) !== null && inSheet(d, '[data-shplgrow="game"]').textContent.includes('game genre · role-playing (rpg)'),
    'picking a playlist genre returns to the rows with the pick named');
  inSheet(d, '#shdone').click(); await sleep(20);
  assert(sheetEl(d) === null, 'done closes the genre sheet');
  assert(cardMeta('queue').startsWith('5 tracks'), 'genre facet keeps only tagged releases');
  assert(plCard().querySelector('.plname').textContent.includes('— Role-playing (RPG)'),
    'facet variants get their own playlist name');
  assert(stored().plGenre.game === 'Role-playing (RPG)', 'facet choice persists per medium');
  assert(d.querySelector('#c-plgenre').textContent.trim() === 'role-playing (rpg) ▾'
    && d.querySelector('#c-plgenre').classList.contains('on'), 'genre chip shows the active facet');
  d.querySelector('#c-plgenre').click();
  inSheet(d, '[data-shplgrow="game"]').click(); await sleep(10);
  inSheet(d, '[data-shplg-game="all"]').click(); await sleep(20);
  inSheet(d, '#shdone').click(); await sleep(20);
  plCard().querySelector('.plx').click();
  assert(errors.length === 0, 'export click stays clean');

  // ---------- one-tap publish ----------
  assert(plCard().querySelector('[data-plp]') === null && d.querySelector('#pubtok') !== null,
    'publish hidden until a token is connected');
  const realFetch = w.fetch;
  d.querySelector('#pubtok').value = '  github_pat_TEST  ';
  d.querySelector('#pubsave').click(); await sleep(20);
  assert(w.localStorage.getItem('vgm-pub-token') === 'github_pat_TEST' && d.querySelector('#pubclear') !== null,
    'connect trims and stores the token outside app state');
  assert(S(`JSON.stringify(buildExport())`).indexOf('github_pat_TEST') === -1,
    'backups never carry the token');
  S(`PUB_POLL_MS = 1`);
  const calls = [];
  w.fetch = async (url, opts) => {
    calls.push({ url: String(url), opts });
    if (String(url).endsWith('/dispatches')) return { ok: false, status: 204, json: async () => ({}) };
    return { ok: true, status: 200, json: async () => ({ workflow_runs: [
      { status: 'completed', conclusion: 'success', created_at: new Date().toISOString() }] }) };
  };
  plCard().querySelector('[data-plp]').click(); await sleep(150);
  const dis = calls.find(c => c.url.endsWith('/dispatches'));
  assert(dis && dis.url.includes('/repos/cjmerc39/vgm-publisher/')
    && dis.opts.method === 'POST' && dis.opts.headers['Authorization'] === 'Bearer github_pat_TEST',
    'publish dispatches to the publisher repo with the token');
  const sent = JSON.parse(dis.opts.body);
  assert(sent.event_type === 'publish' && sent.client_payload.playlist.app === 'scorekeep-playlist'
    && sent.client_payload.playlist.name === 'Scorekeep · Liked Songs'
    && sent.client_payload.playlist.tracks.length === 1, 'dispatch carries the playlist export');
  assert(plCard().querySelector('[data-plp]').textContent.includes('PUBLISHED'),
    'button reports the green run');
  d.querySelector('#list .plcard[data-plc="queue"]').click(); await sleep(20);
  w.fetch = async () => ({ ok: false, status: 401, json: async () => ({}) });
  d.querySelector('#list .plcard[data-plc="queue"] [data-plp]').click(); await sleep(50);
  assert(d.querySelector('#list .plcard[data-plc="queue"] [data-plp]').textContent.includes('token rejected'),
    'a 401 reads as token rejected');
  d.querySelector('#pubclear').click(); await sleep(20);
  assert(w.localStorage.getItem('vgm-pub-token') === null && d.querySelector('#list [data-plp]') === null,
    'disconnect wipes the token and the buttons');
  w.fetch = realFetch;
  assert(errors.length === 0, 'publish flows stay clean');

  // ---------- custom playlists: create, sticky add, change, manage ----------
  assert(d.querySelector('#cplhead') !== null && d.querySelector('#cplnew') !== null
    && d.querySelectorAll('#list .plcard').length === 4, 'library shows the custom section, empty at first');
  d.querySelector('#cplnew').click(); await sleep(20);
  d.querySelector('#cp-name').value = 'Boss Rush';
  d.querySelector('#cp-create').click(); await sleep(20);
  assert(stored().view === 'feed' && stored().cpls.length === 1 && stored().cpls[0].name === 'Boss Rush',
    'create from library: named playlist exists and the app moves to the feed');
  assert(stored().cplLast && stored().cplLast.id === stored().cpls[0].id,
    'the new playlist is armed as the sticky target');
  assert(d.querySelector('#toast').textContent.includes('Boss Rush'), 'a toast points at the new playlist');
  rowById('hades-ii').click(); await sleep(20);
  const tadds = () => [...rowById('hades-ii').querySelectorAll('[data-act="tadd"]')];
  assert(tadds().length === 3, 'expanded feed row offers + on its top tracks');
  tadds()[0].click(); await sleep(20);
  assert(d.querySelector('#sheet') === null && stored().cpls[0].tracks.length === 1,
    'sticky target takes the first save with no picker');
  assert(d.querySelector('#toast').textContent.includes('saved to Boss Rush'), 'snackbar names the playlist');
  tadds()[1].click(); await sleep(20);
  assert(stored().cpls[0].tracks.length === 2, 'the next save also skips the picker');
  tadds()[0].click(); await sleep(20);
  assert(stored().cpls[0].tracks.length === 2 && d.querySelector('#toast').textContent.includes('already in'),
    'a duplicate save is skipped and says so');
  S(`S.cplLast.at -= ${11 * 60000}; save()`);
  tadds()[2].click(); await sleep(20);
  assert(d.querySelector('#sheet [data-cpick]') !== null, 'an expired sticky window reopens the picker');
  d.querySelector('#sheet [data-cpick]').click(); await sleep(20);
  assert(d.querySelector('#sheet') === null && stored().cpls[0].tracks.length === 3,
    'picking from the sheet adds and closes it');
  d.querySelector('#toast-change').click(); await sleep(20);
  assert(d.querySelector('#sheet') !== null, 'the snackbar CHANGE reopens the picker');
  d.querySelector('#cp-name').value = 'Chill VGM';
  d.querySelector('#cp-create').click(); await sleep(20);
  assert(stored().cpls.length === 2 && stored().cpls[0].tracks.length === 2
    && stored().cpls[1].tracks.length === 1, 'change + new playlist MOVES the save');
  const bossId = stored().cpls[0].id, chillId = stored().cpls[1].id;
  tab('library').click(); await sleep(20);
  assert(d.querySelectorAll('#list .plcard').length === 6, 'custom cards join the recipe cards');
  d.querySelector(`#list .plcard[data-plc="c:${chillId}"]`).click(); await sleep(20);
  const chillCard = () => d.querySelector(`#list .plcard[data-plc="c:${chillId}"]`);
  assert(chillCard().querySelector('.plmeta').textContent.startsWith('1 track ')
    && chillCard().querySelector('[data-plx]').disabled === false, 'custom card previews and can export');
  const cexp = JSON.parse(S(`JSON.stringify(plExportObj('c:${chillId}'))`));
  assert(cexp.name === 'Chill VGM' && cexp.tracks.length === 1 && cexp.tracks[0].videoId === 'vidCC'
    && cexp.tracks[0].game === 'Hades II', 'custom export resolves videoIds through the catalog');
  d.querySelector(`#list .plcard[data-plc="c:${bossId}"]`).click(); await sleep(20);
  d.querySelector(`#list .plcard[data-plc="c:${bossId}"] .cprm`).click(); await sleep(20);
  assert(stored().cpls[0].tracks.length === 1, 'the ✕ removes one track');
  d.querySelector(`[data-cpldel="${bossId}"]`).click(); await sleep(20);
  assert(stored().cpls.length === 2 && d.querySelector(`[data-cpldel="${bossId}"]`).textContent.includes('SURE'),
    'delete arms first instead of firing');
  d.querySelector(`[data-cpldel="${bossId}"]`).click(); await sleep(20);
  assert(stored().cpls.length === 1 && stored().cpls[0].id === chillId, 'the second tap deletes');
  const vs = JSON.parse(S(`JSON.stringify(validateState({v:2, entries:{},
    cpls:[{id:'a', name:'  X  ', at:'bad', tracks:[{id:'r', t:'T'}, {id:'r', t:'t'}, 'junk', {id:'', t:'y'}]},
          {id:'a', name:'dupe'}, {name:'noid'}, null],
    cplLast:{id:'a', at:5}}))`));
  assert(vs.cpls.length === 1 && vs.cpls[0].name === 'X' && vs.cpls[0].at === 0
    && vs.cpls[0].tracks.length === 1 && vs.cplLast && vs.cplLast.at === 5,
    'import sanitizes custom playlists: folded dupes, junk, and orphan cplLast handled');
  assert(errors.length === 0, 'custom playlist flows stay clean');
  S(`editEntry('hades-ii', e => { e.status = 'unsorted'; e.queuedOn = null; })`);
  S(`editEntry('ゼルダの伝説', e => { e.status = 'unsorted'; e.queuedOn = null; })`);
  d.querySelector('#libpl').click(); await sleep(20);
  assert(stored().libView === 'albums', 'tapping the active chip returns to albums');

  // ---------- hidden: reachable, reversible ----------
  tab('feed').click(); await sleep(20);
  rowById('ゼルダの伝説').querySelector('[data-act="hide"]').click(); await sleep(20);
  assert(rowById('ゼルダの伝説') === null, 'hide removes the row from the feed');
  d.querySelector('#hidtoggle').click(); await sleep(20);
  assert(d.querySelector('#hidhead').textContent.includes('2'), 'hidden section counts both hidden rows');
  d.querySelector('.row.ghost[data-id="ゼルダの伝説"] [data-act="restore"]').click(); await sleep(20);
  assert(rowById('ゼルダの伝説') !== null, 'restore brings the row back');

  // ---------- search still works, now note-aware ----------
  const q = d.getElementById('q');
  const type = (s) => { q.value = s; q.dispatchEvent(new w.Event('input', { bubbles: true })); };
  type('mitsuda');
  assert(rows().length === 1 && rows()[0].dataset.id === 'chrono-cross-the-radical-dreamers-edition', 'search matches composers');
  type('hadés');
  assert(rows().length === 1 && rows()[0].dataset.id === 'hades-ii', 'search folds diacritics (pokemon finds Pokémon)');
  type('radical dreamers edition ost');
  assert(rows().length === 1, 'original headline text stays searchable behind the album label');
  type('slaps');
  assert(rows().length === 1 && rows()[0].dataset.id === 'ratchet-clank-rift-apart', 'search matches your notes');
  assert(d.getElementById('qwrap').classList.contains('has'), 'clear button appears while text is present');
  d.getElementById('qclear').click(); await sleep(20);
  assert(d.getElementById('q').value === '' && !d.getElementById('qwrap').classList.contains('has')
    && rows().length === 5, 'clear button empties the search and restores the list');
  type('');

  // ---------- export / import round-trip ----------
  const dump = S('JSON.stringify(buildExport())');
  const parsedDump = JSON.parse(dump);
  assert(parsedDump.app === 'scorekeep' && parsedDump.state.v === 3, 'export wraps the current state');
  S(`editEntry('ratchet-clank-rift-apart', e => { e.note = 'clobbered'; e.rating = 1; })`);
  assert(S(`applyImport(${JSON.stringify(dump)})`) === true, 'import accepts its own export');
  const oldDump = dump.replace('"app":"scorekeep"', '"app":"vgm-finder"');
  assert(oldDump !== dump && S(`applyImport(${JSON.stringify(oldDump)})`) === true,
    'a backup made before the rename still imports');
  assert(stored().entries['ratchet-clank-rift-apart'].note.includes('slaps') &&
         stored().entries['ratchet-clank-rift-apart'].rating === 3.5, 'import restores the exported state');
  assert(S(`applyImport('{"nope":true}')`) === false, 'import rejects foreign JSON');
  assert(S(`applyImport('not json')`) === false, 'import rejects non-JSON');
  const legacy = JSON.stringify({ v: 1, starred: { 'hades-ii': true }, listened: {}, hidden: {}, lastSeen: 5 });
  assert(S(`applyImport(${JSON.stringify(legacy)})`) === true && stored().v === 3 &&
         stored().entries['hades-ii'].liked === true, 'importing a v1 backup migrates it');
  assert(S(`applyImport(${JSON.stringify(dump)})`) === true, 'state restored for the reload test');

  // ---------- persistence across reload ----------
  const raw = w.localStorage.getItem('vgm-v1');
  const re = makeDom(okFetch(FIXTURE), raw);
  await sleep(120);
  assert(re.errors.length === 0, 'reload boots clean on v2 state');
  const rtab = (v) => re.d.querySelector(`#tabbar button[data-v="${v}"]`);
  assert(rtab('library').textContent.includes('2') && rtab('queue').textContent.includes('0'),
    'counts survive a reload');
  assert(JSON.parse(re.w.localStorage.getItem('vgm-v1')).entries['ratchet-clank-rift-apart'].rating === 3.5,
    'diary content identical after reload');

  // ---------- fresh visitor, empty and error states ----------
  const first = makeDom(okFetch(FIXTURE));
  await sleep(60);
  assert(first.d.querySelectorAll('#list .new').length === 0, 'first-ever visit badges nothing as NEW');
  first.d.querySelector('#tabbar button[data-v="queue"]').click();
  assert(first.d.querySelector('#list .state').textContent.includes('QUEUE EMPTY'), 'empty queue explains itself');
  first.d.querySelector('#tabbar button[data-v="library"]').click();
  assert(first.d.querySelector('#list .state').textContent.includes('NOTHING LOGGED'), 'empty library points at the ritual');

  const broken = makeDom(async () => ({ ok: false, status: 404, json: async () => ({}) }));
  await sleep(60);
  assert(broken.d.querySelector('#list .state').textContent.includes('HTTP 404'), 'fetch failure states the status');

  // ---------- installed-app (standalone) navigation ----------
  const alone = makeDom(okFetch(FIXTURE), null, true);
  await sleep(120);
  alone.w.eval('navTo = u => { window.__nav = u; }');
  alone.w.eval("openTrack(byId('hades-ii'))");
  assert(alone.w.__nav === 'https://music.youtube.com/playlist?list=OLAK5uy_hades2'
    && alone.w.__opened === undefined,
    'standalone mode navigates directly so the universal link takes over — no leftover sheet');

  // ================= Phase A: split tracklists, mediums, paging =================

  // ---------- lazy tracklists from data/tracks/<id>.json ----------
  const SA_TRACKS = [
    { title: 'Alpha', plays: '2M plays', videoId: 'vidA' },
    { title: 'Beta', plays: '200K plays', videoId: 'vidB' },
    { title: 'Gamma', plays: null, videoId: null },
  ];
  const SB_TRACKS = [{ title: 'Delta', plays: null, videoId: 'vidD' }];
  const SPLIT_FIX = {
    updatedAt: '2026-09-01T10:00:00Z',
    releases: [
      { id: 'split-a', title: 'Split A Soundtrack', medium: 'game', game: 'Split A',
        composers: ['Comp A'], date: '2026-08-01', tracksN: 3, playsTotal: 2200000,
        ytmPlaylistId: 'OLAK5uy_sa', genres: ['Platform'], console: true, company: 'Nintendo',
        sources: [{ name: 'igdb', type: 'catalog', url: 'https://x/a', seenAt: '2026-08-01T10:00:00Z' }],
        ytmSearchUrl: 'https://music.youtube.com/search?q=Split+A', notable: true,
        ytmAlbumUrl: 'https://music.youtube.com/browse/MPREb_sa', art: null },
      { id: 'split-b', title: 'Split B Soundtrack', medium: 'game', game: 'Split B',
        composers: [], date: '2026-07-20', tracksN: 1,
        sources: [{ name: 'steam', type: 'catalog', url: 'https://x/b', seenAt: '2026-07-20T10:00:00Z' }],
        ytmSearchUrl: 'https://music.youtube.com/search?q=Split+B', notable: true,
        ytmAlbumUrl: null, art: null },
      { id: 'split-miss', title: 'Split Miss Soundtrack', medium: 'game', game: 'Split Miss',
        composers: [], date: '2026-07-10', tracksN: 2,
        sources: [{ name: 'steam', type: 'catalog', url: 'https://x/m', seenAt: '2026-07-10T10:00:00Z' }],
        ytmSearchUrl: 'https://music.youtube.com/search?q=Split+Miss', notable: true,
        ytmAlbumUrl: null, art: null },
      { id: 'split-empty', title: 'Split Empty Soundtrack', medium: 'game', game: 'Split Empty',
        composers: [], date: '2026-07-05', tracksN: 0,
        sources: [{ name: 'steam', type: 'catalog', url: 'https://x/e', seenAt: '2026-07-05T10:00:00Z' }],
        ytmSearchUrl: 'https://music.youtube.com/search?q=Split+Empty', notable: true,
        ytmAlbumUrl: null, art: null },
      { id: 'split-c', title: 'Split C Soundtrack', medium: 'game', game: 'Split C',
        composers: [], date: '2026-06-20', tracksN: 1,
        sources: [{ name: 'steam', type: 'catalog', url: 'https://x/c', seenAt: '2026-06-20T10:00:00Z' }],
        ytmSearchUrl: 'https://music.youtube.com/search?q=Split+C', notable: true,
        ytmAlbumUrl: null, art: null },
      { id: 'film-split-film', title: 'Split Film Soundtrack', medium: 'film', game: 'Split Film',
        composers: ['Comp F'], date: '2026-07-15', playsTotal: 500000, genres: ['Science Fiction'],
        sources: [{ name: 'tmdb', type: 'catalog', url: 'https://x/f', seenAt: '2026-07-15T10:00:00Z' }],
        ytmSearchUrl: 'https://music.youtube.com/search?q=Split+Film', notable: true,
        ytmAlbumUrl: null, art: null },
      { id: 'tv-split-show', title: 'Split Show Soundtrack', medium: 'tv', game: 'Split Show',
        composers: ['Comp T'], date: '2026-07-01', genres: ['Drama'],
        sources: [{ name: 'tmdb', type: 'catalog', url: 'https://x/t', seenAt: '2026-07-01T10:00:00Z' }],
        ytmSearchUrl: 'https://music.youtube.com/search?q=Split+Show', notable: true,
        ytmAlbumUrl: null, art: null },
    ],
  };
  const SC_TRACKS = [{ title: 'Epsilon', plays: null, videoId: 'vidE' }];
  const hits = {};
  const routedFetch = async (url) => {
    hits[url] = (hits[url] || 0) + 1;
    if (url === 'data/releases.json') return { ok: true, status: 200, json: async () => SPLIT_FIX };
    if (url === 'data/tracks/split-a.json') return { ok: true, status: 200, json: async () => SA_TRACKS };
    if (url === 'data/tracks/split-b.json') return { ok: true, status: 200, json: async () => SB_TRACKS };
    if (url === 'data/tracks/split-c.json') {  // slow on purpose: the concurrent-await test races it
      await sleep(60);
      return { ok: true, status: 200, json: async () => SC_TRACKS };
    }
    return { ok: false, status: 404, json: async () => ({}) };
  };
  const sp = makeDom(routedFetch, { v: 2, entries: {
    'split-a': { status: 'listened', listenedOn: '2026-08-02', likedTracks: ['Alpha'] },
    'split-b': { likedTracks: ['Delta'] },
    'split-miss': { likedTracks: ['Ghost Song'] },
    'film-split-film': { status: 'listened', listenedOn: '2026-08-03' },
  }, lastSeen: T('2026-08-20T00:00:00Z') });
  await sleep(120);
  const sq = (sel) => sp.d.querySelector(sel);
  const sRows = () => [...sp.d.querySelectorAll('#list .row:not(.ghost)')];
  const sRow = (id) => sp.d.querySelector(`#list .row[data-id="${id}"]`);
  const sStored = () => JSON.parse(sp.w.localStorage.getItem('vgm-v1'));
  assert(sp.errors.length === 0, 'split-shape data boots clean on old v2 state');
  assert(sStored().v === 3 && sStored().feedMedium === 'all', 'v2 state upgraded in place, mediums default to all');
  assert(sStored().feedGenre.game === 'all' && sStored().feedGenre.screen === 'all', 'old single-value genre state migrates to buckets');
  assert(hits['data/tracks/split-a.json'] === undefined, 'boot fetches no tracklist files');

  sRow('split-a').click();
  await sleep(120);
  assert(hits['data/tracks/split-a.json'] === 1, 'expanding a row fetches its tracks file');
  const sx = sRow('split-a').querySelector('.rx');
  assert(sx.textContent.includes('TOP TRACKS') && sx.textContent.includes('Alpha')
    && sx.textContent.includes('All 3 tracks'), 'expanded panel renders the lazy-loaded tracklist');
  sRow('split-a').click();
  sRow('split-a').click();
  await sleep(80);
  assert(hits['data/tracks/split-a.json'] === 1, 're-expanding reuses the session cache, no refetch');

  sRow('split-a').querySelector('[data-act="album"]').click();
  await sleep(40);
  assert(sp.d.querySelectorAll('#album .atrack').length === 3, 'album page lists the loaded tracks');
  sq('#album .aclose').click();

  sRow('split-miss').click();
  await sleep(120);
  assert(sRow('split-miss').querySelector('.rx') !== null
    && sRow('split-miss').querySelectorAll('.xtrack').length === 0
    && sRow('split-miss').querySelector('[data-act="listen"]') !== null,
    'a missing tracks file degrades to the listen link, not an error');
  assert(sp.errors.length === 0, 'the 404 tracklist raises no runtime errors');
  sRow('split-miss').click();
  sRow('split-miss').click();
  await sleep(120);
  assert(hits['data/tracks/split-miss.json'] === 2, 'a failed tracklist fetch retries on the next tap');
  sRow('split-miss').click();

  // ---------- concurrent callers share one in-flight fetch ----------
  const raced = await sp.w.eval(
    `Promise.all([loadTracks(['split-c']), loadTracks(['split-c'])]).then(() => TRACKS['split-c'].map(t => t.title))`);
  assert(JSON.stringify([...raced]) === '["Epsilon"]' && hits['data/tracks/split-c.json'] === 1,
    'a second caller awaits the in-flight fetch instead of skipping it');

  // ---------- liked songs load only the ids they reference ----------
  sp.d.querySelector('#tabbar button[data-v="library"]').click();
  sq('#libsongs').click();
  await sleep(120);
  assert(hits['data/tracks/split-b.json'] === 1, 'liked songs fetch a referenced tracklist');
  assert(hits['data/tracks/film-split-film.json'] === undefined
    && hits['data/tracks/tv-split-show.json'] === undefined,
    'liked songs never fetch unreferenced tracklists');
  const songRows = [...sp.d.querySelectorAll('#list .row.song')];
  assert(songRows.length === 3, 'liked songs render, including the one with a lost file');
  sp.w.__opened = null;
  songRows.find(x => x.dataset.t === 'Alpha').click();
  assert(sp.w.__opened === 'https://music.youtube.com/watch?v=vidA&list=OLAK5uy_sa',
    'a loaded liked song plays with album context');
  sp.w.__opened = null;
  songRows.find(x => x.dataset.t === 'Ghost Song').click();
  assert(String(sp.w.__opened).startsWith('https://music.youtube.com/search?q='),
    'a liked song without its file falls back to search');

  // ---------- medium lives in the filters sheet ----------
  sq('#libsongs').click();
  await sleep(20);
  assert(sp.d.querySelectorAll('#subctl button').length === 4 && sq('#c-libfilters') !== null
    && sq('#libliked') === null,
    'library row stays four chips: sort, filters, and the two mode chips');

  sp.d.querySelector('#tabbar button[data-v="feed"]').click();
  await sleep(20);
  sq('#c-filters').click();
  assert(sp.d.querySelectorAll('#sheetwrap [data-shmed]').length === 3,
    'the medium segment leads the filters sheet once film data exists');
  assert(inSheet(sp.d, '[data-shco]') === null && inSheet(sp.d, '[data-shgenre]') === null,
    'under all, the sheet is just the segment and the footer');
  inSheet(sp.d, '[data-shmed="screen"]').click();
  await sleep(20);
  assert(sRows().length === 2 && sRows().every(x => x.dataset.id.match(/^(film|tv)-/)),
    'film + tv shows both screen mediums');
  assert(sq('#c-filters').textContent === 'filters · film + tv', 'the chip names the screen medium');
  assert(sp.d.querySelectorAll('#sheetwrap [data-shsub]').length === 3,
    'the both/film/tv sub-segment appears under film + tv');
  inSheet(sp.d, '[data-shsub="film"]').click();
  await sleep(20);
  assert(sRows().length === 1 && sRows()[0].dataset.id === 'film-split-film', 'film narrows to film rows');
  assert(JSON.parse(sp.w.localStorage.getItem('vgm-v1')).feedMedium === 'film', 'medium persists');
  assert(sq('#c-filters').textContent === 'filters · film', 'the chip names the medium');
  assert(inSheet(sp.d, '[data-shco]') === null && sq('#sheetwrap #shconsole') === null,
    'scope and console never render outside games');
  sp.w.eval("S.feedCo = 'indie'; renderAll()");
  assert(sq('#c-filters').textContent === 'filters · film',
    'an inert stored scope never reads out on the chip');
  assert(sRows().length === 1, 'an inert stored scope filters nothing');
  inSheet(sp.d, '#shgenrerow').click(); await sleep(10);
  const gRows = [...sp.d.querySelectorAll('#sheetwrap [data-shgenre]')].map(b => b.dataset.shgenre);
  assert(gRows.includes('Science Fiction') && !gRows.includes('Platform'),
    'genre list scopes to the screen selection');
  inSheet(sp.d, '[data-shgenre="Science Fiction"]').click();
  await sleep(20);
  assert(sq('#c-filters').textContent === 'filters · film, science fiction',
    'the chip reads medium then genre');
  inSheet(sp.d, '#shdone').click();
  assert(sRows()[0].querySelector('.rsub').textContent === 'Split Film · Comp F',
    'film subtitle reads film title and composers');
  sRows()[0].click();
  assert([...sRows()[0].querySelectorAll('.xk')].some(k => k.textContent === 'film'),
    'expanded info labels the work by its medium');
  sRows()[0].click();
  sp.w.eval("openAlbum('film-split-film')");
  assert(sq('#album .ameta').textContent.includes('film score'), 'album header names the medium');
  sq('#album .aclose').click();
  sq('#c-filters').click();
  inSheet(sp.d, '[data-shmed="game"]').click();
  await sleep(20);
  assert(sRows().length === 0, 'the stored indie scope wakes up with the games medium');
  assert(sq('#c-filters').textContent === 'filters · games, indie',
    'the chip reads medium then scope again');
  assert(inSheet(sp.d, '[data-shco="indie"]').classList.contains('on')
    && sq('#sheetwrap #shconsole') !== null && inSheet(sp.d, '[data-shsub]') === null,
    'games mode shows scope and console, never the sub-segment');
  inSheet(sp.d, '#shgenrerow').click(); await sleep(10);
  const gameGenres = [...sp.d.querySelectorAll('#sheetwrap [data-shgenre]')].map(b => b.dataset.shgenre);
  assert(gameGenres.includes('Platform') && !gameGenres.includes('Science Fiction'),
    'the game genre list never carries screen genres');
  inSheet(sp.d, '#shback').click(); await sleep(10);
  assert(JSON.parse(sp.w.localStorage.getItem('vgm-v1')).feedGenre.screen === 'Science Fiction',
    'the screen genre pick survives, stored in its own bucket');
  inSheet(sp.d, '#shclear').click();
  await sleep(20);
  assert(sheetEl(sp.d) !== null, 'clear keeps the sheet open');
  const cleared = JSON.parse(sp.w.localStorage.getItem('vgm-v1'));
  assert(cleared.feedMedium === 'all' && cleared.feedCo === 'all'
    && cleared.feedGenre.game === 'all' && cleared.feedGenre.screen === 'all',
    'clear resets medium, scope, and both genre buckets');
  assert(sRows().length === 7 && sq('#c-filters').textContent === 'filters',
    'cleared feed shows everything and the chip reads neutral');
  inSheet(sp.d, '#shdone').click();

  // both unions the genre vocabularies; the sub-selections keep them apart
  sq('#c-filters').click();
  inSheet(sp.d, '[data-shmed="screen"]').click();
  await sleep(20);
  inSheet(sp.d, '#shgenrerow').click(); await sleep(10);
  const unionG = [...sp.d.querySelectorAll('#sheetwrap [data-shgenre]')].map(b => b.dataset.shgenre);
  assert(unionG.includes('Science Fiction') && unionG.includes('Drama') && !unionG.includes('Platform'),
    'both lists the union of film and tv genres, never game ones');
  inSheet(sp.d, '#shback').click(); await sleep(10);
  inSheet(sp.d, '[data-shsub="film"]').click();
  await sleep(20);
  inSheet(sp.d, '[data-shmed="screen"]').click();
  await sleep(20);
  assert(JSON.parse(sp.w.localStorage.getItem('vgm-v1')).feedMedium === 'film',
    'tapping the already-on film + tv segment keeps the sub-selection');
  inSheet(sp.d, '#scrim').click();
  sp.w.eval("clearFeedFilters()");
  await sleep(20);

  // a v3 backup with a single-value genre imports and migrates
  const spKeep = sp.w.localStorage.getItem('vgm-v1');
  assert(sp.w.eval(`applyImport(JSON.stringify({ v: 3, entries: {}, feedGenre: 'Platform', feedMedium: 'film' }))`) === true,
    'a v3 backup still imports');
  const mig = JSON.parse(sp.w.localStorage.getItem('vgm-v1'));
  assert(mig.v === 3 && mig.feedGenre.screen === 'Platform' && mig.feedGenre.game === 'all'
    && mig.feedMedium === 'film',
    'a legacy genre saved under a screen medium migrates into the screen bucket');
  assert(sp.w.eval(`applyImport(JSON.stringify({ v: 3, entries: {}, feedGenre: 'Platform', feedMedium: 'game' }))`) === true
    && JSON.parse(sp.w.localStorage.getItem('vgm-v1')).feedGenre.game === 'Platform',
    'a legacy genre saved under games migrates into the game bucket');
  assert(sp.w.eval(`applyImport(JSON.stringify({ v: 3, entries: {}, plGenre: 'Drama' }))`) === true
    && JSON.parse(sp.w.localStorage.getItem('vgm-v1')).plGenre.screen === 'Drama',
    'the merged playlists genre reaches the bucket that can actually match it');
  assert(sp.w.eval(`applyImport(${JSON.stringify(spKeep)})`) === true, 'prior state restored after the import test');
  sp.w.eval("clearFeedFilters()");
  await sleep(20);

  // random under film + tv never returns a game row
  sp.w.eval("setFeedMedium('screen')");
  sp.w.eval('Math.random = () => 0.999');
  sp.d.querySelector('#hrandom').click();
  await sleep(50);
  const expanded = sp.d.querySelector('#list .row[aria-expanded="true"]');
  assert(expanded && /^(film|tv)-/.test(expanded.dataset.id),
    'random under film + tv never returns a game row');
  expanded.click();
  sp.w.eval("setFeedMedium('all')");
  await sleep(20);

  // library filters chip drives libMedium with the same sheet
  sp.d.querySelector('#tabbar button[data-v="library"]').click();
  await sleep(20);
  assert(sq('#c-libfilters') !== null && sq('#c-libfilters').textContent === 'filters',
    'the library albums row gains its own filters chip');
  sq('#c-libfilters').click();
  inSheet(sp.d, '[data-shlmed="screen"]').click();
  await sleep(20);
  assert(sRows().length === 1 && sRows()[0].dataset.id === 'film-split-film',
    'library film + tv narrows to logged screen rows');
  assert(sq('#c-libfilters').textContent === 'filters · film + tv', 'the library chip names the medium');
  inSheet(sp.d, '[data-shlsub="tv"]').click();
  await sleep(20);
  assert(sRows().length === 0, 'library tv narrows further; nothing logged there yet');
  inSheet(sp.d, '#shliked').click();
  await sleep(20);
  assert(JSON.parse(sp.w.localStorage.getItem('vgm-v1')).libLiked === true
    && sq('#c-libfilters').textContent === 'filters · tv, liked',
    'the liked toggle lives in the sheet and reads out on the chip');
  inSheet(sp.d, '#shclear').click();
  await sleep(20);
  const lcl = JSON.parse(sp.w.localStorage.getItem('vgm-v1'));
  assert(lcl.libMedium === 'all' && lcl.libLiked === false && sheetEl(sp.d) !== null,
    'library clear resets medium and liked, and stays open');
  inSheet(sp.d, '#shdone').click();

  // the medium filter follows into the liked-songs view
  sp.w.eval("setLibMedium('game')");
  sq('#libsongs').click();
  await sleep(60);
  assert(sq('#c-libfilters').textContent === 'filters · games', 'songs view keeps the medium chip');
  const songIds = [...sp.d.querySelectorAll('#list .row.song')].map(x => x.dataset.id);
  assert(songIds.length && songIds.every(id => !/^(film|tv)-/.test(id)),
    'liked songs obey the library medium filter');
  sq('#c-libfilters').click();
  assert(inSheet(sp.d, '#shliked') === null, 'the liked toggle is omitted where every row is already liked');
  inSheet(sp.d, '#shclear').click();
  await sleep(20);
  inSheet(sp.d, '#shdone').click();
  sq('#libsongs').click();
  await sleep(20);
  sq('#libpl').click();
  await sleep(20);
  sq('#c-plgenre').click();
  assert(inSheet(sp.d, '[data-shplgrow="game"]') !== null && inSheet(sp.d, '[data-shplgrow="screen"]') !== null,
    'the playlists genre sheet offers both medium groups');
  inSheet(sp.d, '[data-shplgrow="screen"]').click(); await sleep(10);
  inSheet(sp.d, '[data-shplg-screen="Science Fiction"]').click();
  await sleep(20);
  inSheet(sp.d, '#shdone').click(); await sleep(10);
  assert(JSON.parse(sp.w.localStorage.getItem('vgm-v1')).plGenre.screen === 'Science Fiction'
    && sq('#c-plgenre').textContent.trim() === 'science fiction ▾',
    'a screen genre facet lands in its own bucket and on the chip');
  sq('#c-plgenre').click();
  inSheet(sp.d, '[data-shplgrow="screen"]').click(); await sleep(10);
  inSheet(sp.d, '[data-shplg-screen="all"]').click();
  await sleep(20);
  inSheet(sp.d, '#shdone').click(); await sleep(10);
  sq('#libpl').click();
  await sleep(20);
  sp.d.querySelector('#tabbar button[data-v="feed"]').click();
  await sleep(20);

  // ---------- most played sort ----------
  sq('#c-sort').click();
  inSheet(sp.d, '[data-shsort="plays"]').click();
  await sleep(20);
  const order = sRows().map(x => x.dataset.id);
  assert(order[0] === 'split-a' && order[1] === 'film-split-film',
    'most played ranks by playsTotal without loading tracklists');
  assert(order.length === 7 && order.slice(2).every(id => !SPLIT_FIX.releases.find(r => r.id === id).playsTotal),
    'rows without playsTotal sink to the bottom');
  assert(hits['data/tracks/split-empty.json'] === undefined, 'sorting fetches nothing');

  // ---------- paging, year jump, back to top ----------
  const bigRows = [];
  for (let i = 0; i < 150; i++) {
    const year = 2026 - Math.floor(i / 20);
    bigRows.push({
      id: `big-${i}`, title: `Big ${i} Soundtrack`, medium: 'game', game: `Big ${i}`,
      composers: [], date: `${year}-${String(12 - (i % 12)).padStart(2, '0')}-15`,
      sources: [{ name: 'steam', type: 'catalog', url: `https://x/${i}`, seenAt: '2026-07-01T00:00:00Z' }],
      ytmSearchUrl: `https://music.youtube.com/search?q=Big+${i}`, ytmAlbumUrl: null,
      art: null, notable: true,
    });
  }
  const bg = makeDom(okFetch({ updatedAt: '2026-09-01T10:00:00Z', releases: bigRows }));
  await sleep(150);
  const bRows = () => [...bg.d.querySelectorAll('#list .row:not(.ghost)')];
  assert(bg.errors.length === 0, 'a 150-row catalog boots clean');
  assert(bRows().length === 60, 'the feed renders one page of 60 rows');
  const more = () => bg.d.querySelector('#more');
  assert(more() !== null && more().textContent.includes('90'), 'the MORE sentinel counts what is left');
  const keepEl = bRows()[0];
  more().click();
  assert(bRows().length === 120 && bRows()[0] === keepEl,
    'MORE appends the next page without rebuilding the shown rows');
  more().click();
  assert(bRows().length === 150 && more() === null, 'the last page retires the sentinel');

  bRows()[0].click();
  assert(bRows().length === 150 && bRows()[0].getAttribute('aria-expanded') === 'true',
    'expanding a row never resets paging');
  bRows()[0].click();

  bg.d.querySelector('#q').value = 'Big 1';
  bg.d.querySelector('#q').dispatchEvent(new bg.w.Event('input', { bubbles: true }));
  await sleep(20);
  assert(bRows().length === 60 && more() !== null && more().textContent.includes('1'),
    'search results page from the top');
  bg.d.querySelector('#qclear').click();
  await sleep(20);
  assert(bRows().length === 60, 'clearing search starts back at page one');

  bRows()[0].querySelector('[data-act="hide"]').click();
  await sleep(20);
  bg.d.querySelector('#hidtoggle').click();
  await sleep(20);
  assert(bg.d.querySelector('#hidhead') !== null && more() !== null,
    'the hidden shelf renders even while pages remain');
  assert(bRows().length === 60, 'revealing hidden rows never resets paging');
  bg.d.querySelector('#list .row.ghost [data-act="restore"]').click();
  await sleep(20);
  bg.w.eval('if(S.showHidden) toggleShowHidden()');
  await sleep(20);

  bg.d.querySelector('#c-year').click();
  const yRows = [...bg.d.querySelectorAll('#sheetwrap [data-shyear]')];
  assert(yRows.length === 8 && yRows[0].dataset.shyear === '2026'
    && yRows[0].querySelector('.shr').textContent === '20',
    'year sheet lists the years newest first with counts');
  inSheet(bg.d, '[data-shyear="2020"]').click();
  await sleep(20);
  assert(sheetEl(bg.d) === null, 'picking a year closes the sheet');
  assert([...bg.d.querySelectorAll('#list .yhead')].some(h => h.textContent === '2020'),
    'year jump pages in far years and lands on the header');

  const bMain = bg.d.querySelector('main');
  const toTop = bg.d.querySelector('#totop');
  assert(toTop.hidden === true, 'back-to-top hides at the top of the list');
  bMain.scrollTop = 900;
  bMain.dispatchEvent(new bg.w.Event('scroll'));
  assert(toTop.hidden === false, 'back-to-top appears after a screen of scroll');
  bg.w.eval('document.querySelector("main").scrollTo = function(o){ this.scrollTop = o.top; }');
  toTop.click();
  bMain.dispatchEvent(new bg.w.Event('scroll'));
  assert(bMain.scrollTop === 0 && toTop.hidden === true, 'back-to-top returns to the top and tucks away');
  bg.d.querySelector('#c-filters').click();
  assert(bg.d.querySelector('#sheetwrap [data-shmed]') === null,
    'medium segment stays out of the way while the catalog is games only');
  inSheet(bg.d, '#scrim').click();
  assert(sheetEl(bg.d) === null, 'the scrim closes the sheet');

  // ---------- addendum invariants: three chips, dismissals, random ----------
  for(const change of [`setFeedSort('plays')`, `setFeedCo('indie')`, `toggleFeedConsole()`,
                       `setFeedSort('date')`, `clearFeedFilters()`]){
    bg.w.eval(change);
    assert(bg.d.querySelectorAll('#subctl button').length === 3,
      'feed row stays exactly three chips after ' + change);
  }
  assert(bg.d.querySelector('#c-filters').classList.contains('fchip'),
    'filters chip carries the truncation hook');

  bg.d.querySelector('#c-sort').click();
  const swSheet = sheetEl(bg.d);
  const ts = new bg.w.Event('touchstart', { bubbles: true });
  ts.touches = [{ clientY: 100 }];
  swSheet.dispatchEvent(ts);
  const te = new bg.w.Event('touchend', { bubbles: true });
  te.changedTouches = [{ clientY: 220 }];
  swSheet.dispatchEvent(te);
  assert(sheetEl(bg.d) === null, 'swipe down dismisses the sheet');

  bg.d.querySelector('#c-sort').click();
  bg.w.dispatchEvent(new bg.w.KeyboardEvent('keydown', { key: 'Escape' }));
  assert(sheetEl(bg.d) === null, 'escape closes the control sheet');

  bg.d.querySelector('#q').value = 'Big 149';
  bg.d.querySelector('#q').dispatchEvent(new bg.w.Event('input', { bubbles: true }));
  await sleep(20);
  bg.w.eval('Math.random = () => 0');
  bg.w.__opened = null;
  bg.d.querySelector('#hrandom').click();
  assert(bg.d.querySelector('#list .row[data-id="big-149"]').getAttribute('aria-expanded') === 'true',
    'header random respects the current filters');
  bg.d.querySelector('#qclear').click(); await sleep(20);

  bg.d.querySelector('#tabbar button[data-v="library"]').click(); await sleep(20);
  bg.d.querySelector('#hrandom').click(); await sleep(20);
  assert(JSON.parse(bg.w.localStorage.getItem('vgm-v1')).view === 'feed',
    'header random hops back to the feed first');

  bg.w.eval(`setFeedSort('az')`);
  bg.d.querySelector('#c-year').click();
  inSheet(bg.d, '[data-shyear="2019"]').click(); await sleep(20);
  assert(bg.d.querySelector('#list .row[data-id="big-140"]') !== null,
    'a year pick under a flat sort still pages in that year');
  bg.w.eval(`setFeedSort('date')`);

  // ---------- retired rows (MATCHER-FIX-SPEC Phase 2 orphans) ----------
  const retiredRow = (id, medium, title, date, genre, extra) => Object.assign({
    id, title, medium, game: title.replace(' Soundtrack', ''), composers: [], date, genres: [genre],
    sources: [{ name: 'tmdb-' + medium, type: 'catalog', url: 'https://x/' + id, seenAt: '2026-09-01T00:00:00Z' }],
    ytmSearchUrl: 'https://music.youtube.com/search?q=' + id,
    ytmAlbumUrl: 'https://music.youtube.com/browse/' + id, art: null, notable: true }, extra || {});
  const RET = { updatedAt: '2026-09-13T10:00:00Z', releases: [
    retiredRow('film-live', 'film', 'Live Soundtrack', '2020-01-01', 'Drama'),
    retiredRow('tv-gone-season-2', 'tv', 'Gone Season 2 Soundtrack', '2018-01-01', 'Mystery', { retired: true }),
    retiredRow('tv-quiet', 'tv', 'Quiet Soundtrack', '2015-01-01', 'Western', { retired: true }),
  ] };
  const rt = makeDom(okFetch(RET),
    { v: 3, entries: { 'tv-gone-season-2': { status: 'listened', listenedOn: '2026-08-01' } } });
  await sleep(120);
  const rtRows = () => [...rt.d.querySelectorAll('#list .row:not(.ghost)')].map(x => x.dataset.id);
  assert(rt.errors.length === 0, 'a catalog with retired rows boots clean');
  assert(JSON.stringify(rtRows()) === JSON.stringify(['film-live']), 'retired rows leave the feed');
  assert(rt.d.querySelector('#colophon').textContent.includes('1 soundtracks'),
    'the colophon counts only live rows');
  rt.d.querySelector('#q').value = 'Gone';
  rt.d.querySelector('#q').dispatchEvent(new rt.w.Event('input', { bubbles: true }));
  await sleep(20);
  assert(rtRows().length === 0, 'search never surfaces a retired row');
  rt.d.querySelector('#qclear').click(); await sleep(20);
  rt.d.querySelector('#c-filters').click();
  rt.d.querySelector('#sheetwrap [data-shmed="screen"]').click(); await sleep(20);
  rt.d.querySelector('#sheetwrap #shgenrerow').click(); await sleep(10);
  const rtGenres = [...rt.d.querySelectorAll('#sheetwrap [data-shgenre]')].map(b => b.dataset.shgenre);
  assert(rtGenres.includes('Drama') && !rtGenres.includes('Mystery') && !rtGenres.includes('Western'),
    'retired rows add nothing to the genre lists');
  rt.d.querySelector('#sheetwrap #shback').click(); await sleep(10);
  rt.d.querySelector('#sheetwrap #shdone').click();
  rt.w.eval('clearFeedFilters()');
  rt.d.querySelector('#tabbar button[data-v="library"]').click(); await sleep(20);
  assert(JSON.stringify(rtRows()) === JSON.stringify(['tv-gone-season-2']),
    'a retired row the listener logged stays in the library');

  // ---------- recipes: the engine, the sheet, the cards, the random mix ----------
  const rcRow = (id, medium, game, title, extra) => Object.assign({ id, title, medium, game, composers: [], date: '2000-01-01',
    sources: [{ name: 'x', type: 'catalog', url: 'https://x/' + id, seenAt: '2026-08-01T10:00:00Z' }],
    ytmSearchUrl: 'https://music.youtube.com/search?q=' + id, notable: true, ytmAlbumUrl: null, art: null }, extra);
  const RC_ROWS = [
    rcRow('g-alpha', 'game', 'Alpha Quest', 'Alpha Quest Soundtrack', { composers: ['Nobuo Uematsu'], date: '2024-05-01',
      company: 'Square Enix', console: true, genres: ['Role-playing (RPG)'], tracksN: 3, playsTotal: 3000000, ytmPlaylistId: 'OLAK5uy_alpha' }),
    rcRow('g-beta', 'game', 'Zeta Blast', 'Zeta Blast Soundtrack', { composers: ['Yoko Shimomura'], date: '2021-03-01',
      company: 'Tiny Indie Co', console: false, genres: ['Platform'], tracksN: 2, playsTotal: 100000 }),
    rcRow('g-gamma', 'game', 'Gamma Drive', 'Gamma Drive Soundtrack', { composers: ['Nobuo Uematsu', 'Masashi Hamauzu'], date: '2018-09-09',
      company: 'Nintendo', console: true, genres: ['Role-playing (RPG)'], topTracks: [{ title: 'G-Top', plays: null }, { title: 'G-Two', plays: null }] }),
    rcRow('g-hidden', 'game', 'Hidden Gem', 'Hidden Gem Soundtrack', { composers: ['Nobuo Uematsu'], date: '2024-01-01',
      company: 'Nintendo', console: true, genres: ['Role-playing (RPG)'], tracksN: 1, playsTotal: 9000000 }),
    rcRow('g-empty', 'game', 'Empty', 'Empty Soundtrack', { date: '2023-01-01', tracksN: 0 }),
    rcRow('film-delta', 'film', 'Delta Falls', 'Delta Falls Soundtrack', { composers: ['Hans Zimmer'], date: '2022-07-07',
      genres: ['Drama'], tracksN: 2, scoresN: 1, playsTotal: 5000000, ytmPlaylistId: 'OLAK5uy_delta' }),
    rcRow('tv-eps', 'tv', 'Epsilon', 'Epsilon Season 1 Soundtrack', { composers: ['Bear McCreary'], date: '2020-02-02',
      genres: ['Drama', 'Crime'], tracksN: 2, scoresN: 1, playsTotal: 50000 }),
    rcRow('film-songs', 'film', 'Songs Movie', 'Songs Movie (Music From The Motion Picture)', { composers: ['Various Artists'],
      date: '2019-06-06', genres: ['Comedy'], tracksN: 1, scoresN: 0, playsTotal: 2000, songsAlbum: true }),
  ];
  const RC_TRACKS = {
    'g-alpha': [{ title: 'A1', plays: '10 plays', videoId: 'vidA1' }, { title: 'A2', plays: '2M plays', videoId: 'vidA2' },
                { title: 'A3', plays: '900K plays', videoId: 'vidA3' }],
    'g-beta': [{ title: 'B1', plays: '80K plays', videoId: 'vidB1' }, { title: 'B2', plays: '20K plays', videoId: 'vidB2' }],
    'g-hidden': [{ title: 'H1', plays: '9M plays', videoId: 'vidH1' }],
    // the collector marks film and tv tracks by anyone but the composer as songs
    'film-delta': [{ title: 'D1', plays: '1M plays', videoId: 'vidD1', artists: ['Hans Zimmer'] },
                   { title: 'D2', plays: '4M plays', videoId: 'vidD2', artists: ['Pop Star'], song: true }],
    'tv-eps': [{ title: 'E1', plays: '30K plays', videoId: 'vidE1', artists: ['Bear McCreary'] },
               { title: 'E2', plays: '20K plays', videoId: 'vidE2', artists: ['Cast'], song: true }],
    'film-songs': [{ title: 'S1', plays: '2K plays', videoId: 'vidS1', artists: ['Singer'], song: true }],
  };
  const TOP_OF = { 'Alpha Quest': 'A2', 'Zeta Blast': 'B1', 'Gamma Drive': 'G-Top', 'Delta Falls': 'D1', 'Epsilon': 'E1', 'Songs Movie': 'S1' };
  for (let i = 1; i <= 36; i++) {  // a pool wider than the random mix's 30, so a reshuffle changes the selection too
    const id = 'mix-' + String(i).padStart(2, '0');
    RC_ROWS.push(rcRow(id, 'game', 'Mix ' + i, 'Mix ' + i + ' Soundtrack', { composers: ['Mix Person'], date: (1950 + i) + '-01-01',
      company: 'Mix Studio', console: false, genres: ['Shooter'], tracksN: 1, playsTotal: 1000 }));
    RC_TRACKS[id] = [{ title: 'Mix Track ' + i, plays: '1K plays', videoId: 'vidM' + i }];
    TOP_OF['Mix ' + i] = 'Mix Track ' + i;
  }
  const rcHits = {};
  const rcFetch = async (url) => {
    rcHits[url] = (rcHits[url] || 0) + 1;
    if (url === 'data/releases.json') return { ok: true, status: 200, json: async () => ({ updatedAt: '2026-09-01T10:00:00Z', releases: RC_ROWS }) };
    const m = /^data\/tracks\/(.+)\.json$/.exec(url);
    const list = m && RC_TRACKS[decodeURIComponent(m[1])];
    if (list) return { ok: true, status: 200, json: async () => list };
    return { ok: false, status: 404, json: async () => ({}) };
  };
  const rc = makeDom(rcFetch, { v: 3, entries: {
    'g-alpha': { status: 'listened', listenedOn: '2026-08-01', rating: 4.5, likedTracks: ['A2'] },
    'g-beta': { status: 'listened', listenedOn: '2026-08-02', rating: 3 },
    'film-delta': { status: 'listened', listenedOn: '2026-08-03', rating: 5, likedTracks: ['D2'] },
    'tv-eps': { status: 'queued', queuedOn: '2026-08-04' },
    'g-gamma': { status: 'queued', queuedOn: '2026-08-05' },
    'g-hidden': { status: 'hidden' },
  }, lastSeen: T('2026-08-20T00:00:00Z') });
  await sleep(120);
  const rq = (sel) => rc.d.querySelector(sel);
  const rStored = () => JSON.parse(rc.w.localStorage.getItem('vgm-v1'));
  const rules = (o) => `Object.assign(recipeBlank(), ${JSON.stringify(o)})`;
  const stats = (o) => JSON.parse(rc.w.eval(`JSON.stringify(recipeStats(${rules(o)}))`));
  const pool = (o) => { const s = stats(o); return s.tracks + '/' + s.albums; };
  const titles = (o, seed = 1) => JSON.parse(rc.w.eval(`JSON.stringify(recipeBuild(${rules(o)}, ${seed}).map(t => t.title))`));
  const build = async (o, seed = 1) => { await rc.w.eval(`recipeLoad(${rules(o)}, ${seed})`); return titles(o, seed); };
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  assert(rc.errors.length === 0, 'the recipe fixture boots clean');
  assert(same(rStored().recipes, []), 'a v3 state without recipes gains an empty list');

  // filters, alone: each narrows the pool, counted from row metadata without a single file fetch
  assert(pool({}) === '48/42', 'no rules: every visible album with tracks; the hidden and the empty one stay out');
  assert(Object.keys(rcHits).length === 1, 'counting a recipe fetches no tracklist files');
  assert(pool({ medium: 'film' }) === '3/2' && pool({ medium: 'tv' }) === '2/1' && pool({ medium: 'screen' }) === '5/3'
    && pool({ medium: 'game' }) === '43/39', 'medium narrows to games, film, tv, or both screens');
  assert(pool({ medium: 'game', genre: { game: 'Role-playing (RPG)', screen: 'all' } }) === '5/2', 'a game genre narrows inside games');
  assert(pool({ medium: 'screen', genre: { game: 'all', screen: 'Drama' } }) === '4/2'
    && pool({ medium: 'tv', genre: { game: 'all', screen: 'Crime' } }) === '2/1', 'a screen genre narrows inside film + tv');
  assert(pool({ genre: { game: 'Role-playing (RPG)', screen: 'Drama' } }) === '48/42', 'under all mediums a stored genre is inert');
  assert(pool({ yearFrom: '2020', yearTo: '2022' }) === '6/3' && pool({ yearFrom: '2024' }) === '3/1' && pool({ yearTo: '1951' }) === '1/1',
    'year bounds narrow by release year, either side open');
  assert(pool({ composer: 'uematsu' }) === '5/2' && pool({ composer: '  UEMATSU ' }) === '5/2' && pool({ composer: 'nobody' }) === '0/0',
    'composer is a folded contains-match');
  assert(pool({ rating: '3' }) === '7/3' && pool({ rating: '4' }) === '5/2' && pool({ rating: '5' }) === '2/1', 'rating thresholds read the diary');
  assert(pool({ hearted: true }) === '5/2', 'hearted keeps albums with at least one ♥ track');
  assert(pool({ medium: 'game', co: 'big' }) === '5/2' && pool({ medium: 'game', co: 'indie' }) === '38/37'
    && pool({ medium: 'game', console: true }) === '5/2', 'scope and console narrow games like the feed');
  assert(pool({ co: 'big', console: true }) === '48/42', 'scope and console are inert outside the games medium');
  assert(pool({ scores: true }) === '45/41' && pool({ medium: 'film', scores: true }) === '1/1' && pool({ medium: 'film' }) === '3/2',
    'scores only drops song tracks and keeps their albums; off by default');
  assert(pool({ hearted: true, pick: 'hearted', scores: true }) === '2/2', 'before loading, hearted counts cannot know which hearts are songs');
  assert(pool({ source: 'library' }) === '7/3' && pool({ source: 'queue' }) === '4/2', 'library and queue sources');
  assert(pool({ source: 'library', medium: 'game', rating: '4', hearted: true }) === '3/1', 'filters AND together');
  assert(pool({ source: 'library', medium: 'game', rating: '4', hearted: true, pick: 'top', topN: 2 }) === '2/1'
    && pool({ source: 'library', medium: 'game', rating: '4', hearted: true, pick: 'hearted' }) === '1/1',
    'the track pick counts per album from metadata');
  assert(stats({ limit: 20 }).capped === true && stats({ limit: 20 }).expected === 20 && stats({}).capped === false,
    'the cap reports itself without changing the pool');

  // selection: top N ranks by plays, a missing file falls back to topTracks, hearts rematch the tracklist
  const RPG = { medium: 'game', genre: { game: 'Role-playing (RPG)', screen: 'all' } };
  assert(same(await build(Object.assign({ pick: 'top', topN: 2, order: 'newest' }, RPG)), ['A2', 'A3', 'G-Top', 'G-Two']),
    'top 2 ranks by plays, not running order, and falls back to topTracks without a file');
  assert(rcHits['data/tracks/g-alpha.json'] === 1 && rcHits['data/tracks/g-gamma.json'] === undefined,
    'the build read the album with a file and never asked for one the row does not promise');
  assert(same(await build({ hearted: true, pick: 'hearted' }), ['D2', 'A2']), 'the ♥ pick keeps only hearted tracks');
  const heartsExp = JSON.parse(rc.w.eval(`JSON.stringify(recipeBuild(${rules({ hearted: true, pick: 'hearted' })}, 1))`));
  assert(heartsExp[0].videoId === 'vidD2' && heartsExp[1].videoId === 'vidA2', 'hearted tracks carry the videoId from the loaded file');
  assert(same(await build({ hearted: true, pick: 'hearted', scores: true }), ['A2']) && pool({ hearted: true, pick: 'hearted', scores: true }) === '1/1',
    'a hearted song leaves under scores only, and the loaded count agrees');
  assert(same(await build({ medium: 'film', pick: 'top', topN: 1, scores: true }), ['D1'])
    && same(await build({ medium: 'film', pick: 'top', topN: 1 }), ['D2', 'S1']), 'scores only changes which track is the top one');

  // order, then limit: the same pool in four orders, cut after ordering
  const SINCE18 = { medium: 'game', yearFrom: '2018', pick: 'top', topN: 1 };
  assert(same(await build(Object.assign({ order: 'newest' }, SINCE18)), ['A2', 'B1', 'G-Top']), 'newest album: by release date');
  assert(same(await build(Object.assign({ order: 'album' }, SINCE18)), ['A2', 'G-Top', 'B1']), 'album order: albums a to z');
  assert(same(await build(Object.assign({ order: 'plays' }, SINCE18)), ['A2', 'B1', 'G-Top']), 'most played: by track plays, unknown last');
  assert(same(await build(Object.assign({ order: 'album', limit: 2 }, SINCE18)), ['A2', 'G-Top']), 'the limit cuts after ordering');
  assert(same(await build({ medium: 'game', order: 'plays', limit: 3 }), ['A2', 'A3', 'B1']),
    'most played ranks tracks across albums, so one album can fill several slots');
  assert(same(await build({ medium: 'game', pick: 'top', topN: 1, order: 'plays', limit: 3 }), ['A2', 'B1', 'Mix Track 36']),
    'select runs before order: top 1 per album, then the best of those');
  const sh1 = await build({ medium: 'game', yearFrom: '2018', order: 'shuffle' }, 7);
  const sh2 = await build({ medium: 'game', yearFrom: '2018', order: 'shuffle' }, 8);
  assert(sh1.length === 7 && sh2.length === 7 && !same(sh1, sh2) && same(sh1.slice().sort(), sh2.slice().sort()),
    'shuffle reorders the same tracks; a different seed deals differently');
  assert(same(sh1, titles({ medium: 'game', yearFrom: '2018', order: 'shuffle' }, 7)), 'the same seed deals the same order: a re-export is stable');
  assert(same(rc.w.eval(`JSON.stringify(recipeLoadIds(${rules({ order: 'newest', limit: 3 })}, 1))`), JSON.stringify(['g-alpha', 'film-delta', 'g-beta', 'tv-eps']))
    , 'a card or export reads only the albums that can make the cut, plus a small margin');

  // live re-evaluation: a new rating changes what a recipe produces
  const LIB4 = { source: 'library', rating: '4' };
  assert(pool(LIB4) === '5/2', 'before: two albums rated 4+');
  rc.w.eval(`editEntry('g-beta', e => { e.rating = 4; })`);
  assert(pool(LIB4) === '7/3' && same(await build(Object.assign({ order: 'newest', pick: 'top', topN: 1 }, LIB4)), ['A2', 'D2', 'B1']),
    'after: rating a third album adds it to the recipe without a save');
  rc.w.eval(`editEntry('g-beta', e => { e.rating = 3; })`);

  // names: generated from the rules, editable
  const autoName = (o) => rc.w.eval(`recipeAutoName(${rules(o)})`);
  assert(autoName({ rating: '4', medium: 'film', pick: 'top', topN: 2 }) === '4★+ film scores, top 2 each', 'the default name describes the rules');
  assert(autoName({ rating: '4', medium: 'film', pick: 'top', topN: 2, scores: true }) === '4★+ film scores only, top 2 each'
    && autoName({ scores: true }) === 'scores only' && autoName({ medium: 'game', scores: true }) === 'game scores only'
    && autoName({ medium: 'screen', scores: true, order: 'shuffle' }) === 'film + tv scores only, shuffled', 'scores only reads out in the name');
  assert(autoName({ source: 'queue', medium: 'game', co: 'indie', console: true, genre: { game: 'Platform', screen: 'all' }, order: 'shuffle', pick: 'hearted' })
    === 'indie console platform game soundtracks from the queue, ♥ tracks only, shuffled', 'every rule that is set reads out');
  assert(autoName({ composer: 'Uematsu', yearFrom: '2010', yearTo: '2015', pick: 'top', topN: 1 }) === 'soundtracks by Uematsu 2010 to 2015, top track each'
    && autoName({ yearFrom: '2020' }) === 'soundtracks since 2020' && autoName({ yearTo: '1999' }) === 'soundtracks up to 1999', 'composer and years read out');
  assert(rc.w.eval(`recipeName(${rules({ name: 'My Faves', rating: '5' })})`) === 'My Faves', 'a typed name wins over the generated one');

  // the sheet: rows, live count, genre sub-sheet, typed fields, save, edit, delete
  rc.d.querySelector('#tabbar button[data-v="library"]').click();
  rq('#libpl').click(); await sleep(120);
  const rCards = () => [...rc.d.querySelectorAll('#list .plcard')].map(x => x.dataset.plc);
  assert(same(rCards(), ['liked', 'queue', 'rated', 'random']) && rq('#rcpnew') !== null, 'four built-ins and a new-recipe button, no recipes yet');
  rq('#rcpnew').click();
  const rSheet = () => rc.d.querySelector('#sheetwrap #sheet');
  const rCount = () => rq('#rcount').textContent;
  const tapRule = async (field, v) => { rq(`#sheetwrap [data-rc="${field}"][data-v="${v}"]`).click(); await sleep(10); };
  const typeIn = async (id, v) => { const el = rq('#sheetwrap #' + id); el.value = v; el.dispatchEvent(new rc.w.Event('input', { bubbles: true })); await sleep(10); };
  assert(rSheet() !== null && rSheet().classList.contains('tall') && rq('#sheetwrap select') === null, 'the recipe sheet is the tall control sheet, no native select');
  assert(rCount() === '48 tracks from 42 albums' && rq('#rc-name').placeholder === 'soundtracks', 'a live count and the generated name greet a new recipe');
  assert(rq('#sheetwrap [data-rct="scores"]').getAttribute('aria-pressed') === 'false', 'scores only starts off for a recipe');
  rq('#sheetwrap [data-rct="scores"]').click(); await sleep(10);
  assert(rCount() === '45 tracks from 41 albums' && rq('#rc-name').placeholder === 'scores only'
    && rq('#sheetwrap [data-rct="scores"]').getAttribute('aria-pressed') === 'true', 'the toggle drops the songs and names itself');
  rq('#sheetwrap [data-rct="scores"]').click(); await sleep(10);
  assert(rCount() === '48 tracks from 42 albums' && rq('#rc-name').placeholder === 'soundtracks', 'and comes back off');
  assert(rq('#sheetwrap [data-rc="medium"]') !== null && rq('#sheetwrap #rc-genre') !== null && rq('#sheetwrap [data-rc="co"]') === null,
    'under all mediums the sheet shows the all-mediums genre row but no scope or console rows');
  await tapRule('source', 'library');
  assert(rCount() === '7 tracks from 3 albums' && rq('#rc-name').placeholder === 'soundtracks from the library', 'the count and the name follow the source');
  await tapRule('rating', '4');
  assert(rCount() === '5 tracks from 2 albums', 'the count follows the rating');
  assert(rq('#sheetwrap [data-rc="topN"]') === null, 'the per-album N hides until top n is picked');
  await tapRule('pick', 'top');
  assert(rq('#sheetwrap [data-rc="topN"][data-v="3"]').classList.contains('on'), 'top n starts at 3');
  await tapRule('topN', '2');
  assert(rCount() === '4 tracks from 2 albums' && rq('#rc-name').placeholder === '4★+ soundtracks from the library, top 2 each',
    'top 2 per album counts two from each');
  await tapRule('medium', 'game');
  assert(rCount() === '2 tracks from 1 album' && rq('#sheetwrap #rc-genre') !== null && rq('#sheetwrap [data-rc="co"][data-v="big"]') !== null
    && rq('#sheetwrap [data-rct="console"]') !== null, 'picking games reveals genre, scope, and console');
  rq('#sheetwrap #rc-genre').click(); await sleep(10);
  assert(rq('#sheetwrap [data-shrg="Role-playing (RPG)"]') !== null && rq('#sheetwrap #rc-genre') === null, 'the genre row opens its own list');
  rq('#sheetwrap [data-shrg="Role-playing (RPG)"]').click(); await sleep(10);
  assert(rq('#sheetwrap #rc-genre .shl').textContent === 'role-playing (rpg)' && rCount() === '2 tracks from 1 album',
    'a genre pick returns to the recipe with the pick shown');
  await tapRule('limit', '20');
  assert(rq('#sheetwrap [data-rc="limit"][data-v="20"]').classList.contains('on'), 'limit segments select');
  await typeIn('rc-composer', 'zimmer');
  assert(rCount() === '0 tracks from 0 albums' && rq('#sheetwrap #rc-composer').value === 'zimmer',
    'typing a composer updates the count in place, the field keeps its text');
  await typeIn('rc-composer', '');
  await typeIn('rc-from', '2025');
  assert(rCount() === '0 tracks from 0 albums', 'a from-year past every album empties the count');
  await typeIn('rc-from', '20');
  assert(rCount() === '2 tracks from 1 album', 'a partial year is not a bound yet');
  await typeIn('rc-from', '');
  await typeIn('rc-name', 'My Faves');
  rq('#sheetwrap #rc-save').click(); await sleep(120);
  assert(rSheet() === null && rStored().recipes.length === 1, 'save closes the sheet and stores the recipe');
  const saved = rStored().recipes[0];
  assert(saved.name === 'My Faves' && saved.source === 'library' && saved.rating === '4' && saved.pick === 'top' && saved.topN === 2
    && saved.medium === 'game' && saved.genre.game === 'Role-playing (RPG)' && saved.limit === 20 && saved.composer === '' && saved.yearFrom === ''
    && saved.scores === false,
    'the stored recipe carries every rule as set');
  const rKey = 'r:' + saved.id;
  const rCard = () => rc.d.querySelector(`#list .plcard[data-plc="${rKey}"]`);
  assert(same(rCards(), ['liked', 'queue', 'rated', 'random', rKey]) && rCard().getAttribute('aria-expanded') === 'true',
    'the new recipe lands after the built-ins, opened');
  assert(rCard().querySelector('.plname').textContent === 'My Faves'
    && rCard().querySelector('.plmeta').textContent === '2 tracks · 4★+ role-playing (rpg) game soundtracks from the library, top 2 each',
    'a renamed recipe keeps its rules readable on the card');
  assert(same([...rCard().querySelectorAll('.pltrack .t')].map(x => x.textContent), ['A2', 'A3']), 'the open card previews the tracks');
  assert(rCard().querySelector('[data-plx]').disabled === false && rCard().querySelector('[data-rcpedit]') !== null
    && rCard().querySelector('[data-rcpdel]') !== null, 'export, edit, and delete are offered');
  rCard().querySelector('[data-rcpedit]').click(); await sleep(10);
  assert(rSheet() !== null && rq('#rc-name').value === 'My Faves' && rq('#sheetwrap [data-rc="rating"][data-v="4"]').classList.contains('on'),
    'edit reopens the sheet with the saved rules');
  await tapRule('rating', 'any');
  rq('#sheetwrap #rc-cancel').click(); await sleep(10);
  assert(rSheet() === null && rStored().recipes[0].rating === '4', 'cancel keeps the saved recipe as it was');
  rCard().querySelector('[data-rcpedit]').click(); await sleep(10);
  await tapRule('rating', 'any');
  rq('#sheetwrap #rc-save').click(); await sleep(20);
  assert(rStored().recipes.length === 1 && rStored().recipes[0].rating === 'any' && rStored().recipes[0].id === saved.id,
    'saving an edit replaces the recipe in place');
  rq('#rcpnew').click(); await sleep(10);
  rc.w.dispatchEvent(new rc.w.KeyboardEvent('keydown', { key: 'Escape' }));
  assert(rSheet() === null && rStored().recipes.length === 1, 'escape discards a new draft');
  rCard().querySelector('[data-rcpdel]').click(); await sleep(10);
  assert(rCard().querySelector('[data-rcpdel]').textContent === 'SURE? TAP AGAIN' && rStored().recipes.length === 1, 'delete arms on the first tap');
  rCard().querySelector('[data-rcpdel]').click(); await sleep(10);
  assert(rCard() === null && same(rStored().recipes, []), 'the second tap deletes the recipe');
  assert(rc.errors.length === 0, 'the sheet flow stays clean');

  // export: a recipe's JSON has exactly a built-in's shape; an empty recipe can neither export nor publish
  rc.w.eval(`S.recipes.push(Object.assign(recipeBlank(), { id: 'rx-hearts', medium: 'game', hearted: true, pick: 'hearted' }),
                            Object.assign(recipeBlank(), { id: 'rx-empty', composer: 'nobody' })); save(); renderAll();`);
  await rc.w.eval(`plLoad('liked')`); await rc.w.eval(`plLoad('r:rx-hearts')`);
  const heartsOut = JSON.parse(rc.w.eval(`JSON.stringify(plExportObj('r:rx-hearts'))`));
  const likedOut = JSON.parse(rc.w.eval(`JSON.stringify(plExportObj('liked'))`));
  assert(same(Object.keys(heartsOut), ['app', 'name', 'tracks']) && heartsOut.app === 'scorekeep-playlist'
    && heartsOut.name === 'Scorekeep · ♥ game soundtracks, ♥ tracks only', 'a recipe export carries the app label and the prefixed name');
  assert(same(heartsOut.tracks[0], likedOut.tracks[0]) && same(heartsOut.tracks[0],
    { game: 'Alpha Quest', title: 'A2', videoId: 'vidA2', ytmPlaylistId: 'OLAK5uy_alpha', searchQuery: 'Alpha Quest A2' }),
    'a recipe track is byte-identical to the same track from a built-in');
  const emptyCard = () => rc.d.querySelector('#list .plcard[data-plc="r:rx-empty"]');
  assert(emptyCard().querySelector('.plmeta').textContent.startsWith('0 tracks'), 'an empty recipe shows as empty');
  emptyCard().click(); await sleep(20);
  assert(emptyCard().querySelector('[data-plx]').disabled === true && emptyCard().textContent.includes('nothing matches these rules yet'),
    'an empty recipe cannot export');
  rc.w.localStorage.setItem('vgm-pub-token', 'github_pat_RC'); rc.w.eval('renderList()');
  assert(emptyCard().querySelector('[data-plp]').disabled === true, 'an empty recipe cannot publish');
  const rcCalls = [];
  const rcRealFetch = rc.w.fetch;
  rc.w.fetch = async (url, opts) => { rcCalls.push(String(url)); return rcRealFetch(url, opts); };
  await rc.w.eval(`publishPlaylist('r:rx-empty')`); await rc.w.eval(`exportPlaylist('r:rx-empty')`);
  assert(!rcCalls.some(u => u.includes('github')) && rc.errors.length === 0, 'forcing an empty publish sends nothing');
  rc.w.fetch = rcRealFetch;
  rc.w.localStorage.removeItem('vgm-pub-token');

  // backups: recipes ride along, old backups import without them, junk is sanitized
  const rcDump = JSON.parse(rc.w.eval(`JSON.stringify(buildExport())`));
  assert(rcDump.state.recipes.length === 2 && rcDump.state.recipes[0].id === 'rx-hearts', 'a backup carries the recipes');
  assert(rc.w.eval(`applyImport('{"v":3,"entries":{}}')`) === true && same(rStored().recipes, []) && rStored().mixScores === true,
    'an older backup without recipes imports clean, with the random mix on scores only');
  assert(rc.w.eval(`applyImport('{"v":3,"entries":{},"mixScores":false}')`) === true && rStored().mixScores === false, 'the random mix toggle rides in backups');
  assert(rc.w.eval(`applyImport(${JSON.stringify(JSON.stringify(rcDump))})`) === true && rStored().recipes.length === 2
    && rStored().recipes[0].hearted === true && rStored().recipes[0].pick === 'hearted', 'export then import round-trips the recipes');
  assert(rc.w.eval(`applyImport('{"v":3,"entries":{},"recipes":[{"id":"ok","limit":999,"topN":9,"order":"bogus","rating":"4","name":"  Kept  ","scores":"yes"},{"id":"ok"},{"name":"no id"},"junk",{"id":"g","genre":"Platform","medium":"game","yearFrom":"20x0"}]}')`) === true
    && same(rStored().recipes.map(r => [r.id, r.limit, r.topN, r.order, r.rating, r.name, r.genre.game, r.yearFrom, r.scores]),
            [['ok', 50, 3, 'plays', '4', 'Kept', 'all', '', false], ['g', 50, 3, 'plays', 'any', '', 'Platform', '', false]]),
    'import sanitizes recipes: bad values fall to defaults, dupes and idless entries drop');
  rc.w.eval(`applyImport(${JSON.stringify(JSON.stringify(rcDump))})`);

  // the random mix: one top track per album, the feed's medium and hidden state, reseeded per reshuffle, replaced on publish
  rc.w.eval(`RSEED.random = 1`); await rc.w.eval(`plLoad('random')`);
  const mix1 = JSON.parse(rc.w.eval(`JSON.stringify(plExportObj('random'))`));
  assert(same(Object.keys(mix1), ['app', 'name', 'replace', 'tracks']) && mix1.replace === true && mix1.name === 'Scorekeep · Random Mix',
    'the random mix export asks the companion to replace, and is otherwise a built-in export');
  assert(mix1.tracks.length === 30 && new Set(mix1.tracks.map(t => t.game)).size === 30, '30 tracks from 30 different albums');
  assert(mix1.tracks.every(t => TOP_OF[t.game] === t.title) && !mix1.tracks.some(t => t.game === 'Hidden Gem' || t.game === 'Empty'),
    'each album sends its most-played track; hidden and empty albums never appear');
  rc.w.eval(`RSEED.random = 2`); await rc.w.eval(`plLoad('random')`);
  const mix2 = JSON.parse(rc.w.eval(`JSON.stringify(plExportObj('random'))`));
  const gamesOf = m => m.tracks.map(t => t.game);
  assert(mix2.tracks.length === 30 && !same(gamesOf(mix1), gamesOf(mix2)) && !same(gamesOf(mix1).slice().sort(), gamesOf(mix2).slice().sort()),
    'a reshuffle changes both the order and the selection');
  rc.w.eval(`setFeedMedium('screen')`); await rc.w.eval(`plLoad('random')`);
  const mixS = JSON.parse(rc.w.eval(`JSON.stringify(plExportObj('random'))`));
  assert(same(gamesOf(mixS).sort(), ['Delta Falls', 'Epsilon']), 'the mix follows the feed medium: film + tv gives the two screen albums');
  rc.w.eval(`setFeedMedium('game')`); await rc.w.eval(`plLoad('random')`);
  const mixG = JSON.parse(rc.w.eval(`JSON.stringify(plExportObj('random'))`));
  assert(mixG.tracks.length === 30 && !gamesOf(mixG).some(g => g === 'Delta Falls' || g === 'Epsilon'), 'games only keeps screen albums out');
  rc.w.eval(`setFeedMedium('all')`);
  for (const seed of [3, 4, 5, 6]) {
    rc.w.eval(`RSEED.random = ${seed}`); await rc.w.eval(`plLoad('random')`);
    if (JSON.parse(rc.w.eval(`JSON.stringify(plExportObj('random'))`)).tracks.some(t => t.game === 'Hidden Gem')) assert(false, 'a hidden album leaked into the mix');
  }
  rc.d.querySelector('#tabbar button[data-v="library"]').click();
  if (rStored().libView !== 'playlists') rq('#libpl').click();
  await sleep(120);
  const mixCard = () => rc.d.querySelector('#list .plcard[data-plc="random"]');
  assert(mixCard().querySelector('.plname').textContent === 'Scorekeep · Random Mix' && mixCard().querySelector('.plmeta').textContent.startsWith('30 tracks'),
    'the random mix card is the fourth built-in');
  mixCard().click(); await sleep(120);
  assert(mixCard().querySelector('#reshuffle') !== null && mixCard().querySelectorAll('.pltrack').length === 30, 'the open card offers reshuffle and previews 30 tracks');
  const before = rc.w.eval('RSEED.random');
  const realRandom = rc.w.Math.random;
  rc.w.Math.random = () => 0.25;
  mixCard().querySelector('#reshuffle').click(); await sleep(120);
  rc.w.Math.random = realRandom;
  assert(rc.w.eval('RSEED.random') !== before && rc.w.eval('RSEED.random') === Math.floor(0.25 * 0x7fffffff)
    && mixCard().querySelectorAll('.pltrack').length === 30, 'reshuffle reseeds the mix and redraws the card');
  rc.w.eval(`setFeedMedium('screen')`); await rc.w.eval(`plLoad('random')`); await sleep(50);
  const mixRows = () => [...mixCard().querySelectorAll('.pltrack .g')].map(x => x.textContent).sort();
  assert(same(mixRows(), ['Delta Falls', 'Epsilon']) && mixCard().querySelector('#mixscores').textContent === '✓ SCORES ONLY'
    && mixCard().querySelector('.plmeta').textContent.includes('scores only'), 'the random mix starts on scores only and says so');
  mixCard().querySelector('#mixscores').click(); await sleep(120);
  assert(rStored().mixScores === false && same(mixRows(), ['Delta Falls', 'Epsilon', 'Songs Movie'])
    && mixCard().querySelector('#mixscores').textContent === 'SCORES ONLY' && !mixCard().querySelector('.plmeta').textContent.includes('scores only'),
    'switching scores only off lets the song compilation into the mix, and the choice persists');
  mixCard().querySelector('#mixscores').click(); await sleep(120);
  assert(rStored().mixScores === true && same(mixRows(), ['Delta Falls', 'Epsilon']), 'and back on drops it again');
  rc.w.eval(`setFeedMedium('all')`);
  assert(rc.errors.length === 0, 'the random mix stays clean');

  // ---------- scores only in the main filters, the genre picker, typed limits ----------
  rc.d.querySelector('#tabbar button[data-v="feed"]').click(); await sleep(20);
  rq('#c-filters').click(); await sleep(10);
  assert(rq('#sheetwrap #shscores') !== null && rq('#sheetwrap #shscores').getAttribute('aria-pressed') === 'false'
    && rq('#sheetwrap #shgenrerow') !== null, 'under all mediums the feed sheet offers scores only and the all-mediums genre row');
  rq('#sheetwrap #shscores').click(); await sleep(20);
  assert(rStored().feedScores === true && rq('#c-filters').textContent === 'filters · scores only', 'scores only persists and names itself on the chip');
  rq('#sheetwrap [data-shmed="screen"]').click(); await sleep(20);
  rq('#sheetwrap [data-shsub="film"]').click(); await sleep(20);
  assert(rq('#c-filters').textContent === 'filters · film, scores only' && rq('#sheetwrap #shgenrerow').textContent.includes('genre · all'),
    'the chip reads medium then scores only; the genre is one row naming its pick');
  rq('#sheetwrap #shdone').click(); await sleep(20);
  const deltaRow = () => rc.d.querySelector('#list .row[data-id="film-delta"]');
  deltaRow().click(); await sleep(120);
  assert(deltaRow().querySelectorAll('.xtrack').length === 1 && deltaRow().textContent.includes('D1') && !deltaRow().textContent.includes('D2')
    && deltaRow().querySelector('.xall').textContent === 'All 1 tracks ›', 'scores only hides the song from the expanded row and its count');
  rc.w.eval(`openAlbum('film-delta')`); await sleep(20);
  assert([...rc.d.querySelectorAll('#album .atrack .ttl')].map(x => x.textContent).join() === 'D1', 'the album page lists score tracks only');
  rc.w.__opened = null; rc.d.querySelector('#album .atrack').click();
  assert(rc.w.__opened === 'https://music.youtube.com/watch?v=vidD1&list=OLAK5uy_delta', 'tapping the first shown track plays that track, not the hidden one');
  rq('#album .aclose').click();
  const songsRow = () => rc.d.querySelector('#list .row[data-id="film-songs"]');
  songsRow().click(); await sleep(120);
  assert(songsRow().textContent.includes('songs only, hidden by scores only') && songsRow().querySelector('.xall') === null,
    'an album with no score track says so instead of listing nothing');
  songsRow().click();
  rq('#c-filters').click(); await sleep(10);
  rq('#sheetwrap [data-shmed="game"]').click(); await sleep(20);
  assert(rq('#sheetwrap #shscores') === null && rq('#c-filters').textContent === 'filters · games' && rStored().feedScores === true,
    'under games the row hides and the chip drops it, the choice kept for later');
  // the genre picker: a row, a sub-sheet with counts, back on a pick, scroll remembered
  assert(rq('#sheetwrap #shgenrerow').textContent.includes('genre · all') && rq('#sheetwrap [data-shgenre]') === null,
    'the genre row shows the pick and no inline list');
  rq('#sheetwrap #shgenrerow').click(); await sleep(10);
  const rpgRow = () => rq('#sheetwrap [data-shgenre="Role-playing (RPG)"]');
  assert(rq('#sheetwrap #shback') !== null && rpgRow() !== null && rpgRow().querySelector('.shr').textContent === '3',
    'the picker lists the medium\'s genres with counts');
  rq('#sheetwrap .shbody').scrollTop = 37;
  rpgRow().click(); await sleep(20);
  assert(rq('#sheetwrap #shgenrerow') !== null && rq('#sheetwrap #shgenrerow').textContent.includes('genre · role-playing (rpg)')
    && rStored().feedGenre.game === 'Role-playing (RPG)' && rq('#c-filters').textContent === 'filters · games, role-playing (rpg)',
    'a pick returns to the filters with the row and the chip updated');
  rq('#sheetwrap #shgenrerow').click(); await sleep(10);
  assert(rq('#sheetwrap .shbody').scrollTop === 37 && rpgRow().querySelector('.shr').textContent === '3 ✓',
    'the picker reopens where it was scrolled, the pick ticked');
  rq('#sheetwrap #shback').click(); await sleep(10);
  assert(rq('#sheetwrap #shgenrerow') !== null && rStored().feedGenre.game === 'Role-playing (RPG)', 'back returns without changing the pick');
  rq('#sheetwrap #shclear').click(); await sleep(20);
  assert(rStored().feedScores === false && rStored().feedGenre.game === 'all', 'clear resets scores only with the rest');
  rq('#sheetwrap #shdone').click(); await sleep(10);
  // the library sheet and the songs view
  rc.d.querySelector('#tabbar button[data-v="library"]').click(); await sleep(20);
  if (rStored().libView !== 'albums') { rq('#' + (rStored().libView === 'songs' ? 'libsongs' : 'libpl')).click(); await sleep(20); }
  rq('#c-libfilters').click(); await sleep(10);
  assert(rq('#sheetwrap #shlscores') !== null, 'the library sheet offers scores only under medium');
  rq('#sheetwrap #shlscores').click(); await sleep(20);
  assert(rStored().libScores === true && rq('#c-libfilters').textContent === 'filters · scores only', 'the library toggle persists and labels its chip');
  rq('#sheetwrap [data-shlmed="game"]').click(); await sleep(20);
  assert(rq('#sheetwrap #shlscores') === null && rq('#c-libfilters').textContent === 'filters · games', 'hidden under games in the library too');
  rq('#sheetwrap [data-shlmed="all"]').click(); await sleep(20);
  rq('#sheetwrap #shdone').click(); await sleep(10);
  rq('#libsongs').click(); await sleep(150);
  const songTitles = () => [...rc.d.querySelectorAll('#list .row.song')].map(x => x.dataset.t);
  assert(same(songTitles(), ['A2']) && rq('#c-libfilters').textContent === 'filters · scores only', 'the songs view hides a hearted song under scores only');
  rq('#c-libfilters').click(); await sleep(10);
  rq('#sheetwrap #shlscores').click(); await sleep(150);
  assert(same(songTitles(), ['A2', 'D2']), 'and shows it again when off');
  rq('#sheetwrap #shdone').click(); await sleep(10);
  rq('#libsongs').click(); await sleep(20);
  // typed limits: the recipe sheet and the random mix card
  rq('#libpl').click(); await sleep(150);
  rq('#rcpnew').click(); await sleep(10);
  assert(rq('#sheetwrap #rc-limit').value === '50' && rq('#sheetwrap [data-rc="limit"][data-v="50"]').classList.contains('on'), 'the limit field starts at the preset');
  await typeIn('rc-limit', '35');
  assert(rq('#sheetwrap [data-rc="limit"].on') === null && rCount().endsWith('capped at 35') && rq('#sheetwrap #rc-limit').value === '35',
    'a typed limit deselects the presets and caps the count, the caret untouched');
  await typeIn('rc-limit', '999');
  assert(rCount().endsWith('capped at 35'), 'an out-of-range number changes nothing');
  await tapRule('limit', '20');
  assert(rq('#sheetwrap #rc-limit').value === '20' && rCount().endsWith('capped at 20'), 'a preset fills the field');
  await typeIn('rc-limit', '7');
  rq('#sheetwrap #rc-save').click(); await sleep(120);
  assert(rStored().recipes[rStored().recipes.length - 1].limit === 7, 'the typed limit saves');
  const mixCard2 = () => rc.d.querySelector('#list .plcard[data-plc="random"]');
  if (mixCard2().getAttribute('aria-expanded') !== 'true') { mixCard2().click(); await sleep(150); }
  assert(mixCard2().querySelector('#mixlimit').value === '30' && mixCard2().querySelector('[data-mixlimit="30"]').classList.contains('on'),
    'the random mix shows its 30 with presets');
  mixCard2().querySelector('[data-mixlimit="20"]').click(); await sleep(150);
  assert(rStored().mixLimit === 20 && mixCard2().querySelectorAll('.pltrack').length === 20 && mixCard2().querySelector('.plmeta').textContent.startsWith('20 tracks'),
    'a preset redraws the mix at that size');
  const mixInp = mixCard2().querySelector('#mixlimit');
  mixInp.value = '5'; mixInp.dispatchEvent(new rc.w.Event('input', { bubbles: true }));
  assert(rStored().mixLimit === 5 && mixCard2().querySelector('#mixlimit') === mixInp && mixCard2().querySelector('[data-mixlimit].on') === null,
    'typing stores the limit at once without redrawing the card mid-keystroke');
  await sleep(800);
  assert(mixCard2().querySelectorAll('.pltrack').length === 5 && mixCard2().querySelector('.plmeta').textContent.startsWith('5 tracks'),
    'the card redraws once the typing settles');
  mixCard2().querySelector('#mixlimit').click();
  assert(mixCard2().getAttribute('aria-expanded') === 'true', 'tapping the field never folds the card');
  assert(rc.w.eval(`applyImport('{"v":3,"entries":{},"mixLimit":999,"feedScores":true}')`) === true
    && rStored().mixLimit === 30 && rStored().feedScores === true && rStored().libScores === false,
    'backups carry the toggles and a bad limit falls to 30');
  assert(rc.errors.length === 0, 'the filters and limits stay clean');

  // ---------- moods: the recipe row, the chips, the feed filtered to a mood ----------
  rc.w.eval(`recipeOpen(null)`);
  assert(rq('#sheetwrap #rc-mood') === null, 'no album carries moods: the recipe sheet shows no mood row');
  rc.w.eval(`recipeCancel()`);
  const mdRow = (id, medium, game, extra) => Object.assign({ id, title: game + ' Soundtrack', medium, game, composers: [], date: '2025-01-01',
    sources: [{ name: 'x', type: 'catalog', url: 'https://x/' + id, seenAt: '2026-08-25T10:00:00Z' }],
    ytmSearchUrl: 'https://music.youtube.com/search?q=' + id, notable: true, ytmAlbumUrl: null, art: null }, extra);
  const MD_ROWS = [
    mdRow('m-silent', 'game', 'Silent Town', { tracksN: 4, playsTotal: 8000000, moods: ['eerie', 'suspenseful', 'sad'], moodsN: [3, 2, 1] }),
    mdRow('m-hero', 'film', 'Hero Rising', { tracksN: 3, scoresN: 2, playsTotal: 8000000, moods: ['epic', 'heroic', 'suspenseful'], moodsN: [2, 2, 1] }),
    mdRow('m-calm', 'tv', 'Calm Waters', { tracksN: 3, playsTotal: 30000, moods: ['peaceful', 'tender', 'nostalgic'], moodsN: [2, 1, 1] }),
    mdRow('m-untagged', 'game', 'Not Yet', { tracksN: 2, playsTotal: 9000 }),
    mdRow('m-bare', 'game', 'Bare Bones', { tracksN: 1, playsTotal: 10, moods: [], moodsN: [] }),
  ];
  const MD_TRACKS = {
    // a partly tagged album: its most played track carries no mood
    'm-silent': [{ title: 'S1', plays: '1M plays', videoId: 'vS1', moods: ['eerie', 'suspenseful'] },
                 { title: 'S2', plays: '2M plays', videoId: 'vS2', moods: ['eerie'] },
                 { title: 'S3', plays: '10K plays', videoId: 'vS3', moods: ['eerie', 'sad'] },
                 { title: 'S4', plays: '5M plays', videoId: 'vS4' }],
    'm-hero': [{ title: 'H1', plays: '3M plays', videoId: 'vH1', moods: ['heroic', 'epic'] },
               { title: 'H2', plays: '1M plays', videoId: 'vH2', moods: ['heroic', 'suspenseful'] },
               { title: 'H3', plays: '4M plays', videoId: 'vH3', moods: ['epic'], song: true }],
    // eerie is on a track here but not in the album's top three
    'm-calm': [{ title: 'C1', plays: '20K plays', videoId: 'vC1', moods: ['peaceful', 'tender'] },
               { title: 'C2', plays: '9K plays', videoId: 'vC2', moods: ['peaceful', 'nostalgic'] },
               { title: 'C3', plays: '1K plays', videoId: 'vC3', moods: ['eerie'] }],
    'm-untagged': [{ title: 'U1', plays: '8K plays', videoId: 'vU1' }, { title: 'U2', plays: '1K plays', videoId: 'vU2' }],
    'm-bare': [{ title: 'B1', plays: '10 plays', videoId: 'vB1' }],
  };
  const mdHits = {};
  const md = makeDom(async (url) => {
    mdHits[url] = (mdHits[url] || 0) + 1;
    if (url === 'data/releases.json') return { ok: true, status: 200, json: async () => ({ updatedAt: '2026-09-01T10:00:00Z', releases: MD_ROWS }) };
    const m = /^data\/tracks\/(.+)\.json$/.exec(url);
    const list = m && MD_TRACKS[decodeURIComponent(m[1])];
    return list ? { ok: true, status: 200, json: async () => JSON.parse(JSON.stringify(list)) } : { ok: false, status: 404, json: async () => ({}) };
  }, { v: 3, entries: { 'm-silent': { status: 'listened', listenedOn: '2026-08-01', likedTracks: ['S4', 'S2'] } }, lastSeen: T('2026-08-20T00:00:00Z') });
  await sleep(120);
  const mq = (sel) => md.d.querySelector(sel);
  const mdStored = () => JSON.parse(md.w.localStorage.getItem('vgm-v1'));
  const mStats = (o) => JSON.parse(md.w.eval(`JSON.stringify(recipeStats(${rules(o)}))`));
  const mPool = (o) => { const s = mStats(o); return s.tracks + '/' + s.albums; };
  const mTitles = (o) => JSON.parse(md.w.eval(`JSON.stringify(recipeBuild(${rules(o)}, 1).map(t => t.title))`));
  const mBuild = async (o) => { await md.w.eval(`recipeLoad(${rules(o)}, 1)`); return mTitles(o); };
  const mLine = (o) => md.w.eval(`recipeCountLine(recipeStats(${rules(o)}), ${rules(o)})`);
  assert(md.errors.length === 0, 'the mood fixture boots clean');
  assert(md.w.eval(`JSON.stringify(MOODS)`) === JSON.stringify(JSON.parse(fs.readFileSync('collector/moods.json', 'utf8')).moods.map(m => m.mood)),
    'the app\'s mood list is the collector\'s vocabulary, in its order');

  // counting before any tracklist is read: albums join on their top three, tracks come from moodsN
  assert(mPool({ moods: ['eerie'] }) === '3/1' && Object.keys(mdHits).length === 1, 'one mood counts from the row, no tracklist fetched');
  assert(mPool({ moods: ['suspenseful'] }) === '3/2' && mPool({ moods: ['suspenseful'], medium: 'film' }) === '1/1', 'a mood ANDs with the medium');
  assert(mPool({ moods: ['nostalgic'] }) === '1/1' && mPool({ moods: ['dreamy'] }) === '0/0', 'a mood no album carries empties the pool');
  assert(mLine({ moods: ['eerie', 'heroic'] }) === 'at least 5 tracks from 2 albums' && mLine({ moods: ['eerie'] }) === '3 tracks from 1 album',
    'several moods on unread albums count a floor and say so; one mood is exact');
  assert(mLine({ moods: ['eerie', 'heroic'], pick: 'top', topN: 1 }) === '2 tracks from 2 albums', 'a full top pick is exact even with several moods');

  // building: OR within moods, the untagged track stays out, the top three decide which albums join
  assert(same(await mBuild({ moods: ['eerie'] }), ['S2', 'S1', 'S3']), 'a partly tagged album gives only its tagged tracks, most played first');
  assert(same(await mBuild({ moods: ['eerie', 'heroic'], pick: 'top', topN: 1 }), ['H1', 'S2']), 'top 1 per album picks among the mood\'s tracks');
  assert(same(await mBuild({ moods: ['eerie', 'heroic'] }), ['H1', 'S2', 'H2', 'S1', 'S3']), 'several moods: any of them, across albums, a plays tie kept in album order');
  assert(mLine({ moods: ['eerie', 'heroic'] }) === '5 tracks from 2 albums' && mPool({ moods: ['eerie', 'suspenseful'] }) === '4/2',
    'once read, the count is exact and a track with two chosen moods counts once');
  assert(!mTitles({ moods: ['eerie'] }).includes('C3'), 'eerie outside an album\'s top three does not bring that album in');
  assert(same(await mBuild({ moods: ['epic'], scores: true }), ['H1']) && same(await mBuild({ moods: ['epic'] }), ['H3', 'H1']),
    'scores only still drops a song that carries the mood');
  assert(same(await mBuild({ moods: ['eerie'], pick: 'hearted' }), ['S2']), 'a hearted track without the mood stays out of a ♥ pick');
  assert(mPool({}) === '13/5' && same(await mBuild({ medium: 'game', order: 'album' }), ['B1', 'U1', 'U2', 'S1', 'S2', 'S3', 'S4']),
    'no moods chosen: untagged albums and tracks are in, as before');

  // names and backups
  const mName = (o) => md.w.eval(`recipeAutoName(${rules(o)})`);
  assert(mName({ moods: ['eerie'] }) === 'eerie soundtracks' && mName({ moods: ['suspenseful', 'sad', 'eerie'], medium: 'film', rating: '4' }) === '4★+ suspenseful, sad or eerie film scores',
    'the chosen moods read out in the name');
  assert(md.w.eval(`applyImport('{"v":3,"entries":{},"recipes":[{"id":"mx","moods":["eerie","bogus","tense","eerie"]},{"id":"my","moods":"eerie"},{"id":"mz","moods":["mournful","powerful"]}]}')`) === true
    && same(mdStored().recipes.map(r => r.moods), [['suspenseful', 'ominous', 'intense', 'eerie'], [], ['sad', 'epic']]),
    'import reads an old tense as its three new moods, mournful as sad, powerful as epic, in vocabulary order, and drops the rest');
  md.w.eval(`applyImport('{"v":3,"entries":{"m-silent":{"status":"listened","listenedOn":"2026-08-01","likedTracks":["S4","S2"]}}}')`);

  // the sheet: a mood row, a picker that toggles several, the count following
  md.w.eval(`setView('library')`); mq('#libpl').click(); await sleep(60);
  mq('#rcpnew').click(); await sleep(10);
  assert(mq('#sheetwrap #rc-mood .shl').textContent === 'any', 'the recipe sheet has a mood row, any by default');
  mq('#sheetwrap #rc-mood').click(); await sleep(10);
  const mPick = (m) => mq(`#sheetwrap [data-shrm="${m}"]`);
  assert(mPick('eerie') !== null && md.d.querySelectorAll('#sheetwrap [data-shrm]').length === 21 && mq('#sheetwrap #sheet').classList.contains('tall'),
    'the mood picker lists any plus the twenty moods');
  assert(mPick('suspenseful').querySelector('.shr').textContent === '2' && mPick('dreamy').querySelector('.shr').textContent === '0',
    'each mood shows how many albums have it in their top three');
  mPick('heroic').click(); await sleep(10);
  mPick('eerie').click(); await sleep(10);
  assert(mq('#sheetwrap [data-shrm="heroic"] .shr').textContent === '1 ✓' && mq('#sheetwrap [data-shrm="eerie"] .shr').textContent === '1 ✓'
    && mq('#sheetwrap [data-shrm="any"] .shr').textContent === '' && mq('#sheetwrap #rcount').textContent === '5 tracks from 2 albums',
    'picks toggle in place, several at once, with the count shown');
  mPick('heroic').click(); await sleep(10);
  assert(mq('#sheetwrap [data-shrm="heroic"] .shr').textContent === '1' && mq('#sheetwrap #rcount').textContent === '3 tracks from 1 album', 'a second tap takes a mood off');
  mPick('heroic').click(); await sleep(10);
  md.w.dispatchEvent(new md.w.KeyboardEvent('keydown', { key: 'Escape' }));
  assert(mq('#sheetwrap #rc-mood .shl').textContent === 'eerie, heroic' && mq('#sheetwrap #rc-name').placeholder === 'eerie or heroic soundtracks',
    'escape returns to the recipe, which names the picks');
  mq('#sheetwrap #rc-save').click(); await sleep(120);
  assert(same(mdStored().recipes[0].moods, ['eerie', 'heroic']), 'the saved recipe carries its moods');

  // chips: the expanded row and the album page, each opening the feed on that mood
  md.w.eval(`setView('feed')`); await sleep(10);
  const newBadge = () => (mq('#tabbar .nb') || { textContent: '' }).textContent;
  const badge0 = newBadge();
  const feedIds = () => [...md.d.querySelectorAll('#list .row')].map(x => x.dataset.id);
  const qIn = mq('#q'); qIn.value = 'silent'; qIn.dispatchEvent(new md.w.Event('input', { bubbles: true }));
  assert(same(feedIds(), ['m-silent']), 'a search narrows the feed first');
  mq('#list .row[data-id="m-silent"]').click(); await sleep(60);
  const chips = [...md.d.querySelectorAll('#list .row[data-id="m-silent"] .mchip')].map(x => x.textContent);
  assert(same(chips, ['eerie', 'suspenseful', 'sad']), 'the expanded row shows the album\'s three moods');
  assert(mq('#list .row[data-id="m-untagged"]') === null || !mq('#list .row[data-id="m-untagged"] .mchip'), 'an untagged album shows no mood chips');
  mq('#list .row[data-id="m-silent"] .mchip[data-mood="suspenseful"]').click(); await sleep(10);
  assert(mq('#moodbar .mlabel').textContent === 'MOOD · SUSPENSEFUL' && mq('#moodbar .mn').textContent === '2 albums'
    && same(feedIds().sort(), ['m-hero', 'm-silent']) && md.w.eval('Q') === '' && mq('#q').value === '',
    'a chip opens the feed on that mood and clears the search');
  assert(newBadge() === badge0 && mq('#c-filters').textContent === 'filters', 'the NEW badge and the filters chip ignore the mood');
  assert(mdStored().feedMood === undefined, 'the mood is not saved: it lasts the session, like a search');
  mq('#moodclear').click(); await sleep(10);
  assert(mq('#moodbar') === null && feedIds().length === 5, 'clear brings the whole feed back');
  md.w.eval(`openAlbum('m-hero')`); await sleep(60);
  assert(same([...md.d.querySelectorAll('#album .amoods .mchip')].map(x => x.textContent), ['epic', 'heroic', 'suspenseful']), 'the album page shows the moods');
  mq('#album .mchip[data-mood="epic"]').click(); await sleep(10);
  assert(mq('#album') === null && mq('#moodbar .mlabel').textContent === 'MOOD · EPIC' && same(feedIds(), ['m-hero']),
    'a chip on the album page closes it and opens the feed on that mood');
  md.w.eval(`setFeedMedium('tv')`);
  assert(mq('#moodbar .mn').textContent === '0 albums' && mq('#list .state .big').textContent === 'NO MATCHES' && mq('#moodclear') !== null,
    'the mood ANDs with the feed filters and an empty result keeps the way out');
  md.w.eval(`setFeedMedium('all'); clearFeedMood()`);
  md.w.eval(`setView('library'); setLibView('albums')`); await sleep(10);
  md.w.eval(`EXPANDED = null; toggleExpand('m-silent')`); await sleep(60);
  mq('#list .row[data-id="m-silent"] .mchip[data-mood="sad"]').click(); await sleep(10);
  assert(mdStored().view === 'feed' && same(feedIds(), ['m-silent']), 'a chip in the library opens the feed');
  assert(md.errors.length === 0, 'the mood flow stays clean');

  // ---------- genres: one vocabulary across mediums, Anime, game themes, an all-mediums pick ----------
  const gnRow = (id, medium, game, extra) => Object.assign({ id, title: game + ' Soundtrack', medium, game, composers: [], date: '2024-01-01',
    sources: [{ name: 'x', type: 'catalog', url: 'https://x/' + id, seenAt: '2026-08-25T10:00:00Z' }],
    ytmSearchUrl: 'https://music.youtube.com/search?q=' + id, notable: true, ytmAlbumUrl: null, art: null, tracksN: 1 }, extra);
  const GN_ROWS = [
    gnRow('film-arrival', 'film', 'Arrival', { genres: ['Drama', 'Science Fiction', 'Mystery'] }),
    gnRow('tv-expanse', 'tv', 'The Expanse', { genres: ['Sci-Fi & Fantasy', 'Drama'] }),
    gnRow('tv-band', 'tv', 'Band of Brothers', { genres: ['War & Politics', 'Action & Adventure', 'Drama'] }),
    gnRow('film-hereditary', 'film', 'Hereditary', { genres: ['Horror', 'Mystery', 'Thriller'] }),
    gnRow('film-totoro', 'film', 'My Neighbor Totoro', { genres: ['Fantasy', 'Animation', 'Family', 'Anime'] }),
    gnRow('dead-space', 'game', 'Dead Space', { genres: ['Shooter'], themes: ['Action', 'Horror', 'Science fiction'] }),
    gnRow('valiant', 'game', 'Valiant Hearts', { genres: ['Adventure', 'Puzzle'], themes: ['Historical', 'Warfare'] }),
    gnRow('no-themes', 'game', 'Plain Game', { genres: ['Platform'] }),
  ];
  const gn = makeDom(okFetch({ updatedAt: '2026-09-01T10:00:00Z', releases: GN_ROWS }),
    { v: 3, entries: {}, lastSeen: T('2026-08-20T00:00:00Z'), feedMedium: 'screen',
      feedGenre: { game: 'all', screen: 'Sci-Fi & Fantasy' },   // a pick saved before the vocabulary joined up
      recipes: [{ id: 'old', medium: 'tv', genre: { game: 'all', screen: 'War & Politics' } }] });
  await sleep(120);
  const gq = (sel) => gn.d.querySelector(sel);
  const gIds = () => [...gn.d.querySelectorAll('#list .row')].map(x => x.dataset.id).sort();
  const gState = () => JSON.parse(gn.w.localStorage.getItem('vgm-v1'));
  const gOf = (id) => JSON.parse(gn.w.eval(`JSON.stringify(genresOf(byId('${id}')))`));
  assert(gn.errors.length === 0, 'the genre fixture boots clean');
  assert(same(gOf('tv-expanse'), ['Science Fiction', 'Fantasy', 'Drama'])
    && same(gOf('tv-band'), ['War', 'Politics', 'Action', 'Adventure', 'Drama']),
    'TV\'s paired genres read as the film names');
  assert(same(gOf('dead-space'), ['Shooter', 'Action', 'Horror', 'Science Fiction']) && same(gOf('valiant'), ['Adventure', 'Puzzle', 'History', 'War'])
    && same(gOf('no-themes'), ['Platform']), 'a game\'s IGDB themes join its genres under the shared names');
  assert(gState().feedGenre.screen === 'Science Fiction' && same(gIds(), ['film-arrival', 'tv-expanse']),
    'a saved "Sci-Fi & Fantasy" pick carries over as Science Fiction and now reaches both the film and the show');
  assert(gState().recipes[0].genre.screen === 'War', 'a recipe\'s old TV pick carries over too');
  const screenList = JSON.parse(gn.w.eval(`JSON.stringify(genreCounts('screen', 'all').map(x => x[0]))`));
  assert(screenList.includes('Anime') && screenList.includes('Science Fiction') && !screenList.includes('Sci-Fi & Fantasy')
    && !screenList.includes('Shooter'), 'the film + tv list is one vocabulary, Anime included, no game genres');
  gn.w.eval(`setFeedGenre('screen', 'Anime')`);
  assert(same(gIds(), ['film-totoro']), 'Anime filters film and TV');
  gn.w.eval(`setFeedMedium('game')`);
  const gameList = JSON.parse(gn.w.eval(`JSON.stringify(genreCounts('game', 'all').map(x => x[0]))`));
  assert(gameList.includes('Horror') && gameList.includes('Shooter') && gameList.includes('History'), 'the games list carries themes beside genres');
  gn.w.eval(`setFeedGenre('game', 'Horror')`);
  assert(same(gIds(), ['dead-space']), 'a theme filters games');

  // one genre across every medium
  gn.w.eval(`setFeedMedium('all')`);
  assert(same(gIds().length, 8), 'under all mediums the game and screen picks stay inert');
  gq('#c-filters').click(); await sleep(10);
  gq('#sheetwrap #shgenrerow').click(); await sleep(10);
  const allPick = (g) => gq(`#sheetwrap [data-shgenre="${g}"]`);
  assert(allPick('Horror') !== null && allPick('Horror').querySelector('.shr').textContent === '2'
    && allPick('War').querySelector('.shr').textContent === '2', 'the all-mediums list counts across games, films and shows');
  allPick('Horror').click(); await sleep(10);
  assert(gState().feedGenre.all === 'Horror' && same(gIds(), ['dead-space', 'film-hereditary']),
    'Horror under all mediums: the horror game and the horror film together');
  gq('#sheetwrap #shdone').click(); await sleep(10);
  assert(gq('#c-filters').textContent === 'filters · horror', 'the filters chip names the all-mediums genre');
  gn.w.eval(`clearFeedFilters()`);
  assert(gState().feedGenre.all === 'all' && gIds().length === 8, 'clear resets it');
  const gPool = (o) => { const s = JSON.parse(gn.w.eval(`JSON.stringify(recipeStats(Object.assign(recipeBlank(), ${JSON.stringify(o)})))`)); return s.albums; };
  assert(gPool({ medium: 'all', genre: { game: 'all', screen: 'all', all: 'War' } }) === 2
    && gPool({ medium: 'screen', genre: { game: 'all', screen: 'Science Fiction', all: 'all' } }) === 2,
    'recipes take the all-mediums genre and the joined film + tv names');
  assert(gn.w.eval(`recipeAutoName(Object.assign(recipeBlank(), { genre: { game: 'all', screen: 'all', all: 'Horror' } }))`) === 'horror soundtracks',
    'an all-mediums genre reads out in a recipe name');
  assert(gn.errors.length === 0, 'the genre flow stays clean');

  console.log(process.exitCode ? '\nSUITE FAILED' : '\nall green');
})();
