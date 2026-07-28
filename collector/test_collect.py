"""Collector tests. Fixtures are verbatim copies of real source responses
captured 2026-07-28; counts below are locked to those files."""
import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import collect

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 7, 28, 10, 0, 0, tzinfo=timezone.utc)
SEEN = "2026-07-28T10:00:00Z"

FEED_FILES = {
    "https://nowplaying.cool/rss/": "nowplaying-feed.xml",
    "https://blipblop.net/feed/": "blipblop-feed.xml",
    "https://www.vgmonline.net/feed/": "vgmo-feed.xml",
    collect.IGDB_URL: "igdb-games.json",
}
STEAM_URL = next(s["url"] for s in collect.SOURCES if s["name"] == "steam")
FEED_FILES[STEAM_URL] = "steam-soundtracks.json"

YTM_FIX = json.loads((FIXTURES / "ytm-search.json").read_text(encoding="utf-8"))
_BY_NORM = {collect.normalize_title(q): res for q, res in YTM_FIX.items()}


def fake_resolve(query):
    return _BY_NORM.get(collect.normalize_title(query), [])


def no_resolve(query):
    return []


def raw(name):
    return (FIXTURES / name).read_bytes()


def fixture_fetch(url):
    return raw(FEED_FILES[url])


def src(name="test", type="editorial"):
    return {"name": name, "type": type}


# ---------------- per-source parsing ----------------

def test_nowplaying_keeps_ost_and_vinyl_only():
    items = collect.parse_nowplaying(raw("nowplaying-feed.xml"), no_resolve)
    assert len(items) == 10  # 15 in feed, 5 are News (singles/previews)
    titles = " | ".join(i["title"] for i in items)
    assert "UNBEATABLE" in titles
    assert "Mina the Hollower" in titles  # Vinyl category included
    assert "Splatoon Raiders" not in titles  # News category excluded
    assert all(i["url"].startswith("https://nowplaying.cool/") for i in items)
    assert all(i["date"] for i in items)


def test_blipblop_keeps_confirmed_release_only():
    items = collect.parse_blipblop(raw("blipblop-feed.xml"), no_resolve)
    assert len(items) == 9  # 10 in feed; the Sonic Frontiers EP campaign isn't a confirmed release
    titles = " | ".join(i["title"] for i in items)
    assert "Plague Tale" in titles
    assert "TJ Davis" not in titles


def test_vgmo_keeps_news_and_album_reviews_only():
    items = collect.parse_vgmo(raw("vgmo-feed.xml"), no_resolve)
    assert len(items) == 5  # 10 in feed, 5 are Editorials
    titles = " | ".join(i["title"] for i in items)
    assert "NieR:Piano Journeys" in titles
    assert "Listener" not in titles  # the Listener's Guide editorials


def test_steam_parses_search_rows():
    items = collect.parse_steam(raw("steam-soundtracks.json"), no_resolve)
    assert len(items) == 25
    assert items[0]["title"] == "Endacopia Soundtrack"
    assert items[0]["url"].startswith("https://store.steampowered.com/app/")
    assert "?" not in items[0]["url"]  # tracking query stripped so reruns dedupe
    assert all(i["date"] and i["date"].startswith("2026-") for i in items)
    assert items[0]["date"] == "2026-07-28"


def test_steam_rows_carry_game_and_art():
    items = collect.parse_steam(raw("steam-soundtracks.json"), no_resolve)
    assert items[0]["game"] == "Endacopia"
    assert items[0]["art"] and items[0]["art"].endswith("/header.jpg")
    assert "/apps/" in items[0]["art"]
    assert all(i["art"] for i in items)  # every search row ships a capsule image


