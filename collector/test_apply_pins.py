"""Pins for titles no leg will revisit: the row is built from the stored
record like a re-walk addition, once, and never over an album in use."""
import json

import apply_pins
import collect

SEEN = "2026-09-18T03:00:00Z"
HEIST = {"medium": "tv", "id": "71446", "name": "Money Heist", "original": "La casa de papel", "date": "2017-05-02",
         "years": [2017, 2019, 2021], "composers": ["Iván M. Lacámara", "Manel Santisteban"], "aliases": [],
         "genres": ["Crime", "Drama"], "poster": "/heist.jpg", "votes": 19671, "accepted": [], "seen": {}, "albums": {},
         "results": [{"resultType": "album", "browseId": "MPREb_ciao", "year": "2024",
                      "title": "Ciao Bella: La Casa de Papel Symphonic (Original Motion Picture Soundtrack) (Extended Versions)",
                      "thumbnails": [{"url": "https://yt3/ciao-small", "width": 60}, {"url": "https://yt3/ciao", "width": 544}],
                      "artists": [{"name": "Iván M. Lacámara"}]}]}
OVERRIDES = {"tv": [{"tmdb": 71446, "season": None, "name": "Money Heist", "album": "MPREb_ciao",
                     "albumTitle": "Ciao Bella: La Casa de Papel Symphonic", "why": "title gate"},
                    {"tmdb": 99999, "season": None, "name": "No Record", "album": "MPREb_none", "why": "x"}]}


def _existing():
    return [{"id": "tv-berlin", "title": "Berlin Soundtrack", "medium": "tv", "game": "Berlin", "date": "2023-12-29",
             "composers": [], "ytmAlbumUrl": "https://music.youtube.com/browse/MPREb_berlin",
             "sources": [{"name": "tmdb-tv", "type": "catalog", "url": "https://www.themoviedb.org/tv/207332", "seenAt": SEEN}]}]


def test_a_pinned_title_with_no_row_gets_one_like_a_rewalk_addition():
    releases, logs = _existing(), []
    added = apply_pins.apply_pins(releases, OVERRIDES, {("tv", "71446"): HEIST}, SEEN, log=logs.append)
    assert added == ["tv-money-heist"]
    r = releases[-1]
    assert r["title"] == "Money Heist Soundtrack" and r["game"] == "Money Heist" and r["medium"] == "tv"
    assert r["albumTitle"].startswith("Ciao Bella") and r["ytmAlbumUrl"] == "https://music.youtube.com/browse/MPREb_ciao"
    assert r["composers"] == ["Iván M. Lacámara", "Manel Santisteban"] and r["date"] == "2017-05-02"
    assert r["art"] == "https://yt3/ciao" and r["genres"] == ["Crime", "Drama"]
    assert r["sources"][0]["url"] == "https://www.themoviedb.org/tv/71446" and "weakMatch" not in r
    assert any("No Record (tv 99999): no stored record, skipped" in x for x in logs)


def test_a_second_run_adds_nothing_and_a_worn_album_is_never_taken():
    releases = _existing()
    apply_pins.apply_pins(releases, OVERRIDES, {("tv", "71446"): HEIST}, SEEN, log=lambda *_: None)
    assert apply_pins.apply_pins(releases, OVERRIDES, {("tv", "71446"): HEIST}, SEEN, log=lambda *_: None) == []
    worn = _existing()
    worn[0]["ytmAlbumUrl"] = "https://music.youtube.com/browse/MPREb_ciao"
    assert apply_pins.apply_pins(worn, OVERRIDES, {("tv", "71446"): HEIST}, SEEN, log=lambda *_: None) == []
    assert len(worn) == 1


def test_a_title_with_no_stored_record_is_looked_up_once_and_kept(tmp_path):
    bake = dict(HEIST, id="34549", name="The Great British Bake Off", original="The Great British Bake Off",
                date="2010-08-17", composers=[], genres=["Reality"],
                results=[dict(HEIST["results"][0], browseId="MPREb_bake", title="Great British Bake Off",
                              artists=[{"name": "Tom Howe"}])])
    overrides = {"tv": OVERRIDES["tv"][:1] + [{"tmdb": 34549, "season": None, "name": "The Great British Bake Off",
                                                "album": "MPREb_bake", "albumTitle": "Great British Bake Off", "why": "x"}]}
    calls = []
    def fetch(medium, tid, releases):
        calls.append((medium, tid))
        return bake
    shard = tmp_path / "eval-pins.json"
    releases, evaluations = _existing(), {("tv", "71446"): HEIST}
    assert apply_pins.fetch_records(releases, overrides, evaluations, fetch=fetch, shard=shard, log=lambda *_: None) == 1
    assert calls == [("tv", "34549")]  # Money Heist has its stored record: never looked up
    assert json.loads(shard.read_text(encoding="utf-8"))[0]["id"] == "34549"
    added = apply_pins.apply_pins(releases, overrides, evaluations, SEEN, log=lambda *_: None)
    assert added == ["tv-money-heist", "tv-the-great-british-bake-off"]
    bake_row = releases[-1]
    assert bake_row["composers"] == ["Tom Howe"] and bake_row["date"] == "2010-08-17"  # no TMDb composer: the album's act
    assert apply_pins.fetch_records(releases, overrides, evaluations, fetch=fetch, shard=shard, log=lambda *_: None) == 0
    assert calls == [("tv", "34549")]  # its row exists now: nothing looked up again


def test_only_limits_the_run_to_the_named_titles():
    releases = _existing()
    assert apply_pins.apply_pins(releases, OVERRIDES, {("tv", "71446"): HEIST}, SEEN, only={"12345"}, log=lambda *_: None) == []
    assert len(releases) == 1


def test_a_pin_for_an_album_the_search_never_showed_reads_its_page():
    """A search returns eight albums, so a pinned later season is usually not
    among them: its own page has to give the act, the art and the title."""
    p = {"tmdb": 73544, "season": 3, "name": "Warrior", "album": "MPREb_U2hJBOqYuD9",
         "albumTitle": "Warrior, Season 3 (Original Series Soundtrack)", "why": "x"}
    page = {"title": "Warrior, Season 3 (Original Series Soundtrack)", "year": "2023",
            "artists": [{"name": "Reza Safinia"}, {"name": "H. Scott Salinas"}],
            "thumbnails": [{"url": "https://yt3/warrior-small", "width": 226},
                           {"url": "https://yt3/warrior", "width": 544}]}
    read = []
    def album_fn(bid):
        read.append(bid)
        return page
    info = {"medium": "tv", "composers": [], "aliases": []}   # TMDb credits Warrior no composer
    c = collect.pin_candidate(p, info, [], album_fn)
    assert read == ["MPREb_U2hJBOqYuD9"] and c["title"] == page["title"] and c["year"] == "2023"
    assert c["art"] == "https://yt3/warrior" and c["season"] == 3
    assert c["composers"] == ["Reza Safinia", "H. Scott Salinas"] and c["composersFrom"] == "album"
    # the search's own result still wins, and no page is read for it
    read.clear()
    result = dict(page, browseId=p["album"], title="Warrior S3", thumbnails=[{"url": "https://yt3/s", "width": 60}])
    c = collect.pin_candidate(p, info, [result], album_fn)
    assert read == [] and c["title"] == "Warrior S3" and c["art"] == "https://yt3/s"
    # no reader at all: the pin's own words, as before
    c = collect.pin_candidate(p, info, [])
    assert c["title"] == p["albumTitle"] and c["art"] is None and c["composers"] == []
