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


def no_album(browse_id):
    return {"tracks": []}


def no_itunes(query):
    return None


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
    assert fading["title"] == "Fading Echo Soundtrack"
    assert fading["albumTitle"] == "Fading Echo (Original Soundtrack)"
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


def test_gaas_scan_collects_every_qualifying_album():
    results = [
        {"resultType": "album", "browseId": "MPREb_g1", "year": "2020",
         "title": "Genshin Impact - City of Winds and Idylls (Original Game Soundtrack)",
         "artists": [{"name": "Yu-Peng Chen"}], "thumbnails": []},
        {"resultType": "album", "browseId": "MPREb_g2", "year": "2023",
         "title": "Genshin Impact - Fountain of Belleau (Original Game Soundtrack)",
         "artists": [{"name": "HOYO-MiX"}], "thumbnails": []},
        {"resultType": "album", "browseId": "MPREb_bad1", "year": "2022",
         "title": "Genshin Impact Lofi Chill Soundtrack Remixes",
         "artists": [{"name": "Some Channel"}], "thumbnails": []},
        {"resultType": "album", "browseId": "MPREb_bad2", "year": "2021",
         "title": "Anime Piano Soundtrack Collection",
         "artists": [{"name": "X"}], "thumbnails": []},
        {"resultType": "album", "browseId": "MPREb_bad3", "year": "2025",
         "title": "A Genshin Impact Movie (Original Motion Picture Soundtrack)",
         "artists": [{"name": "Various Artists"}], "thumbnails": []},
        {"resultType": "album", "browseId": "MPREb_bad4", "year": "2024",
         "title": "Our Cool Tales in Genshin Impact Soundtrack",
         "artists": [{"name": "Various Artists"}], "thumbnails": []},
    ]
    releases = []
    added, merged = collect.gaas_albums(releases, lambda q, limit=5: results, SEEN,
                                        names=["Genshin Impact"])
    assert added == 2  # two real volumes; the remix and the unrelated album stay out
    assert {r["title"] for r in releases} == {
        "Genshin Impact - City of Winds and Idylls (Original Game Soundtrack)",
        "Genshin Impact - Fountain of Belleau (Original Game Soundtrack)"}
    assert all(r["game"] == "Genshin Impact" and r["ytmAlbumUrl"] for r in releases)
    assert releases[0]["date"] == "2020-01-01"  # dated by album year, not the game
    # rerun: idempotent, new seasons would append
    added2, _ = collect.gaas_albums(releases, lambda q, limit=5: results, SEEN,
                                    names=["Genshin Impact"])
    assert added2 == 0 and len(releases) == 2


def test_arriving_album_invalidates_stale_tracklists():
    releases = []
    collect.merge(releases, [{"title": "Hi-Fi Rush Soundtrack",
                              "url": "https://a.example/hfr", "date": "2023-01-25"}], src("a"), SEEN)
    releases[0]["tracks"] = []  # checked while it was a search row: nothing found
    collect.merge(releases, [{"title": "Hi-Fi Rush Soundtrack", "albumTitle": "Hi-Fi RUSH OST",
                              "url": "https://b.example/hfr", "date": "2023-01-25",
                              "ytmAlbumUrl": "https://music.youtube.com/browse/MPREb_hfr"}], src("b"), SEEN)
    assert "tracks" not in releases[0]  # stale check cleared: fill refetches with plays
    assert releases[0]["ytmAlbumUrl"]


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


# ---------------- top tracks + companies ----------------

def test_plays_num_parses_ytm_counts():
    assert collect._plays_num("9 plays") == 9
    assert collect._plays_num("1.2M plays") == 1_200_000
    assert collect._plays_num("12,345 plays") == 12_345
    assert collect._plays_num("3B plays") == 3_000_000_000
    assert collect._plays_num(None) is None


def test_itunes_album_matching():
    n = collect.normalize_title
    m = collect._itunes_album_matches
    assert m("Pokémon Diamond & Pokémon Pearl: Super Music Collection", n("Pokémon Diamond Version"))
    assert m("Pokémon X & Pokémon Y: Super Music Collection", n("Pokémon X"))
    assert m("Kirby and the Forgotten Land", n("Kirby and the Forgotten Land"))  # exact, any artist
    assert not m("Kirby and the Forgotten Land (Covers)", n("Kirby and the Forgotten Land"))  # no music wording
    assert not m("Unrelated Music Collection", n("Pokémon Diamond Version"))
    assert not m("Pearl Music", n("Pearl"))  # too short to trust containment


