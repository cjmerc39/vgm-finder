const { JSDOM } = require('jsdom');
const fs = require('fs');
const html = fs.readFileSync('index.html', 'utf8');

const T = (n) => Date.parse(n); // shorthand: ISO -> ms
const LAST_VISIT = T('2026-07-25T00:00:00Z');

const FIXTURE = {
  updatedAt: '2026-07-28T10:00:00Z',
  releases: [
    { id: 'chrono-cross-the-radical-dreamers-edition', title: 'Chrono Cross: The Radical Dreamers Edition OST',
      game: 'Chrono Cross', composers: ['Yasunori Mitsuda'], date: '2026-06-01',
      sources: [{ name: 'vgmo', type: 'editorial', url: 'https://vgmonline.net/a', seenAt: '2026-07-01T10:00:00Z' }],
      ytmSearchUrl: 'https://music.youtube.com/search?q=Chrono+Cross%3A+The+Radical+Dreamers+Edition+OST+soundtrack',
      ytmAlbumUrl: null, art: null, notable: true },
    { id: 'hades-ii', title: 'Hades II Original Soundtrack', game: 'Hades II', composers: ['Darren Korb'], date: '2026-07-20',
      sources: [{ name: 'nowplaying', type: 'editorial', url: 'https://nowplaying.cool/h', seenAt: '2026-07-10T10:00:00Z' },
                { name: 'r/gamemusic', type: 'community', url: 'https://reddit.com/h', seenAt: '2026-07-11T10:00:00Z' }],
      ytmSearchUrl: 'https://music.youtube.com/search?q=Hades+II+Original+Soundtrack+soundtrack',
      ytmAlbumUrl: 'https://music.youtube.com/playlist?list=OLAK5uy_hades2', art: null, notable: true },
    { id: 'ratchet-clank-rift-apart', title: 'Ratchet & Clank: Rift Apart OST', game: null, composers: [], date: '2026-07-18',
      sources: [{ name: 'blipblop', type: 'editorial', url: 'https://blipblop.net/r', seenAt: '2026-07-12T10:00:00Z' }],
      ytmSearchUrl: 'https://music.youtube.com/search?q=Ratchet+%26+Clank%3A+Rift+Apart+OST+soundtrack',
      ytmAlbumUrl: null, art: null, notable: true },
    { id: 'ゼルダの伝説', title: 'ゼルダの伝説 ティアーズ オブ ザ キングダム OST', game: null, composers: [], date: '2026-07-15',
      sources: [{ name: 'vgmo', type: 'editorial', url: 'https://vgmonline.net/z', seenAt: '2026-07-13T10:00:00Z' }],
      ytmSearchUrl: 'https://music.youtube.com/search?q=%E3%82%BC%E3%83%AB%E3%83%80%E3%81%AE%E4%BC%9D%E8%AA%AC+OST+soundtrack',
      ytmAlbumUrl: null, art: null, notable: true },
    { id: 'evil', title: '<img src=x onerror="window.__pwned=1">Evil OST', game: null, composers: [], date: '2026-07-10',
      sources: [{ name: 'r/gamemusic', type: 'community', url: 'https://reddit.com/e', seenAt: '2026-07-14T10:00:00Z' }],
      ytmSearchUrl: 'https://music.youtube.com/search?q=Evil+OST+soundtrack',
      ytmAlbumUrl: null, art: null, notable: true },
    { id: 'fresh-drop', title: 'Fresh Drop: A Brand New Soundtrack', game: 'Fresh Drop', composers: ['New Person'], date: '2026-07-28',
      sources: [{ name: 'nowplaying', type: 'editorial', url: 'https://nowplaying.cool/f', seenAt: '2026-07-27T09:00:00Z' }],
      ytmSearchUrl: 'https://music.youtube.com/search?q=Fresh+Drop%3A+A+Brand+New+Soundtrack+soundtrack',
      ytmAlbumUrl: null, art: null, notable: true },
  ],
};