@pytest.mark.parametrize("title,game", [
    ("Hollow Knight - Official Soundtrack", "Hollow Knight"),
    ("Clair Obscur: Expedition 33 – Original Soundtrack", "Clair Obscur: Expedition 33"),
    ("Ori and the Blind Forest (Additional Soundtrack)", "Ori and the Blind Forest"),
    ("Dying Light Original Soundtrack", "Dying Light"),
    ("Stardew Valley 1.6 Original Sound Track", "Stardew Valley 1.6"),
    ("Fight Songs: The Music Of Team Fortress 2", None),  # no soundtrack suffix to strip
    ("OST", None),
])
def test_steam_game_derivation(title, game):
    assert collect._steam_game(title) == game


def test_steam_skips_unreleased_rows():
    blob = json.dumps({"success": 1, "results_html":
        '<a href="https://store.steampowered.com/app/1/A/?snr=x" class="search_result_row">'
        '<span class="title">Real Album Soundtrack</span>'
        '<div class="search_released">Jul 20, 2026</div></a>'
        '<a href="https://store.steampowered.com/app/2/B/" class="search_result_row">'
        '<span class="title">Vapor Soundtrack</span>'
        '<div class="search_released">Coming soon</div></a>'}).encode()
    items = collect.parse_steam(blob, no_resolve)
    assert [i["title"] for i in items] == ["Real Album Soundtrack"]
    assert items[0]["date"] == "2026-07-20"
    assert items[0]["url"] == "https://store.steampowered.com/app/1/A/"


# ---------------- IGDB + strict album matching ----------------

def test_igdb_yields_only_games_with_confident_albums():
    items = collect.parse_igdb(raw("igdb-games.json"), fake_resolve)
    assert {i["game"] for i in items} == {"Fading Echo", "Scarlet Deer Inn", "Denshattack!"}
    fading = next(i for i in items if i["game"] == "Fading Echo")
    assert fading["title"] == "Fading Echo (Original Soundtrack)"
    assert fading["composers"] == ["Maxwell Sterling"]
    assert fading["ytmAlbumUrl"] == "https://music.youtube.com/browse/MPREb_hK34tOz4ENm"
    assert fading["url"] == "https://www.igdb.com/games/fading-echo"
    assert fading["date"] == "2026-07-21"
    assert fading["art"] and "googleusercontent" in fading["art"]  # album art from the YTM match
    # Halo: Campaign Evolved is in the games fixture but YTM only offers the
    # 2001 Combat Evolved album — the strict matcher must refuse it
    assert not any(i["game"] == "Halo: Campaign Evolved" for i in items)


def test_matcher_rejects_near_names_and_fan_albums():
    n = collect.normalize_title
    assert collect._match_album(YTM_FIX["Halo Campaign Evolved soundtrack"],
                                n("Halo: Campaign Evolved")) is None
    assert collect._match_album(YTM_FIX["Hades II soundtrack"], n("Hades II")) is None  # fan album
    assert collect._match_album(YTM_FIX["UNBEATABLE soundtrack"], n("UNBEATABLE")) is None
    hit = collect._match_album(YTM_FIX["Scarlet Deer Inn soundtrack"], n("Scarlet Deer Inn"))
    assert hit and "Lukáš Navrátil" in hit["composers"]
    assert hit["url"] == "https://music.youtube.com/browse/MPREb_LUaLY8EETcH"


def test_matcher_rejects_same_name_band_albums():
    n = collect.normalize_title
    # observed live: the game ZeroSpace matched Kidneythieves' 2002 album, and
    # "Lifted" matched a non-game album with no credited composer
    band = [{"resultType": "album", "browseId": "MPREb_band", "title": "Zerospace",
             "artists": [{"name": "Kidneythieves"}]}]
    assert collect._match_album(band, n("ZeroSpace")) is None  # no soundtrack word
    selfcredit = [{"resultType": "album", "browseId": "MPREb_self",
                   "title": "Lifted (Original Soundtrack)", "artists": [{"name": "Lifted"}]}]
    assert collect._match_album(selfcredit, n("Lifted")) is None  # only credit is the name itself
    # order independence: a plain same-name album before the real OST is skipped, not fatal
    reordered = [YTM_FIX["Fading Echo soundtrack"][2], YTM_FIX["Fading Echo soundtrack"][0]]
    hit = collect._match_album(reordered, n("Fading Echo"))
    assert hit and hit["title"] == "Fading Echo (Original Soundtrack)"