def test_ytm_tracks_capture_plays_and_video_ids():
    album = {"tracks": [{"title": "Hit", "views": "2M plays", "videoId": "vidH"},
                        {"title": "Quiet", "views": None, "videoId": None},
                        {"title": ""}]}
    tracks = collect.ytm_tracks_from(album)
    assert tracks == [{"title": "Hit", "plays": "2M plays", "videoId": "vidH"},
                      {"title": "Quiet", "plays": None, "videoId": None}]


def test_genres_of_takes_top_three_names():
    g = {"genres": [{"name": "Role-playing (RPG)"}, {"name": "Adventure"},
                    {"name": "Indie"}, {"name": "Strategy"}]}
    assert collect.genres_of(g) == ["Role-playing (RPG)", "Adventure", "Indie"]
    assert collect.genres_of({}) is None


def test_fill_tracks_uses_ytm_then_itunes_and_never_refetches():
    def album(bid):
        return {"tracks": [{"title": f"T-{bid}", "views": "5 plays", "videoId": "v"}],
                "audioPlaylistId": f"OLAK_{bid}"}
    def itunes(query):
        return [{"title": "Apple Track", "plays": None}] if "Gold" in query else None
    rows = [
        {"ytmAlbumUrl": "https://music.youtube.com/browse/MPREb_a", "topTracks": []},
        {"ytmAlbumUrl": None, "game": "Pokémon Gold Version"},
        {"ytmAlbumUrl": None, "game": "Obscure Nothing"},
        {"ytmAlbumUrl": None, "game": None, "title": "headline row"},  # nothing to look up
        {"ytmAlbumUrl": "https://music.youtube.com/browse/MPREb_b", "tracks": []},  # already checked
    ]
    assert collect.fill_tracks(rows, album, itunes, cap=1) == 1
    assert rows[0]["tracks"][0] == {"title": "T-MPREb_a", "plays": "5 plays", "videoId": "v"}
    assert rows[0]["ytmPlaylistId"] == "OLAK_MPREb_a"  # album context for song-not-video links
    assert "topTracks" not in rows[0]  # legacy field retired on refetch
    assert collect.fill_tracks(rows, album, itunes, cap=10) == 2
    assert rows[1]["tracks"] == [{"title": "Apple Track", "plays": None}]  # Apple fallback
    assert rows[2]["tracks"] == []  # no match anywhere: completed check
    assert "tracks" not in rows[3]
    assert collect.fill_tracks(rows, album, itunes, cap=10) == 0  # everything settled


def test_is_console_classification():
    assert collect.is_console({"platforms": [6]}) is False              # PC only
    assert collect.is_console({"platforms": [6, 14, 3]}) is False       # PC/Mac/Linux
    assert collect.is_console({"platforms": [6, 130]}) is True          # PC + Switch
    assert collect.is_console({"platforms": [508]}) is True             # unknown/future id counts as console
    assert collect.is_console({"platforms": [39, 34]}) is False         # mobile-only
    assert collect.is_console({}) is None                               # unknown stays unknown


def test_merge_carries_console_flag():
    releases = []
    collect.merge(releases, [{"title": "Tunic Soundtrack", "url": "https://a.example/t",
                              "date": "2026-06-01", "console": True}], src("a"), SEEN)
    assert releases[0]["console"] is True
    collect.merge(releases, [{"title": "Tunic Soundtrack", "url": "https://b.example/t",
                              "date": "2026-06-01", "console": False}], src("b"), SEEN)
    assert releases[0]["console"] is True  # known value never overwritten


def test_company_of_prefers_the_developer():
    g = {"involved_companies": [
        {"developer": False, "company": {"name": "Big Publisher"}},
        {"developer": True, "company": {"name": "Tiny Studio"}}]}
    assert collect.company_of(g) == "Tiny Studio"
    assert collect.company_of({"involved_companies": [
        {"developer": False, "company": {"name": "Only Publisher"}}]}) == "Only Publisher"
    assert collect.company_of({}) is None


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


