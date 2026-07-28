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
}
STEAM_URL = next(s["url"] for s in collect.SOURCES if s["name"] == "steam")
FEED_FILES[STEAM_URL] = "steam-soundtracks.json"


def raw(name):
    return (FIXTURES / name).read_bytes()


def fixture_fetch(url):
    return raw(FEED_FILES[url])


def src(name="test", type="editorial"):
    return {"name": name, "type": type}


# ---------------- per-source parsing ----------------

def test_nowplaying_keeps_ost_and_vinyl_only():
    items = collect.parse_nowplaying(raw("nowplaying-feed.xml"))
    assert len(items) == 10  # 15 in feed, 5 are News (singles/previews)
    titles = " | ".join(i["title"] for i in items)
    assert "UNBEATABLE" in titles
    assert "Mina the Hollower" in titles  # Vinyl category included
    assert "Splatoon Raiders" not in titles  # News category excluded
    assert all(i["url"].startswith("https://nowplaying.cool/") for i in items)
    assert all(i["date"] for i in items)


def test_blipblop_keeps_confirmed_release_only():
    items = collect.parse_blipblop(raw("blipblop-feed.xml"))
    assert len(items) == 9  # 10 in feed; the Sonic Frontiers EP campaign isn't a confirmed release
    titles = " | ".join(i["title"] for i in items)
    assert "Plague Tale" in titles
    assert "TJ Davis" not in titles


def test_vgmo_keeps_news_and_album_reviews_only():
    items = collect.parse_vgmo(raw("vgmo-feed.xml"))
    assert len(items) == 5  # 10 in feed, 5 are Editorials
    titles = " | ".join(i["title"] for i in items)
    assert "NieR:Piano Journeys" in titles
    assert "Listener" not in titles  # the Listener's Guide editorials


def test_steam_parses_search_rows():
    items = collect.parse_steam(raw("steam-soundtracks.json"))
    assert len(items) == 25
    assert items[0]["title"] == "Endacopia Soundtrack"
    assert items[0]["url"].startswith("https://store.steampowered.com/app/")
    assert "?" not in items[0]["url"]  # tracking query stripped so reruns dedupe
    assert all(i["date"] and i["date"].startswith("2026-") for i in items)
    assert items[0]["date"] == "2026-07-28"


def test_steam_skips_unreleased_rows():
    blob = json.dumps({"success": 1, "results_html":
        '<a href="https://store.steampowered.com/app/1/A/?snr=x" class="search_result_row">'
        '<span class="title">Real Album Soundtrack</span>'
        '<div class="search_released">Jul 20, 2026</div></a>'
        '<a href="https://store.steampowered.com/app/2/B/" class="search_result_row">'
        '<span class="title">Vapor Soundtrack</span>'
        '<div class="search_released">Coming soon</div></a>'}).encode()
    items = collect.parse_steam(blob)
    assert [i["title"] for i in items] == ["Real Album Soundtrack"]
    assert items[0]["date"] == "2026-07-20"
    assert items[0]["url"] == "https://store.steampowered.com/app/1/A/"


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
    ("OST", "ost"),  # a title that is only a suffix survives as itself
])
def test_slugify(title, slug):
    assert collect.slugify(title) == slug


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
    assert collect.run(fetch_fn=fixture_fetch, data_path=data_path, now=NOW) == 0
    data = json.loads(data_path.read_text(encoding="utf-8"))
    assert data["updatedAt"] == SEEN
    assert len(data["releases"]) == 49  # 10 + 9 + 5 + 25, no cross-source collisions in these fixtures
    assert all(r["notable"] for r in data["releases"])
    catalog = [r for r in data["releases"] if r["sources"][0]["type"] == "catalog"]
    assert len(catalog) == 25

    # a second run over identical feeds must not rewrite the file
    first = data_path.read_text(encoding="utf-8")
    later = datetime(2026, 7, 29, 10, 0, 0, tzinfo=timezone.utc)
    assert collect.run(fetch_fn=fixture_fetch, data_path=data_path, now=later) == 0
    assert data_path.read_text(encoding="utf-8") == first


def test_run_survives_one_source_failing(tmp_path, capsys):
    def flaky(url):
        if "blipblop" in url:
            raise OSError("simulated network failure")
        return fixture_fetch(url)
    data_path = tmp_path / "releases.json"
    assert collect.run(fetch_fn=flaky, data_path=data_path, now=NOW) == 0
    out = capsys.readouterr().out
    assert "::warning::blipblop failed" in out
    assert len(json.loads(data_path.read_text(encoding="utf-8"))["releases"]) == 40


def test_run_fails_red_when_every_source_fails(tmp_path, capsys):
    def dead(url):
        raise OSError("nope")
    assert collect.run(fetch_fn=dead, data_path=tmp_path / "releases.json", now=NOW) == 1
    assert "::error::" in capsys.readouterr().out