def test_resolver_backfills_recent_unresolved_rows():
    def row(title, date, album=None):
        return {"id": collect.slugify(title), "title": title, "game": None, "composers": [],
                "date": date, "sources": [], "ytmSearchUrl": "x",
                "ytmAlbumUrl": album, "art": None, "notable": True}
    steamish = row("Denshattack! Soundtrack", "2026-07-25")
    headline = row("Mahou Arms finally hits 1.0, and Dale North's full OST is a vibe", "2026-07-27")
    ancient = row("Fading Echo Soundtrack", "2026-01-01")  # matchable but outside the window
    done = row("Hades II", "2026-07-20", album="https://music.youtube.com/browse/existing")
    done["art"] = "https://example.com/done.jpg"  # fully resolved rows cost no lookup
    releases = [steamish, headline, ancient, done]
    looked, filled = collect.resolve_albums(releases, fake_resolve, NOW)
    assert (looked, filled) == (2, 1)  # ancient + done never looked up
    assert steamish["ytmAlbumUrl"] == "https://music.youtube.com/browse/MPREb_8VX7LFDliIy"
    assert steamish["art"] and "googleusercontent" in steamish["art"]
    assert "Tee Lopes" in steamish["composers"]
    assert headline["ytmAlbumUrl"] is None  # editorial headlines never equal album titles
    assert ancient["ytmAlbumUrl"] is None
    assert done["ytmAlbumUrl"] == "https://music.youtube.com/browse/existing"


@pytest.mark.parametrize("headline,album", [
    ("Atomic Owl vinyl reissue is now available from Ghost Mutt Records", "Atomic Owl"),
    ("Resonance: A Plague Tale Legacy vinyl soundtrack up for preorder via Black Screen Records",
     "Resonance: A Plague Tale Legacy vinyl soundtrack"),
    ("Make yourself at home : the World of Warcraft housing soundtrack has arrived",
     "World of Warcraft housing soundtrack"),
    ("Lost In Cult to reissue the Starbound soundtrack on vinyl", "Starbound soundtrack"),
    ("Mahou Arms finally hits 1.0, and Dale North's full OST is a vibe", "Mahou Arms"),
    ("iam8bit announces the Mina the Hollower 3LP vinyl", "Mina the Hollower"),
    ("The cult techno soundtrack of ChainDive finally hits streaming", "cult techno soundtrack of ChainDive"),
    ("Bargain with fate with the Schrödinger's Call soundtrack", None),  # no cut applies: keep the headline
    ("Endacopia Soundtrack", None),  # already an album name
])
def test_headline_album_extraction(headline, album):
    assert collect.headline_album(headline) == album


def test_headline_parsers_attach_display_labels():
    np = collect.parse_nowplaying(raw("nowplaying-feed.xml"), no_resolve)
    wow = next(i for i in np if "World of Warcraft" in i["title"])
    assert wow["albumTitle"] == "World of Warcraft housing soundtrack"
    mahou = next(i for i in np if "Mahou Arms" in i["title"])
    assert mahou["albumTitle"] == "Mahou Arms"
    bb = collect.parse_blipblop(raw("blipblop-feed.xml"), no_resolve)
    owl = next(i for i in bb if "Atomic Owl" in i["title"])
    assert owl["albumTitle"] == "Atomic Owl"


def test_merge_carries_and_fills_album_titles():
    releases = []
    collect.merge(releases, [{"title": "Atomic Owl vinyl reissue is now available from Ghost Mutt Records",
                              "albumTitle": "Atomic Owl", "url": "https://blipblop.net/owl",
                              "date": "2026-07-28"}], src("blipblop"), SEEN)
    assert releases[0]["albumTitle"] == "Atomic Owl"
    # a second source's derived label only fills, never overwrites
    collect.merge(releases, [{"title": "Atomic Owl vinyl reissue is now available from Ghost Mutt Records",
                              "albumTitle": "Different Label", "url": "https://other.example/owl",
                              "date": "2026-07-28"}], src("other"), SEEN)
    assert releases[0]["albumTitle"] == "Atomic Owl"