def test_numeral_folding_matches_roman_against_arabic():
    n = collect.normalize_title
    assert collect._numfold("assassin s creed ii") == "assassin s creed 2"
    assert collect._numfold("final fantasy ix") == "final fantasy 9"
    assert collect._numfold("i am the chowder man") == "i am the chowder man"  # "i" stays a word
    assert collect._numfold("persona5") == "persona 5"  # letter-digit boundary splits
    p5 = [{"resultType": "album", "browseId": "MPREb_p5", "year": "2018",
           "title": "PERSONA5 ORIGINAL SOUNDTRACK",
           "artists": [{"name": "ATLUS Sound Team"}], "thumbnails": []}]
    assert collect._match_album(p5, n("Persona 5")) is not None
    hifi = [{"resultType": "album", "browseId": "MPREb_hfr", "year": "2023",
             "title": "Hi-Fi RUSH: Original Game Soundtrack",
             "artists": [{"name": "Various Artists"}], "thumbnails": []}]
    hit = collect._match_album(hifi, n("Hi-Fi Rush"))
    assert hit is not None and hit["composers"] == []  # VA compilations are legitimate
    ac2 = [{"resultType": "album", "browseId": "MPREb_ac2", "year": "2009",
            "title": "Assassin's Creed 2 (Original Game Soundtrack)",
            "artists": [{"name": "Jesper Kyd"}],
            "thumbnails": [{"url": "https://img.example/ac2.jpg", "width": 544}]}]
    hit = collect._match_album(ac2, n("Assassin's Creed II"), year=2009)
    assert hit and hit["composers"] == ["Jesper Kyd"]
    assert collect._itunes_album_matches("Final Fantasy 9 Original Soundtrack", n("Final Fantasy IX"))


def test_token_matcher_accepts_reworded_albums_but_not_tributes():
    sly = [{"resultType": "album", "browseId": "MPREb_sly",
            "title": "Sly Cooper Vol. I: The Thievius Raccoonus (Music Inspired by the Videogame Soundtrack)",
            "artists": [{"name": "Saliscore"}], "thumbnails": []}]
    hit = collect._match_album_tokens(sly, "Sly Cooper and the Thievius Raccoonus")
    assert hit and hit["url"].endswith("MPREb_sly")
    remix = [{"resultType": "album", "browseId": "MPREb_rx",
              "title": 'Spyro Remixed: Music from "Spyro The Dragon"',
              "artists": [{"name": "Tiny Waves"}], "thumbnails": []}]
    assert collect._match_album_tokens(remix, "Spyro the Dragon") is None  # 'remixed' is foreign
    fever = [{"resultType": "album", "browseId": "MPREb_f", "title": "Pac-Man Fever (Soundtrack)",
              "artists": [{"name": "Buckner & Garcia"}], "thumbnails": []}]
    assert collect._match_album_tokens(fever, "Pac-Man") is None  # 'fever' is foreign
    symphony = [{"resultType": "album", "browseId": "MPREb_s", "title": "Donkey Kong 64 Symphony (Original Score)",
                 "artists": [{"name": "Orchestra"}], "thumbnails": []}]
    assert collect._match_album_tokens(symphony, "Donkey Kong 64") is None  # 'symphony' is foreign
    # volume numbers are bookkeeping; game numerals are identity
    gtav = [{"resultType": "album", "browseId": "MPREb_gta", "title": "The Music of Grand Theft Auto V, Vol. 1: Original Music",
             "artists": [{"name": "Various Artists"}], "thumbnails": []}]
    assert collect._match_album_tokens(gtav, "Grand Theft Auto V") is not None
    hm1cover = [{"resultType": "album", "browseId": "MPREb_hm1", "title": "Hotline Miami (Soundtrack)",
                 "artists": [{"name": "Wolves Den"}], "thumbnails": []}]
    assert collect._match_album_tokens(hm1cover, "Hotline Miami 2: Wrong Number") is None  # missing the 2
    hm2 = [{"resultType": "album", "browseId": "MPREb_hm2", "title": "Hotline Miami 2 (Official Soundtrack)",
            "artists": [{"name": "Various Artists"}], "thumbnails": []}]
    assert collect._match_album_tokens(hm2, "Hotline Miami 2: Wrong Number") is not None  # subtitle may drop
    alpha = [{"resultType": "album", "browseId": "MPREb_mc", "title": "Minecraft - Volume Alpha (Soundtrack)",
              "artists": [{"name": "C418"}], "thumbnails": []}]
    assert collect._match_album_tokens(alpha, "Minecraft") is not None


