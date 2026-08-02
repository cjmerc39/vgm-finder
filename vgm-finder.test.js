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

  // ---------- genre facet + random listen ----------
  assert(d.querySelector('#fgenre') !== null, 'genre select renders when genre data exists');
  d.querySelector('#fgenre').value = 'Platform';
  d.querySelector('#fgenre').dispatchEvent(new w.Event('change', { bubbles: true }));
  await sleep(20);
  assert(rows().length === 1 && rows()[0].dataset.id === 'fresh-drop', 'genre facet filters the feed');
  assert(stored().feedGenre === 'Platform', 'genre choice persists');
  d.querySelector('#fgenre').value = 'all';
  d.querySelector('#fgenre').dispatchEvent(new w.Event('change', { bubbles: true }));
  await sleep(20);
  assert(rows().length === 5, 'genre back to all');
  w.__opened = null;
  w.eval('Math.random = () => 0');
  d.querySelector('#frandom').click();
  assert(rowById('fresh-drop').getAttribute('aria-expanded') === 'true' && w.__opened === null,
    'random expands a pick in-app instead of leaving the app');
  rowById('fresh-drop').click();

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
  assert(d.querySelector('#subctl button[data-ls]') === null, 'sort chips step aside in songs view');
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
  assert(d.querySelectorAll('#list .plcard').length === 3, 'three recipe cards render');
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
  assert(exp1.app === 'vgm-finder-playlist' && exp1.name === 'vgm-finder · Liked Songs', 'export carries the playlist name');
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
  d.querySelector('#plgenre').value = 'Role-playing (RPG)';
  d.querySelector('#plgenre').dispatchEvent(new w.Event('change', { bubbles: true })); await sleep(20);
  assert(cardMeta('queue').startsWith('5 tracks'), 'genre facet keeps only tagged releases');
  assert(plCard().querySelector('.plname').textContent.includes('— Role-playing (RPG)'),
    'facet variants get their own playlist name');
  assert(stored().plGenre === 'Role-playing (RPG)', 'facet choice persists');
  d.querySelector('#plgenre').value = 'all';
  d.querySelector('#plgenre').dispatchEvent(new w.Event('change', { bubbles: true })); await sleep(20);
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
  assert(sent.event_type === 'publish' && sent.client_payload.playlist.app === 'vgm-finder-playlist'
    && sent.client_payload.playlist.name === 'vgm-finder · Liked Songs'
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
    && d.querySelectorAll('#list .plcard').length === 3, 'library shows the custom section, empty at first');
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
  assert(d.querySelectorAll('#list .plcard').length === 5, 'custom cards join the recipe cards');
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