ATOMIC_OWL_RESULTS = [
    {"resultType": "album", "browseId": "MPREb_owl", "title": "Atomic Owl (Original Game Soundtrack)",
     "artists": [{"name": "Some Composer"}],
     "thumbnails": [{"url": "https://img.example/owl.jpg", "width": 544}]},
]


def test_containment_matcher_accepts_headline_supersets_only():
    n = collect.normalize_title
    hay = n("Atomic Owl vinyl reissue is now available from Ghost Mutt Records")
    hit = collect._match_album_within(ATOMIC_OWL_RESULTS, hay)
    assert hit and hit["title"] == "Atomic Owl (Original Game Soundtrack)"
    # single-word names are banned: "Hades" inside a Hades II headline would mislabel it
    one_word = [{"resultType": "album", "browseId": "MPREb_h", "title": "Hades (Original Soundtrack)",
                 "artists": [{"name": "Darren Korb"}], "thumbnails": []}]
    assert collect._match_album_within(one_word, n("hades ii crossover concert announced")) is None
    # no soundtrack keyword, no match
    band = [{"resultType": "album", "browseId": "MPREb_b", "title": "Atomic Owl Anthems",
             "artists": [{"name": "X"}], "thumbnails": []}]
    assert collect._match_album_within(band, hay) is None
    # name not actually inside the headline
    assert collect._match_album_within(ATOMIC_OWL_RESULTS, n("some unrelated news post")) is None


def test_resolver_relabels_headline_rows_with_album_titles():
    row = {"id": "atomic-owl-headline",
           "title": "Atomic Owl vinyl reissue is now available from Ghost Mutt Records",
           "albumTitle": "Atomic Owl",  # heuristic label from parse time
           "game": None, "composers": [], "date": "2026-07-28", "sources": [],
           "ytmSearchUrl": "s", "ytmAlbumUrl": None, "art": None, "notable": True}
    looked, filled = collect.resolve_albums([row], lambda q: ATOMIC_OWL_RESULTS, NOW)
    assert (looked, filled) == (1, 1)
    assert row["albumTitle"] == "Atomic Owl (Original Game Soundtrack)"  # YTM's name beats the heuristic
    assert row["ytmAlbumUrl"] == "https://music.youtube.com/browse/MPREb_owl"
    assert row["art"] == "https://img.example/owl.jpg"
    assert row["composers"] == ["Some Composer"]


def test_strict_matches_do_not_add_redundant_album_titles():
    row = {"id": "denshattack", "title": "Denshattack! Soundtrack", "game": None, "composers": [],
           "date": "2026-07-25", "sources": [], "ytmSearchUrl": "s",
           "ytmAlbumUrl": None, "art": None, "notable": True}
    collect.resolve_albums([row], fake_resolve, NOW)
    assert row["ytmAlbumUrl"]  # matched strictly
    assert "albumTitle" not in row  # same album name modulo suffixes: no relabel needed


def test_resolver_fills_art_on_rows_that_already_have_albums():
    r = {"id": "denshattack", "title": "Denshattack! Soundtrack", "game": None, "composers": ["x"],
         "date": "2026-07-25", "sources": [], "ytmSearchUrl": "s",
         "ytmAlbumUrl": "https://music.youtube.com/browse/already", "art": None, "notable": True}
    looked, filled = collect.resolve_albums([r], fake_resolve, NOW)
    assert (looked, filled) == (1, 0)  # a lookup, but no album overwrite
    assert r["ytmAlbumUrl"] == "https://music.youtube.com/browse/already"
    assert r["art"] and "googleusercontent" in r["art"]


def test_resolver_respects_cap():
    rows = [{"id": str(i), "title": f"Nothing Matches This {i}", "game": None, "composers": [],
             "date": "2026-07-20", "sources": [], "ytmSearchUrl": "x",
             "ytmAlbumUrl": None, "art": None, "notable": True} for i in range(5)]
    looked, filled = collect.resolve_albums(rows, fake_resolve, NOW, cap=3)
    assert (looked, filled) == (3, 0)