def test_containment_tier_takes_creatively_titled_albums():
    p2 = [{"resultType": "album", "browseId": "MPREb_p2",
           "title": "Portal 2: Songs to Test By (Original Game Soundtrack)",
           "artists": [{"name": "Aperture Science Psychoacoustic Laboratories"}], "thumbnails": []}]
    hit = collect._match_album_contains(p2, "Portal 2")
    assert hit and hit["url"].endswith("MPREb_p2")
    # still not a free-for-all: blacklisted wording and missing keywords stay out
    remix = [{"resultType": "album", "browseId": "MPREb_r",
              "title": "Portal 2 Soundtrack Lofi Remixes", "artists": [{"name": "X"}], "thumbnails": []}]
    assert collect._match_album_contains(remix, "Portal 2") is None
    plain = [{"resultType": "album", "browseId": "MPREb_pl",
              "title": "Portal 2 Fan Anthems", "artists": [{"name": "X"}], "thumbnails": []}]
    assert collect._match_album_contains(plain, "Portal 2") is None  # no soundtrack wording
    other = [{"resultType": "album", "browseId": "MPREb_o",
              "title": "Portal Original Soundtrack", "artists": [{"name": "X"}], "thumbnails": []}]
    assert collect._match_album_contains(other, "Portal 2") is None  # the 2 must be present


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
    # numbered names are era-unambiguous: late uploads are welcome
    civ5 = [{"resultType": "album", "browseId": "MPREb_civ5", "year": "2025",
             "title": "Sid Meier's Civilization V (Original Game Soundtrack)",
             "artists": [{"name": "Geoff Knorr"}, {"name": "Michael Curran"}], "thumbnails": []}]
    assert collect._match_album(civ5, n("Sid Meier's Civilization V"), year=2010) is not None


def test_slug_is_stable_across_source_phrasings():
    a = collect.slugify("Silksong — Official Soundtrack")
    b = collect.slugify("silksong official soundtrack")
    assert a == b == "silksong"


# ---------------- YT Music search URLs ----------------

def test_ytm_url_never_duplicates_the_game_name():
    url = collect.ytm_search_url("Madden NFL 26 Soundtrack", "Madden NFL 26")
    assert url == "https://music.youtube.com/search?q=Madden+NFL+26+Soundtrack"
    url = collect.ytm_search_url("Celeste", "Celeste")
    assert url == "https://music.youtube.com/search?q=Celeste+soundtrack"
    url = collect.ytm_search_url("Nos Vies En Lumière", "Clair Obscur: Expedition 33")
    assert url == "https://music.youtube.com/search?q=Nos+Vies+En+Lumi%C3%A8re+Clair+Obscur%3A+Expedition+33+soundtrack"


def test_ytm_url_drops_null_game_and_encodes_punctuation():
    url = collect.ytm_search_url("Ratchet & Clank: Rift Apart OST", None)
    assert url == "https://music.youtube.com/search?q=Ratchet+%26+Clank%3A+Rift+Apart+OST"


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


def test_same_name_different_era_stays_separate():
    releases = []
    collect.merge(releases, [{"title": "Tomb Raider (Original Soundtrack)",
                              "url": "https://a.example/tr2013", "date": "2013-03-05"}], src("a"), SEEN)
    collect.merge(releases, [{"title": "Tomb Raider Soundtrack",
                              "url": "https://b.example/tr1996", "date": "1996-10-24"}], src("b"), SEEN)
    assert len(releases) == 2  # 17 years apart: different releases, not one row
    assert {r["id"] for r in releases} == {"tomb-raider", "tomb-raider-1996"}
    assert next(r for r in releases if r["id"] == "tomb-raider")["date"] == "2013-03-05"
    # rerunning the 1996 item lands on its year-suffixed row, not a third one
    added, merged = collect.merge(releases, [{"title": "Tomb Raider Soundtrack",
                                              "url": "https://b.example/tr1996",
                                              "date": "1996-10-24"}], src("b"), SEEN)
    assert (added, merged) == (0, 0) and len(releases) == 2