function makeDom(fetchImpl, prefill) {
  const errors = [];
  const dom = new JSDOM(html, {
    runScripts: 'dangerously', url: 'https://example.com/',
    beforeParse(w) {
      w.fetch = fetchImpl;
      w.open = (url) => { w.__opened = url; };
      if (prefill) w.localStorage.setItem('vgm-v1', JSON.stringify(prefill));
    },
  });
  dom.window.addEventListener('error', e => errors.push(e.message));
  return { w: dom.window, d: dom.window.document, errors };
}
const okFetch = (data) => async () => ({ ok: true, status: 200, json: async () => data });
const sleep = ms => new Promise(r => setTimeout(r, ms));

const { w, d, errors } = makeDom(okFetch(FIXTURE),
  { v: 1, starred: {}, listened: {}, hidden: {}, lastSeen: LAST_VISIT, filter: 'all', showHidden: false });

(async () => {
  await sleep(120);
  const assert = (c, m) => { if (!c) { console.error('FAIL:', m); process.exitCode = 1; } else console.log('ok  :', m); };
  const rows = () => [...d.querySelectorAll('#list .row:not(.ghost)')];
  const rowById = (id) => d.querySelector(`#list .row[data-id="${id}"]`);

  assert(errors.length === 0, 'no runtime errors on boot' + (errors.length ? ' -> ' + errors.join(' | ') : ''));
  assert(rows().length === 6, 'renders all 6 releases');

  // newest first by date, but TRACK numbers pin to append-only position
  assert(rows()[0].dataset.id === 'fresh-drop', 'newest release renders first');
  assert(rows()[0].querySelector('.tno').textContent === 'TRACK 006', 'newest row keeps its catalog number (006)');
  assert(rows()[5].dataset.id === 'chrono-cross-the-radical-dreamers-edition', 'oldest release renders last');
  assert(rows()[5].querySelector('.tno').textContent === 'TRACK 001', 'first-collected row is TRACK 001');
  assert(rows()[0].querySelector('time').textContent === 'JUL 28', 'current-year dates render without the year');

  // new-since-last-visit badging
  assert(d.querySelectorAll('#list .new').length === 1, 'exactly one row is NEW vs the 07-25 visit');
  assert(rowById('fresh-drop').querySelector('.new') !== null, 'the NEW badge sits on the fresh row');
  assert(w.eval('S.lastSeen') > LAST_VISIT, 'visit timestamp advanced after load');
  assert(JSON.parse(w.localStorage.getItem('vgm-v1')).lastSeen === w.eval('S.lastSeen'), 'advanced timestamp persisted');

  // feed data is escaped, never parsed as markup
  assert(d.querySelector('#list img') === null, 'hostile title injects no element');
  assert(w.__pwned === undefined, 'onerror payload never ran');
  assert(rowById('evil').querySelector('.rtitle').textContent.includes('Evil OST'), 'hostile title still shown as text');

  // sub line and chips
  assert(rowById('hades-ii').textContent.includes('Hades II · Darren Korb'), 'game and composer render on the sub line');
  assert(rowById('hades-ii').querySelectorAll('.chip').length === 2, 'both sources get chips');
  assert(rowById('hades-ii').querySelector('.chip.community') !== null, 'community source chip is badged');
  assert(rowById('ratchet-clank-rift-apart').querySelector('.chip.community') === null, 'editorial chip is not');

  // tap-through: search URL by default, album URL when resolved
  rowById('ratchet-clank-rift-apart').click();
  assert(w.__opened === 'https://music.youtube.com/search?q=Ratchet+%26+Clank%3A+Rift+Apart+OST+soundtrack',
    'row tap opens the encoded YTM search URL untouched');
  rowById('hades-ii').click();
  assert(w.__opened === 'https://music.youtube.com/playlist?list=OLAK5uy_hades2', 'album URL preferred over search when present');
  rowById('ゼルダの伝説').click();
  assert(w.__opened.startsWith('https://music.youtube.com/search?q=%E3%82%BC'), 'Japanese title URL passes through encoded');

  // star: toggles, persists, does not open the row
  w.__opened = null;
  rowById('hades-ii').querySelector('[data-act="star"]').click();
  assert(w.__opened === null, 'starring does not open YTM');
  assert(rowById('hades-ii').querySelector('.star').getAttribute('aria-pressed') === 'true', 'star toggles on');
  assert(JSON.parse(w.localStorage.getItem('vgm-v1')).starred['hades-ii'] === true, 'star round-trips through localStorage');

  // listened: play-state glyph + dim
  rowById('fresh-drop').querySelector('[data-act="heard"]').click();
  assert(rowById('fresh-drop').classList.contains('heard'), 'listened row dims');
  assert(rowById('fresh-drop').querySelector('.heard').textContent === '▶', 'glyph flips to played');
  assert(JSON.parse(w.localStorage.getItem('vgm-v1')).listened['fresh-drop'] === true, 'listened persists');

  // filter chips (with counts)
  const chip = f => d.querySelector(`#chips button[data-f="${f}"]`);
  assert(chip('all').textContent.startsWith('all6'), 'ALL chip counts 6');
  assert(chip('unlistened').textContent.startsWith('unlistened5'), 'UNLISTENED counts 5 after one listen');
  chip('unlistened').click();
  assert(rows().length === 5 && rowById('fresh-drop') === null, 'unlistened filter drops the heard row');
  chip('starred').click();
  assert(rows().length === 1 && rows()[0].dataset.id === 'hades-ii', 'starred filter shows only the starred row');
  assert(JSON.parse(w.localStorage.getItem('vgm-v1')).filter === 'starred', 'active filter persists');
  chip('all').click();
  assert(rows().length === 6, 'ALL restores everything');

  // search across title, game, composers
  const q = d.getElementById('q');
  const type = (s) => { q.value = s; q.dispatchEvent(new w.Event('input', { bubbles: true })); };
  type('ゼルダ');
  assert(rows().length === 1 && rows()[0].dataset.id === 'ゼルダの伝説', 'search matches Japanese titles');
  type('mitsuda');
  assert(rows().length === 1 && rows()[0].dataset.id === 'chrono-cross-the-radical-dreamers-edition', 'search matches composers');
  type('fresh drop');
  assert(rows().length === 1, 'search matches game names');
  type('zzzz');
  assert(rows().length === 0 && d.querySelector('#list .state').textContent.includes('zzzz'), 'no-match state names the query');
  type('');
  assert(rows().length === 6, 'clearing search restores the list');

  // hide -> footer -> show -> restore
  rowById('evil').querySelector('[data-act="hide"]').click();
  assert(rowById('evil') === null, 'hidden row leaves the list');
  assert(d.getElementById('hidtoggle').textContent.includes('1 hidden'), 'footer counts hidden rows');
  d.getElementById('hidtoggle').click();
  assert(d.querySelector('#hidhead') !== null && d.querySelector('#list .row.ghost[data-id="evil"]') !== null,
    'show reveals the hidden section');
  d.querySelector('.row.ghost [data-act="restore"]').click();
  assert(rowById('evil') !== null, 'restore brings the row back');
  assert(JSON.parse(w.localStorage.getItem('vgm-v1')).hidden.evil === undefined, 'restore clears the persisted flag');

  // header sync line
  assert(d.getElementById('sync').textContent === 'synced jul 28', 'header shows the collector sync date');

  // ---------- separate DOMs: empty data, fetch failure, first visit ----------
  const empty = makeDom(okFetch({ updatedAt: null, releases: [] }));
  await sleep(60);
  assert(empty.d.querySelector('#list .state').textContent.includes('NO TRACKS YET'), 'empty data explains the morning collector');

  const broken = makeDom(async () => ({ ok: false, status: 404, json: async () => ({}) }));
  await sleep(60);
  const errText = broken.d.querySelector('#list .state').textContent;
  assert(errText.includes('READ ERROR') && errText.includes('HTTP 404'), 'fetch failure states the status, no apology');

  const first = makeDom(okFetch(FIXTURE)); // no prefill: a brand-new visitor
  await sleep(60);
  assert(first.d.querySelectorAll('#list .new').length === 0, 'first-ever visit badges nothing as NEW');

  console.log(process.exitCode ? '\nSUITE FAILED' : '\nall green');
})();
