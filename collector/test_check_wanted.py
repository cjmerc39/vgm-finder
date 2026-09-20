"""The wanted list: a title searched again every run, added by itself the
run its album appears, and never searched after that."""
import json
from pathlib import Path

import check_wanted
import collect

SEEN = "2026-09-19T03:00:00Z"
TODAY = "2026-09-19"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
YTM_SCREEN = json.loads((FIXTURES / "ytm-screen.json").read_text(encoding="utf-8"))
OPPIE = {"id": 872585, "title": "Oppenheimer", "original_title": "Oppenheimer", "release_date": "2023-07-19",
         "genre_ids": [18, 36], "poster_path": "/oppie.jpg", "vote_count": 10100}


def resolve(query, limit=8):
    return YTM_SCREEN.get(query, [])


def nothing(query, limit=8):
    return []


def album(bid):
    return {"title": "Oppenheimer (Original Motion Picture Soundtrack)", "trackCount": 24,
            "artists": [{"name": "Ludwig Göransson"}], "tracks": []}


def _wanted(**over):
    t = {"medium": "film", "tmdb": "872585", "name": "Oppenheimer", "asked": "2026-09-01"}
    t.update(over)
    return {"titles": [t]}


def _patch(monkeypatch, entry=OPPIE, composers=("Ludwig Göransson",)):
    monkeypatch.setattr(collect, "tmdb_credits", lambda kind, tid: (list(composers), []))
    monkeypatch.setattr(collect, "_tmdb_genre_map", lambda kind: {18: "Drama", 36: "History"})
    monkeypatch.setattr(collect, "load_screen_overrides", lambda *a, **k: {})
    return lambda medium, tid: dict(entry)


def test_a_wanted_title_whose_album_appears_gets_a_row_and_is_never_searched_again(monkeypatch):
    details = _patch(monkeypatch)
    releases, wanted, logs = [], _wanted(), []
    out = check_wanted.check(releases, wanted, SEEN, today=TODAY, resolve=resolve, album_fn=album,
                             details=details, tracks=False, log=logs.append)
    assert len(releases) == 1 and releases[0]["id"] == "film-oppenheimer"
    r = releases[0]
    assert r["medium"] == "film" and r["game"] == "Oppenheimer" and r["date"] == "2023-07-19"
    assert r["ytmAlbumUrl"].endswith("MPREb_Bl1qkU0q9XP") and r["genres"] == ["Drama", "History"]
    assert r["sources"][0]["url"] == "https://www.themoviedb.org/movie/872585"
    assert wanted["titles"][0]["got"] == TODAY and wanted["titles"][0]["rows"] == ["film-oppenheimer"]
    assert out["waiting"] == 0 and len(out["landed"]) == 1
    # a second run asks nothing at all: the entry is done
    asked = []
    check_wanted.check(releases, wanted, SEEN, today=TODAY, resolve=lambda q, limit=8: asked.append(q) or [],
                       album_fn=album, details=lambda *a: 1 / 0, tracks=False, log=logs.append)
    assert asked == [] and len(releases) == 1


def test_a_title_with_no_album_yet_is_counted_and_waits(monkeypatch):
    details = _patch(monkeypatch)
    releases, wanted, logs = [], _wanted(), []
    out = check_wanted.check(releases, wanted, SEEN, today=TODAY, resolve=nothing, album_fn=album,
                             details=details, tracks=False, log=logs.append)
    assert releases == [] and out["waiting"] == 1 and out["landed"] == []
    assert wanted["titles"][0]["checks"] == 1 and wanted["titles"][0]["checked"] == TODAY
    assert any("still nothing on YT Music" in x for x in logs)
    check_wanted.check(releases, wanted, SEEN, today="2026-09-20", resolve=nothing, album_fn=album,
                       details=details, tracks=False, log=logs.append)
    assert wanted["titles"][0]["checks"] == 2 and wanted["titles"][0]["checked"] == "2026-09-20"


def test_a_row_that_arrived_another_way_closes_the_entry_without_a_search(monkeypatch):
    _patch(monkeypatch)
    releases = [{"id": "film-oppenheimer", "title": "Oppenheimer Soundtrack", "medium": "film",
                 "ytmAlbumUrl": "https://music.youtube.com/browse/MPREb_Bl1qkU0q9XP",
                 "sources": [{"name": "tmdb-film", "type": "catalog",
                              "url": "https://www.themoviedb.org/movie/872585", "seenAt": SEEN}]}]
    wanted, logs = _wanted(), []
    out = check_wanted.check(releases, wanted, SEEN, today=TODAY, resolve=nothing, album_fn=album,
                             details=lambda *a: 1 / 0, tracks=False, log=logs.append)
    assert wanted["titles"][0]["got"] == TODAY and out["waiting"] == 0
    assert any("already has a row" in x for x in logs)
    # a retired row holds no claim: the title keeps waiting
    releases[0]["retired"] = True
    again = _wanted()
    check_wanted.check(releases, again, SEEN, today=TODAY, resolve=nothing, album_fn=album,
                       details=_patch(monkeypatch), tracks=False, log=logs.append)
    assert "got" not in again["titles"][0]