def test_numeral_variants_merge_exactly_not_by_fuzzy_odds():
    releases = []
    collect.merge(releases, [{"title": "Assassin's Creed II Soundtrack",
                              "url": "https://a.example/ac2-search", "date": "2009-11-17"}], src("a"), SEEN)
    collect.merge(releases, [{"title": "Assassin's Creed 2 (Original Game Soundtrack)",
                              "url": "https://b.example/ac2-album", "date": "2009-11-17",
                              "ytmAlbumUrl": "https://music.youtube.com/browse/MPREb_ac2"}], src("b"), SEEN)
    assert len(releases) == 1  # II and 2 are the same name: enrich, don't duplicate
    assert releases[0]["id"] == "assassin-s-creed-ii"
    assert releases[0]["ytmAlbumUrl"] == "https://music.youtube.com/browse/MPREb_ac2"


def test_numbered_sequels_never_fuzzy_merge():
    releases = []
    collect.merge(releases, [{"title": "Mass Effect 2 Original Soundtrack",
                              "url": "https://a.example/me2", "date": "2010-01-26"}], src("a"), SEEN)
    collect.merge(releases, [{"title": "Mass Effect 3 Original Soundtrack",
                              "url": "https://b.example/me3", "date": "2012-03-06"}], src("b"), SEEN)
    collect.merge(releases, [{"title": "Grand Theft Auto V Original Soundtrack",
                              "url": "https://c.example/gtav", "date": "2013-09-17"}], src("c"), SEEN)
    collect.merge(releases, [{"title": "Grand Theft Auto 5 Original Soundtrack",
                              "url": "https://d.example/gta5", "date": "2013-09-18"}], src("d"), SEEN)
    assert len(releases) == 3  # ME2 and ME3 stay apart; GTA V and GTA 5 are the same album
    gta = next(r for r in releases if "grand-theft" in r["id"])
    assert len(gta["sources"]) == 2  # roman V and arabic 5 count as the same numeral


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

