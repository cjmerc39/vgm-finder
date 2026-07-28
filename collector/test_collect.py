"""Collector tests. Fixtures are verbatim copies of real source responses
captured 2026-07-28; counts below are locked to those files."""
import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import pytest

import collect

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 7, 28, 10, 0, 0, tzinfo=timezone.utc)
SEEN = "2026-07-28T10:00:00Z"

FEED_FILES = {
    "https://nowplaying.cool/rss/": "nowplaying-feed.xml",
    "https://blipblop.net/feed/": "blipblop-feed.xml",
    "https://www.vgmonline.net/feed/": "vgmo-feed.xml",
    "https://www.reddit.com/r/gamemusic/top/.rss?t=week": "gamemusic-top-week.atom",
}


def load_feed(name):
    return feedparser.parse((FIXTURES / name).read_bytes())


def fixture_fetch(url):
    return (FIXTURES / FEED_FILES[url]).read_bytes()


def src(name="test", type="editorial"):
    return {"name": name, "type": type}


# ---------------- per-source parsing ----------------

def test_nowplaying_keeps_ost_and_vinyl_only():
    items = collect.parse_nowplaying(load_feed("nowplaying-feed.xml"))
    assert len(items) == 10  # 15 in feed, 5 are News (singles/previews)
    titles = " | ".join(i["title"] for i in items)
    assert "UNBEATABLE" in titles
    assert "Mina the Hollower" in titles  # Vinyl category included
    assert "Splatoon Raiders" not in titles  # News category excluded
    assert all(i["url"].startswith("https://nowplaying.cool/") for i in items)
    assert all(i["date"] for i in items)


def test_blipblop_keeps_confirmed_release_only():
    items = collect.parse_blipblop(load_feed("blipblop-feed.xml"))
    assert len(items) == 9  # 10 in feed; the Sonic Frontiers EP campaign isn't a confirmed release
    titles = " | ".join(i["title"] for i in items)
    assert "Plague Tale" in titles
    assert "TJ Davis" not in titles


def test_vgmo_keeps_news_and_album_reviews_only():
    items = collect.parse_vgmo(load_feed("vgmo-feed.xml"))
    assert len(items) == 5  # 10 in feed, 5 are Editorials
    titles = " | ".join(i["title"] for i in items)
    assert "NieR:Piano Journeys" in titles
    assert "Listener" not in titles  # the Listener's Guide editorials


def test_gamemusic_takes_top_ten():
    items = collect.parse_gamemusic(load_feed("gamemusic-top-week.atom"))
    assert len(items) == 10
    assert all(i["url"].startswith("https://www.reddit.com/r/gamemusic/") for i in items)
    assert all(i["date"] for i in items)


# ---------------- slugs and normalization ----------------

@pytest.mark.parametrize("title,slug", [
    ("Chrono Trigger OST", "chrono-trigger"),
    ("DOOM: The Dark Ages (Original Game Soundtrack)", "doom-the-dark-ages"),
    ("Hades II - Original Soundtrack", "hades-ii"),
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
                  src("a", type="community"), SEEN)
    entry = releases[0]
    assert set(entry) == {"id", "title", "game", "composers", "date", "sources",
                          "ytmSearchUrl", "ytmAlbumUrl", "art", "notable"}
    assert entry["game"] is None and entry["composers"] == []
    assert entry["ytmAlbumUrl"] is None and entry["art"] is None and entry["notable"] is True
    assert entry["sources"][0] == {"name": "a", "type": "community",
                                   "url": "https://a.example/tunic", "seenAt": SEEN}


# ---------------- end to end against all fixtures ----------------

def test_run_collects_all_sources_and_is_stable(tmp_path):
    data_path = tmp_path / "releases.json"
    assert collect.run(fetch_fn=fixture_fetch, data_path=data_path, now=NOW) == 0
    data = json.loads(data_path.read_text(encoding="utf-8"))
    assert data["updatedAt"] == SEEN
    assert len(data["releases"]) == 34  # 10 + 9 + 5 + 10, no cross-source collisions in these fixtures
    assert all(r["notable"] for r in data["releases"])
    community = [r for r in data["releases"] if r["sources"][0]["type"] == "community"]
    assert len(community) == 10

    # a second run over identical feeds must not rewrite the file
    first = data_path.read_text(encoding="utf-8")
    later = datetime(2026, 7, 29, 10, 0, 0, tzinfo=timezone.utc)
    assert collect.run(fetch_fn=fixture_fetch, data_path=data_path, now=later) == 0
    assert data_path.read_text(encoding="utf-8") == first


def test_run_survives_one_source_failing(tmp_path, capsys):
    def flaky(url):
        if "reddit" in url:
            raise OSError("simulated network failure")
        return fixture_fetch(url)
    data_path = tmp_path / "releases.json"
    assert collect.run(fetch_fn=flaky, data_path=data_path, now=NOW) == 0
    out = capsys.readouterr().out
    assert "::warning::r/gamemusic failed" in out
    assert len(json.loads(data_path.read_text(encoding="utf-8"))["releases"]) == 24


def test_run_fails_red_when_every_source_fails(tmp_path, capsys):
    def dead(url):
        raise OSError("nope")
    assert collect.run(fetch_fn=dead, data_path=tmp_path / "releases.json", now=NOW) == 1
    assert "::error::" in capsys.readouterr().out