def test_merge_enriches_nulls_without_touching_the_rest():
    releases = []
    collect.merge(releases, [{"title": "Denshattack! Soundtrack",
                              "url": "https://store.steampowered.com/app/9/D/",
                              "date": "2026-07-25"}], src("steam", "catalog"), SEEN)
    collect.merge(releases, [{"title": "Denshattack! (Original Game Soundtrack)",
                              "game": "Denshattack!", "composers": ["Tee Lopes"],
                              "url": "https://www.igdb.com/games/denshattack",
                              "date": "2026-07-15", "art": "https://example.com/densh.jpg",
                              "ytmAlbumUrl": "https://music.youtube.com/browse/MPREb_8VX7LFDliIy"}],
                  src("igdb", "catalog"), SEEN)
    assert len(releases) == 1  # both normalize to "denshattack"
    entry = releases[0]
    assert entry["title"] == "Denshattack! Soundtrack"  # first-seen title kept
    assert entry["game"] == "Denshattack!"              # null filled
    assert entry["composers"] == ["Tee Lopes"]          # empty filled
    assert entry["ytmAlbumUrl"] == "https://music.youtube.com/browse/MPREb_8VX7LFDliIy"
    assert entry["art"] == "https://example.com/densh.jpg"  # art null-filled, never overwritten
    assert entry["date"] == "2026-07-15"                # earliest (game release) wins
    assert [s["name"] for s in entry["sources"]] == ["steam", "igdb"]


# ---------------- slugs and normalization ----------------

@pytest.mark.parametrize("title,slug", [
    ("Chrono Trigger OST", "chrono-trigger"),
    ("DOOM: The Dark Ages (Original Game Soundtrack)", "doom-the-dark-ages"),
    ("Hades II - Original Soundtrack", "hades-ii"),
    ("Endacopia Soundtrack", "endacopia"),
    ("Celeste: Farewell (Original Soundtrack)", "celeste-farewell"),
    ("NieR:Piano Journeys", "nier-piano-journeys"),
    ("Stardew Valley 1.6 Original Sound Track", "stardew-valley-1-6"),
    ("ペルソナ5 OST", "ペルソナ5"),
    ("Ghost of Tsushima (Music from the Video Game)", "ghost-of-tsushima"),
    ("Marvel's Spider-Man (Original Video Game Soundtrack)", "marvel-s-spider-man"),
    ("OST", "ost"),  # a title that is only a suffix survives as itself
])
def test_slugify(title, slug):
    assert collect.slugify(title) == slug


def test_matcher_accepts_console_exclusive_album_namings():
    n = collect.normalize_title
    tsushima = [{"resultType": "album", "browseId": "MPREb_got",
                 "title": "Ghost of Tsushima (Music from the Video Game)",
                 "artists": [{"name": "Ilan Eshkeri"}, {"name": "Shigeru Umebayashi"}],
                 "thumbnails": [{"url": "https://img.example/got.jpg", "width": 544}]}]
    hit = collect._match_album(tsushima, n("Ghost of Tsushima"))
    assert hit and hit["composers"] == ["Ilan Eshkeri", "Shigeru Umebayashi"]
    spidey = [{"resultType": "album", "browseId": "MPREb_sm",
               "title": "Marvel's Spider-Man (Original Video Game Soundtrack)",
               "artists": [{"name": "John Paesano"}], "thumbnails": []}]
    assert collect._match_album(spidey, n("Marvel's Spider-Man")) is not None
    # a bare same-name album with no soundtrack marker stays out (band-album guard)
    bare = [{"resultType": "album", "browseId": "MPREb_tlou", "title": "The Last of Us",
             "artists": [{"name": "Gustavo Santaolalla"}], "thumbnails": []}]
    assert collect._match_album(bare, n("The Last of Us")) is None