def test_run_collects_all_sources_and_is_stable(tmp_path, monkeypatch):
    monkeypatch.setattr(collect, "TRACKS_CAP", 100)  # settle every row in run one
    data_path = tmp_path / "releases.json"
    assert collect.run(fetch_fn=fixture_fetch, resolve_fn=fake_resolve, album_fn=no_album, itunes_fn=no_itunes,
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
    assert collect.run(fetch_fn=fixture_fetch, resolve_fn=fake_resolve, album_fn=no_album, itunes_fn=no_itunes,
                       data_path=data_path, now=later) == 0
    assert data_path.read_text(encoding="utf-8") == first


def test_run_survives_one_source_failing(tmp_path, capsys):
    def flaky(url):
        if "blipblop" in url:
            raise OSError("simulated network failure")
        return fixture_fetch(url)
    data_path = tmp_path / "releases.json"
    assert collect.run(fetch_fn=flaky, resolve_fn=fake_resolve, album_fn=no_album, itunes_fn=no_itunes,
                       data_path=data_path, now=NOW) == 0
    out = capsys.readouterr().out
    assert "::warning::blipblop failed" in out
    assert len(json.loads(data_path.read_text(encoding="utf-8"))["releases"]) == 43


def test_run_fails_red_when_every_source_fails(tmp_path, capsys):
    def dead(url):
        raise OSError("nope")
    assert collect.run(fetch_fn=dead, resolve_fn=no_resolve, album_fn=no_album, itunes_fn=no_itunes,
                       data_path=tmp_path / "releases.json", now=NOW) == 1
    assert "::error::" in capsys.readouterr().out


# --- one-album-one-row guards (the Zelda covers-album incident) ---

_COVERS_ALBUM = {"resultType": "album", "browseId": "MPREb_zeldacovers", "year": "2018",
                 "title": "Music from The Legend of Zelda",
                 "artists": [{"name": "Various Artists"}], "thumbnails": []}


def test_va_credit_needs_soundtrack_wording():
    # a Various Artists tribute that never says "soundtrack" is fan territory,
    # even though "music from" satisfies the soundtracky keyword check
    assert collect._match_album_tokens([_COVERS_ALBUM], "The Legend of Zelda: Ocarina of Time") is None
    assert collect._match_album([_COVERS_ALBUM], collect.normalize_title("Music from The Legend of Zelda")) is None
    # but VA plus explicit soundtrack wording stays a legitimate credit
    licensed = dict(_COVERS_ALBUM, title="Hi-Fi RUSH (Original Soundtrack)")
    assert collect._hit_from(licensed)
    tribute = dict(_COVERS_ALBUM, title="The Legend of Zelda Tribute Soundtrack")
    assert collect._hit_from(tribute) is None  # blacklist wording still kills it


def test_relaxed_tiers_respect_the_era_guard():
    reboot = {"resultType": "album", "browseId": "MPREb_tr2013", "year": "2013",
              "title": "Tomb Raider (Original Soundtrack)",
              "artists": [{"name": "Jason Graves"}], "thumbnails": []}
    assert collect._match_album_tokens([reboot], "Tomb Raider", year=1996) is None
    assert collect._match_album_tokens([reboot], "Tomb Raider", year=2013)
    assert collect._match_album_contains([reboot], "Tomb Raider", year=1996) is None
    assert collect._match_album_contains([reboot], "Tomb Raider", year=2012)
    # numbered names stay exempt: classics reach streaming decades late
    civ = {"resultType": "album", "browseId": "MPREb_civ5", "year": "2025",
           "title": "Civilization V Original Soundtrack",
           "artists": [{"name": "Geoff Knorr"}], "thumbnails": []}
    assert collect._match_album_tokens([civ], "Civilization V", year=2010)


def test_resolver_never_reassigns_a_claimed_album():
    owner = {"id": "outer-wilds", "title": "Outer Wilds Soundtrack", "date": "2026-07-20",
             "url": "https://x.example/ow", "sources": [], "notable": True,
             "ytmAlbumUrl": "https://music.youtube.com/browse/MPREb_ow", "art": "https://a.example/ow.jpg"}
    dlc = {"id": "outer-wilds-echoes", "title": "Outer Wilds Soundtrack", "date": "2026-07-21",
           "url": "https://x.example/echoes", "sources": [], "notable": True,
           "ytmAlbumUrl": None, "art": None}
    hit = [{"resultType": "album", "browseId": "MPREb_ow", "year": "2019",
            "title": "Outer Wilds (Original Soundtrack)",
            "artists": [{"name": "Andrew Prahlow"}], "thumbnails": []}]
    looked, filled = collect.resolve_albums([owner, dlc], lambda q: hit, NOW)
    assert filled == 0 and dlc["ytmAlbumUrl"] is None  # the base game keeps its album


def test_gaas_scan_skips_albums_other_rows_wear():
    sideswipe_row = {"id": "rocket-league-sideswipe", "title": "Rocket League Sideswipe Soundtrack",
                     "game": "Rocket League Sideswipe", "date": "2021-11-15", "sources": [],
                     "url": "https://x.example/ss", "notable": True,
                     "ytmAlbumUrl": "https://music.youtube.com/browse/MPREb_ss"}
    results = [{"resultType": "album", "browseId": "MPREb_ss", "year": "2021",
                "title": "Rocket League Sideswipe (Original Game Soundtrack)",
                "artists": [{"name": "Mike Ault"}], "thumbnails": []}]
    releases = [sideswipe_row]
    added, _ = collect.gaas_albums(releases, lambda q, limit=5: results, SEEN,
                                   names=["Rocket League"])
    assert added == 0 and len(releases) == 1  # the game row already wears it


def test_hit_gates_cover_the_publisher_conventions():
    # a covers orchestra with a real name never qualifies, whatever the title
    lmw = {"resultType": "album", "browseId": "MPREb_lmw", "year": "2024",
           "title": "Music from the Legend of Zelda",
           "artists": [{"name": "London Music Works"}, {"name": "Scott Buckley"}], "thumbnails": []}
    assert collect._hit_from(lmw) is None
    # the artist page named after the game is fine when the wording is official
    hfw = {"resultType": "album", "browseId": "MPREb_hfw", "year": "2022",
           "title": "Horizon Forbidden West (Original Soundtrack)",
           "artists": [{"name": "Horizon Forbidden West"}], "thumbnails": []}
    hit = collect._hit_from(hfw)
    assert hit and hit["composers"] == []
    # ...but a bare self-credit with no soundtrack wording stays out (Lifted)
    band = {"resultType": "album", "browseId": "MPREb_band", "year": "2020",
            "title": "Lifted", "artists": [{"name": "Lifted"}], "thumbnails": []}
    assert collect._hit_from(band) is None
    # Rockstar's "Vol. 2: The Score" phrasing counts as official for VA
    gta = {"resultType": "album", "browseId": "MPREb_gta2", "year": "2013",
           "title": "The Music of Grand Theft Auto V, Vol. 2: The Score",
           "artists": [{"name": "Various Artists"}], "thumbnails": []}
    assert collect._hit_from(gta)
