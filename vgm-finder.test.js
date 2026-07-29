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
      company: 'Supergiant Games', console: true,
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
      company: 'Nintendo', console: true,
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

  assert(errors.length === 0, 'no runtime errors on boot' + (errors.length ? ' -> ' + errors.join(' | ') : ''));

  // ---------- legacy migration ----------
  assert(stored().v === 2, 'v1 state migrated to v2 and persisted');
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

  // ---------- album-name labels ----------
  assert(rowById('chrono-cross-the-radical-dreamers-edition').querySelector('.rtitle').textContent
    === 'Chrono Cross: The Radical Dreamers Edition (Original Soundtrack)',
    'rows label by resolved album name');
  assert(rowById('fresh-drop').querySelector('.rtitle').textContent.startsWith('Fresh Drop'),
    'rows without a resolved album keep their title');

  // ---------- feed sort control ----------
  assert(d.querySelectorAll('#subctl button[data-fs]').length === 4, 'feed offers four sorts');
  d.querySelector('#subctl button[data-fs="oldest"]').click(); await sleep(20);
  assert(rows()[0].dataset.id === 'chrono-cross-the-radical-dreamers-edition', 'oldest-first surfaces the back catalog');
  assert(stored().feedSort === 'oldest', 'feed sort persists');
  d.querySelector('#subctl button[data-fs="az"]').click(); await sleep(20);
  assert(JSON.stringify(rows().map(r => r.dataset.id)) === JSON.stringify(
    ['chrono-cross-the-radical-dreamers-edition', 'fresh-drop', 'hades-ii', 'ratchet-clank-rift-apart', 'ゼルダの伝説']),
    'a–z sorts by the display label');
  d.querySelector('#subctl button[data-fs="added"]').click(); await sleep(20);
  assert(rows()[0].dataset.id === 'fresh-drop', 'recently-added sort leads with the newest find');
  d.querySelector('#subctl button[data-fs="date"]').click(); await sleep(20);
  assert(rows()[0].dataset.id === 'fresh-drop', 'newest-first restored');

  // ---------- year rails + company facets ----------
  assert(d.querySelectorAll('#list .yhead').length === 1
    && d.querySelector('#list .yhead').textContent === '2026', 'date sorts group rows under year rails');
  assert(d.querySelectorAll('#subctl button[data-fc]').length === 3, 'company facet chips render');
  d.querySelector('#subctl button[data-fc="big"]').click(); await sleep(20);
  assert(rows().length === 1 && rows()[0].dataset.id === 'fresh-drop', 'big-studios facet keeps the Nintendo row');
  d.querySelector('#subctl button[data-fc="indie"]').click(); await sleep(20);
  assert(rows().length === 1 && rows()[0].dataset.id === 'hades-ii', 'indie facet keeps the Supergiant row');
  assert(stored().feedCo === 'indie', 'company facet persists');
  d.querySelector('#subctl button[data-fc="all"]').click(); await sleep(20);
  assert(rows().length === 5, 'all restores the unfaceted feed');
  d.querySelector('#fconsole').click(); await sleep(20);
  assert(rows().length === 4 && rowById('ゼルダの伝説') === null,
    'console filter keeps confirmed console games, drops PC-only and unknown');
  assert(stored().feedConsole === true, 'console filter persists');
  d.querySelector('#fconsole').click(); await sleep(20);
  assert(rows().length === 5, 'console filter toggles back off');

  // ---------- expand, then listen ----------
  rowById('ratchet-clank-rift-apart').click();
  assert(rowById('ratchet-clank-rift-apart').getAttribute('aria-expanded') === 'true'
    && rowById('ratchet-clank-rift-apart').querySelector('.rx') !== null, 'row tap expands the detail panel');
  assert(w.__opened === undefined, 'expanding does not open YTM');
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
  assert(w.__opened === 'https://music.youtube.com/watch?v=vidNE', 'tracks with videoIds link straight to the song');
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
  d.querySelector('#subctl button[data-ls="rating"]').click(); await sleep(20);
  assert(rows()[0].dataset.id === 'fresh-drop' && rows()[1].dataset.id === 'ratchet-clank-rift-apart',
    'rating sort: 5 before 3.5');
  assert(rows()[2].dataset.id === 'chrono-cross-the-radical-dreamers-edition', 'unrated sorts last on rating sort');
  assert(rowById('fresh-drop').querySelector('.minis').textContent === '★★★★★', 'five stars render');
  assert(rowById('ratchet-clank-rift-apart').querySelector('.minis').textContent === '★★★½', 'half star renders as ½');
  d.querySelector('#subctl button[data-ls="date"]').click(); await sleep(20);
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
  type('');

  // ---------- export / import round-trip ----------
  const dump = S('JSON.stringify(buildExport())');
  const parsedDump = JSON.parse(dump);
  assert(parsedDump.app === 'vgm-finder' && parsedDump.state.v === 2, 'export wraps the v2 state');
  S(`editEntry('ratchet-clank-rift-apart', e => { e.note = 'clobbered'; e.rating = 1; })`);
  assert(S(`applyImport(${JSON.stringify(dump)})`) === true, 'import accepts its own export');
  assert(stored().entries['ratchet-clank-rift-apart'].note.includes('slaps') &&
         stored().entries['ratchet-clank-rift-apart'].rating === 3.5, 'import restores the exported state');
  assert(S(`applyImport('{"nope":true}')`) === false, 'import rejects foreign JSON');
  assert(S(`applyImport('not json')`) === false, 'import rejects non-JSON');
  const legacy = JSON.stringify({ v: 1, starred: { 'hades-ii': true }, listened: {}, hidden: {}, lastSeen: 5 });
  assert(S(`applyImport(${JSON.stringify(legacy)})`) === true && stored().v === 2 &&
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

  console.log(process.exitCode ? '\nSUITE FAILED' : '\nall green');
})();