def test_year_anchor_blocks_franchise_crossmatches():
    n = collect.normalize_title
    reboot_ost = [{"resultType": "album", "browseId": "MPREb_tr", "year": "2013",
                   "title": "Tomb Raider (Original Soundtrack)",
                   "artists": [{"name": "Jason Graves"}], "thumbnails": []}]
    # the 1996 game must not adopt the 2013 reboot's album...
    assert collect._match_album(reboot_ost, n("Tomb Raider"), year=1996) is None
    # ...while the reboot itself still matches, as does an unanchored lookup
    assert collect._match_album(reboot_ost, n("Tomb Raider"), year=2013) is not None
    assert collect._match_album(reboot_ost, n("Tomb Raider")) is not None
    # albums with missing/garbage year metadata aren't punished
    no_year = [dict(reboot_ost[0], year=None)]
    assert collect._match_album(no_year, n("Tomb Raider"), year=1996) is not None


def test_slug_is_stable_across_source_phrasings():
    a = collect.slugify("Silksong — Official Soundtrack")
    b = collect.slugify("silksong official soundtrack")
    assert a == b == "silksong"


# ---------------- YT Music search URLs ----------------

def test_ytm_url_basic():
    url = collect.ytm_search_url("Celeste", "Celeste")
    assert url == "https://music.youtube.com/search?q=Celeste+Celeste+soundtrack"


def test_ytm_url_drops_null_game_and_encodes_punctuation():
    url = collect.ytm_search_url("Ratchet & Clank: Rift Apart", None)
    assert url == "https://music.youtube.com/search?q=Ratchet+%26+Clank%3A+Rift+Apart+soundtrack"


def test_ytm_url_encodes_japanese():
    url = collect.ytm_search_url("ゼルダの伝説", None)
    assert url.startswith("https://music.youtube.com/search?q=%E3%82%BC")
    assert url.endswith("+soundtrack")


# ---------------- dedupe / merge / append-only ----------------

def test_same_album_from_two_sources_collides_into_one_entry():
    releases = []
    collect.merge(releases, [{"title": "Hades II Original Soundtrack",
                              "url": "https://a.example/hades", "date": "2026-07-30"}],
                  src("a"), SEEN)
    collect.merge(releases, [{"title": "Hades II OST",
                              "url": "https://b.example/hades", "date": "2026-07-28"}],
                  src("b"), SEEN)
    assert len(releases) == 1
    entry = releases[0]
    assert entry["id"] == "hades-ii"
    assert [s["name"] for s in entry["sources"]] == ["a", "b"]
    assert entry["date"] == "2026-07-28"  # earliest date wins
    assert entry["title"] == "Hades II Original Soundtrack"  # first-seen title kept


def test_fuzzy_near_miss_merges():
    releases = []
    collect.merge(releases, [{"title": "The Legend of Zelda: Echoes of Wisdom Original Soundtrack",
                              "url": "https://a.example/1", "date": "2026-07-01"}], src("a"), SEEN)
    collect.merge(releases, [{"title": "Legend of Zelda Echoes of Wisdom Soundtrack",
                              "url": "https://b.example/2", "date": "2026-07-02"}], src("b"), SEEN)
    assert len(releases) == 1
    assert len(releases[0]["sources"]) == 2


def test_clearly_different_titles_do_not_merge():
    releases = []
    collect.merge(releases, [{"title": "Hollow Knight: Silksong OST",
                              "url": "https://a.example/1", "date": "2026-07-01"}], src("a"), SEEN)
    collect.merge(releases, [{"title": "Hades II OST",
                              "url": "https://b.example/2", "date": "2026-07-02"}], src("b"), SEEN)
    assert len(releases) == 2


def test_rerun_is_append_only_and_idempotent():
    releases = []
    items = [{"title": "Tunic Soundtrack", "url": "https://a.example/tunic", "date": "2026-06-01"}]
    collect.merge(releases, items, src("a"), SEEN)
    snapshot = copy.deepcopy(releases)
    added, merged = collect.merge(releases, copy.deepcopy(items), src("a"), "2026-07-29T10:00:00Z")
    assert (added, merged) == (0, 0)
    assert releases == snapshot  # same source re-reporting changes nothing, seenAt included


