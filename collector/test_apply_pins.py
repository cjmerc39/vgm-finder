"""Pins for titles no leg will revisit: the row is built from the stored
record like a re-walk addition, once, and never over an album in use."""
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


def test_only_limits_the_run_to_the_named_titles():
    releases = _existing()
    assert apply_pins.apply_pins(releases, OVERRIDES, {("tv", "71446"): HEIST}, SEEN, only={"12345"}, log=lambda *_: None) == []
    assert len(releases) == 1