def test_a_mistyped_id_is_reported_and_the_entry_left_alone(monkeypatch):
    details = _patch(monkeypatch, entry=dict(OPPIE, title="Oppenheimer: The Real Story",
                                             original_title="Oppenheimer: The Real Story"))
    releases, wanted, logs = [], _wanted(name="Oppenheimer"), []
    out = check_wanted.check(releases, wanted, SEEN, today=TODAY, resolve=resolve, album_fn=album,
                             details=details, tracks=False, log=logs.append)
    assert releases == [] and len(out["skipped"]) == 1 and "checks" not in wanted["titles"][0]
    assert any("does not match TMDb" in x for x in logs)


def test_an_album_another_row_wears_is_never_taken(monkeypatch):
    details = _patch(monkeypatch)
    releases = [{"id": "oppenheimer", "title": "Oppenheimer Soundtrack", "medium": "game",
                 "ytmAlbumUrl": "https://music.youtube.com/browse/MPREb_Bl1qkU0q9XP",
                 "sources": [{"name": "igdb", "type": "catalog", "url": "https://igdb.com/games/oppenheimer",
                              "seenAt": SEEN}]}]
    wanted, logs = _wanted(), []
    out = check_wanted.check(releases, wanted, SEEN, today=TODAY, resolve=resolve, album_fn=album,
                             details=details, tracks=False, log=logs.append)
    assert len(releases) == 1 and "got" not in wanted["titles"][0] and len(out["skipped"]) == 1
    assert any("already worn by oppenheimer" in x for x in logs)


def test_an_album_matched_on_plays_alone_is_reported_not_taken():
    # a wanted title takes only the match a leg would call exact: the plays-only
    # class is the likeliest wrong answer after years with no soundtrack at all
    weak = {"albumTitle": "Heroes", "ytmAlbumUrl": "https://music.youtube.com/browse/MPREb_weak",
            "weakMatch": True}
    solid = {"albumTitle": "Heroes (Original Television Soundtrack)",
             "ytmAlbumUrl": "https://music.youtube.com/browse/MPREb_solid"}
    logs = []
    keep, why = check_wanted._winnowed([weak], [], "Heroes", logs.append)
    assert keep == [] and "matches on plays alone" in why
    assert any("pin it in screen-overrides.json" in x for x in logs)
    keep, why = check_wanted._winnowed([weak, solid], [], "Heroes", lambda *_: None)
    assert keep == [solid] and why is None   # one bad candidate never blocks a good one


def test_the_name_guard_forgives_a_studio_possessive():
    cage = {"id": 62126, "name": "Marvel's Luke Cage", "original_name": "Marvel's Luke Cage"}
    assert check_wanted._same_title("Luke Cage", cage)          # the list may drop the studio
    assert check_wanted._same_title("Marvel's Luke Cage", cage)  # or keep it
    assert check_wanted._same_title("", cage)                    # no name stored: no guard
    assert not check_wanted._same_title("Iron Fist", cage)       # a different show is still caught


def test_a_lookup_that_fails_is_a_warning_not_a_crash(monkeypatch):
    _patch(monkeypatch)
    def boom(medium, tid):
        raise RuntimeError("TMDb 503")
    releases, wanted, logs = [], _wanted(), []
    out = check_wanted.check(releases, wanted, SEEN, today=TODAY, resolve=resolve, album_fn=album,
                             details=boom, tracks=False, log=logs.append)
    assert out["skipped"] and out["waiting"] == 1 and "checks" not in wanted["titles"][0]
    assert any("TMDb 503" in x for x in logs)


def test_only_limits_the_run_and_add_refuses_junk(monkeypatch):
    details = _patch(monkeypatch)
    releases, wanted = [], _wanted()
    check_wanted.check(releases, wanted, SEEN, today=TODAY, only={"999"}, resolve=resolve, album_fn=album,
                       details=details, tracks=False, log=lambda *_: None)
    assert releases == [] and "checks" not in wanted["titles"][0]
    added = check_wanted.add(wanted, ["tv/1639"], today=TODAY, details=lambda m, t: {"id": 1639, "name": "Heroes"})
    assert added == [{"medium": "tv", "tmdb": "1639", "asked": TODAY, "name": "Heroes"}]
    assert check_wanted.add(wanted, ["tv/1639"], today=TODAY, details=lambda m, t: {"id": 1639}) == []
    for junk in ("1639", "show/1639", "tv/heroes"):
        try:
            check_wanted.add(wanted, [junk], today=TODAY, details=lambda m, t: {})
        except SystemExit:
            continue
        raise AssertionError(junk)


def test_the_list_on_disk_reads_and_round_trips(tmp_path):
    path = tmp_path / "wanted.json"
    path.write_text(json.dumps({"titles": [{"medium": "film", "tmdb": "559", "name": "Spider-Man 3"},
                                           {"medium": "game", "tmdb": "1"}, {"medium": "film"}, "junk"]}),
                    encoding="utf-8")
    wanted = check_wanted.load_wanted(path)
    assert [t["tmdb"] for t in wanted["titles"]] == ["559"]   # games and idless entries are not screen titles
    check_wanted.save_wanted(wanted, path)
    assert check_wanted.load_wanted(path) == wanted
    shipped = check_wanted.load_wanted()
    assert shipped["titles"] and all(t.get("name") and t.get("asked") for t in shipped["titles"])