def test_unrelated_existing_entry_survives_untouched():
    veteran = {"id": "chrono-trigger", "title": "Chrono Trigger OST", "game": None,
               "composers": [], "date": "1995-03-25",
               "sources": [{"name": "a", "type": "editorial",
                            "url": "https://a.example/ct", "seenAt": "2026-01-01T00:00:00Z"}],
               "ytmSearchUrl": "https://music.youtube.com/search?q=Chrono+Trigger+OST+soundtrack",
               "ytmAlbumUrl": None, "art": None, "notable": True}
    releases = [veteran]
    frozen = copy.deepcopy(veteran)
    collect.merge(releases, [{"title": "Something Else Entirely",
                              "url": "https://b.example/x", "date": "2026-07-28"}], src("b"), SEEN)
    assert releases[0] == frozen


def test_new_entry_shape_matches_schema():
    releases = []
    collect.merge(releases, [{"title": "Tunic Soundtrack",
                              "url": "https://a.example/tunic", "date": "2026-06-01"}],
                  src("a", type="catalog"), SEEN)
    entry = releases[0]
    assert set(entry) == {"id", "title", "game", "composers", "date", "sources",
                          "ytmSearchUrl", "ytmAlbumUrl", "art", "notable"}
    assert entry["game"] is None and entry["composers"] == []
    assert entry["ytmAlbumUrl"] is None and entry["art"] is None and entry["notable"] is True
    assert entry["sources"][0] == {"name": "a", "type": "catalog",
                                   "url": "https://a.example/tunic", "seenAt": SEEN}


# ---------------- end to end against all fixtures ----------------

def test_run_collects_all_sources_and_is_stable(tmp_path):
    data_path = tmp_path / "releases.json"
    assert collect.run(fetch_fn=fixture_fetch, resolve_fn=fake_resolve,
                       data_path=data_path, now=NOW) == 0
    data = json.loads(data_path.read_text(encoding="utf-8"))
    assert data["updatedAt"] == SEEN
    assert len(data["releases"]) == 52  # 10 + 9 + 5 + 25 + 3 igdb, no cross-source collisions
    igdb_rows = [r for r in data["releases"] if r["sources"][0]["name"] == "igdb"]
    assert len(igdb_rows) == 3
    assert all(r["ytmAlbumUrl"] and r["game"] and r["composers"] and r["art"] for r in igdb_rows)
    steam_rows = [r for r in data["releases"] if r["sources"][0]["name"] == "steam"]
    assert all(r["art"] for r in steam_rows)  # every steam row derives header art

    # a second run over identical feeds must not rewrite the file
    first = data_path.read_text(encoding="utf-8")
    later = datetime(2026, 7, 29, 10, 0, 0, tzinfo=timezone.utc)
    assert collect.run(fetch_fn=fixture_fetch, resolve_fn=fake_resolve,
                       data_path=data_path, now=later) == 0
    assert data_path.read_text(encoding="utf-8") == first


def test_run_survives_one_source_failing(tmp_path, capsys):
    def flaky(url):
        if "blipblop" in url:
            raise OSError("simulated network failure")
        return fixture_fetch(url)
    data_path = tmp_path / "releases.json"
    assert collect.run(fetch_fn=flaky, resolve_fn=fake_resolve,
                       data_path=data_path, now=NOW) == 0
    out = capsys.readouterr().out
    assert "::warning::blipblop failed" in out
    assert len(json.loads(data_path.read_text(encoding="utf-8"))["releases"]) == 43


def test_run_fails_red_when_every_source_fails(tmp_path, capsys):
    def dead(url):
        raise OSError("nope")
    assert collect.run(fetch_fn=dead, resolve_fn=no_resolve,
                       data_path=tmp_path / "releases.json", now=NOW) == 1
    assert "::error::" in capsys.readouterr().out
