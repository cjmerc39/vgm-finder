"""Screen re-walk (MATCHER-FIX-SPEC Phase 2): evaluate, resolve, apply.

YouTube Music answers come from fixtures/ytm-screen-rules.json, the live
capture the Phase 1 rules were verified against; TMDb is a small fake.
"""
import json
from pathlib import Path

import pytest

import collect
import rewalk
from test_collect import SEEN

RULES = json.loads((Path(__file__).parent / "fixtures" / "ytm-screen-rules.json")
                   .read_text(encoding="utf-8"))


def rules_resolve(query, limit=5):
    return RULES.get(query, [])


def url_of(query, prefix):
    hit = next(r for r in RULES[query] if r["title"].startswith(prefix))
    return "https://music.youtube.com/browse/" + hit["browseId"]


PT3 = url_of("Back to the Future soundtrack", "Back To The Future, Pt. 3")
EXPANDED = url_of("Back to the Future soundtrack", "Back To The Future (Original Motion Picture Soundtrack")
SUITE = url_of("The Empire Strikes Back soundtrack", "The Empire Strikes Back (Symphonic Suite")
EMPIRE_OST = url_of("The Empire Strikes Back soundtrack", "Star Wars: The Empire Strikes Back")
NOCTURNE_S2 = url_of("Castlevania soundtrack", "Castlevania Nocturne Season 2")
CASTLEVANIA_GAME = url_of("Castlevania soundtrack", "Castlevania Original Soundtrack")
LOST_WORLD = url_of("The Lost World: Jurassic Park soundtrack", "The Lost World: Jurassic Park (Original")

FILMS = {
    105: {"title": "Back to the Future", "release_date": "1985-07-03", "composer": (37, "Alan Silvestri")},
    196: {"title": "Back to the Future Part III", "release_date": "1990-05-25", "composer": (37, "Alan Silvestri")},
    1891: {"title": "The Empire Strikes Back", "release_date": "1980-05-20", "composer": (491, "John Williams")},
    330: {"title": "The Lost World: Jurassic Park", "release_date": "1997-05-23", "composer": (491, "John Williams")},
    999: {"title": "Unseen Film", "release_date": "2001-01-01", "composer": (7, "Nobody Known")},
}


def film_entry(fid):
    f = FILMS[fid]
    return {"id": fid, "title": f["title"], "original_title": f["title"], "release_date": f["release_date"],
            "genre_ids": [12], "poster_path": f"/{fid}.jpg", "vote_count": 5000}


CASTLEVANIA = {"id": 71024, "name": "Castlevania", "original_name": "Castlevania",
               "first_air_date": "2017-07-07", "genre_ids": [16], "poster_path": "/cv.jpg", "vote_count": 1605}
CASTLEVANIA_SEASONS = [{"season_number": n, "air_date": d} for n, d in
                       ((1, "2017-07-07"), (2, "2018-10-26"), (3, "2020-03-05"), (4, "2021-05-13"))]


@pytest.fixture
def fake_tmdb(monkeypatch):
    monkeypatch.setattr(collect, "_TMDB_GMAP", {})
    monkeypatch.setattr(collect, "_PERSON_AKA", {})
    asked = []

    def tmdb(path, **params):
        asked.append(path)
        if path == "genre/movie/list":
            return {"genres": [{"id": 12, "name": "Adventure"}]}
        if path == "genre/tv/list":
            return {"genres": [{"id": 16, "name": "Animation"}]}
        if path == "discover/movie":
            # the page walk sees three films; Lost World and the unseen film
            # only reach the re-walk through their catalog rows
            return {"results": [film_entry(i) for i in (105, 196, 1891)], "total_pages": 1}
        if path == "discover/tv":
            return {"results": [CASTLEVANIA], "total_pages": 1}
        if path.startswith("person/"):
            return {"also_known_as": []}
        if path.startswith("movie/") and path.endswith("/credits"):
            pid, name = FILMS[int(path.split("/")[1])]["composer"]
            return {"crew": [{"id": pid, "name": name, "job": "Original Music Composer"}]}
        if path.startswith("movie/"):
            fid = int(path.split("/")[1])
            e = film_entry(fid)
            return dict(e, genres=[{"id": 12, "name": "Adventure"}])
        if path == "tv/71024/aggregate_credits":
            return {"crew": [{"id": 100, "name": "Trevor Morris", "jobs": [{"job": "Original Music Composer"}]}]}
        if path == "tv/71024":
            return dict(CASTLEVANIA, genres=[{"id": 16, "name": "Animation"}], seasons=CASTLEVANIA_SEASONS)
        raise AssertionError("unexpected TMDb path " + path)

    monkeypatch.setattr(collect, "_tmdb_get", tmdb)
    return asked


def row(rid, medium, title, album, url, tmdb, **extra):
    kind = "movie" if medium == "film" else "tv"
    base = {"id": rid, "title": title, "medium": medium, "game": title, "composers": [],
            "date": "2000-01-01", "albumTitle": album, "ytmAlbumUrl": url, "art": None, "notable": True,
            "ytmSearchUrl": "https://music.youtube.com/search?q=x",
            "sources": [{"name": f"tmdb-{medium}", "type": "catalog",
                         "url": f"https://www.themoviedb.org/{kind}/{tmdb}", "seenAt": SEEN}]}
    base.update(extra)
    return base


def catalog():
    return [
        {"id": "castlevania-symphony-of-the-night", "title": "Castlevania Original Soundtrack",
         "medium": "game", "game": "Castlevania: Symphony of the Night", "composers": [], "date": "1997-03-20",
         "ytmAlbumUrl": CASTLEVANIA_GAME, "sources": [], "notable": True},
        row("film-back-to-the-future", "film", "Back to the Future Soundtrack",
            "Back To The Future, Pt. 3 (Original Motion Picture Score)", PT3, 105,
            tracksN=12, playsTotal=1000, ytmPlaylistId="OLAK5uy_pt3"),
        row("film-the-empire-strikes-back", "film", "The Empire Strikes Back Soundtrack",
            "The Empire Strikes Back (Symphonic Suite From The Original Motion Picture Score)", SUITE, 1891),
        row("tv-castlevania-season-2", "tv", "Castlevania Season 2 Soundtrack",
            "Castlevania Nocturne Season 2 (Original Series Soundtrack)", NOCTURNE_S2, 71024),
        row("film-the-lost-world-jurassic-park", "film", "The Lost World: Jurassic Park Soundtrack",
            "The Lost World: Jurassic Park (Original Motion Picture Score)", LOST_WORLD, 330),
        row("film-unseen-film", "film", "Unseen Film Soundtrack", "Unseen Film (Score)",
            "https://music.youtube.com/browse/MPREb_unseen", 999),
    ]


def no_plays(browse_id):
    return {"tracks": []}


def evaluate_fully(folder, releases, resolve=rules_resolve, cap=250):
    state = rewalk.load_state(folder)
    for _ in range(20):
        rewalk.evaluate(releases, state, folder, resolve=resolve, album_fn=no_plays, cap=cap)
        if state["phase"] == "evaluated":
            break
    return state


def _core(plan):
    return json.dumps({k: plan[k] for k in ("corrections", "additions", "orphans", "unverified",
                                            "unchanged", "counts")}, sort_keys=True)


# ---------------- evaluate ----------------

def test_evaluate_walks_pages_then_sweeps_rows_below_the_bars(tmp_path, fake_tmdb):
    folder = tmp_path / "rewalk"
    state = evaluate_fully(folder, catalog())
    assert state["phase"] == "evaluated" and state["pending"] == []
    ev = rewalk.load_evaluations(folder)
    assert set(ev) == {("film", "105"), ("film", "196"), ("film", "1891"), ("tv", "71024"),
                       ("film", "330"), ("film", "999")}
    # the sweep reached Lost World through its details, not a discover page
    assert "movie/330" in fake_tmdb and ev[("film", "330")]["accepted"]
    # the verdict on the album each row wears is kept for resolve
    assert "sequel guard" in ev[("film", "105")]["seen"][PT3]
    assert not any(c.get("trackStats") for c in ev[("film", "105")]["accepted"])  # a credited album exists
    castlevania = ev[("tv", "71024")]["accepted"]
    assert castlevania and castlevania[0]["trackStats"] == \
        {"tracks": 0, "named": 0, "distinct": 0, "composerTracks": 0}
    assert ev[("film", "1891")]["seen"][SUITE] == "accepted"
    assert list(folder.glob("eval-*.json"))


def test_evaluate_stops_cleanly_and_resumes_without_repeating(tmp_path, fake_tmdb):
    releases, asked = catalog(), []

    def flaky(query, limit=5):
        asked.append(query)
        if query == "Back to the Future Part III soundtrack" and asked.count(query) == 1:
            raise ConnectionResetError("Connection reset by peer")
        return rules_resolve(query)

    folder = tmp_path / "rewalk"
    state = rewalk.load_state(folder)
    _, stopped = rewalk.evaluate(releases, state, folder, resolve=flaky, album_fn=no_plays)
    assert stopped and "reset" in stopped
    saved = rewalk.load_state(folder)
    assert saved["phase"] == "film" and saved["filmPage"] == 1  # the page never finished
    assert set(rewalk.load_evaluations(folder)) == {("film", "105")}  # finished work was kept
    evaluate_fully(folder, releases, resolve=flaky)
    assert asked.count("Back to the Future soundtrack") == 1  # no title searched twice
    assert rewalk.load_state(folder)["phase"] == "evaluated"


def test_evaluate_respects_the_lookup_cap(tmp_path, fake_tmdb):
    folder = tmp_path / "rewalk"
    state = rewalk.load_state(folder)
    records, _ = rewalk.evaluate(catalog(), state, folder, resolve=rules_resolve, album_fn=no_plays, cap=1)
    assert len(records) == 1 and state["phase"] == "film" and state["filmPage"] == 1


# ---------------- resolve ----------------

def test_resolve_plans_corrections_additions_orphans_and_unverified(tmp_path, fake_tmdb):
    folder = tmp_path / "rewalk"
    releases = catalog()
    evaluate_fully(folder, releases)
    ev = rewalk.load_evaluations(folder)
    plan = rewalk.plan_rewalk(releases, ev)

    corr = {c["row"]: c for c in plan["corrections"]}
    assert set(corr) == {"film-back-to-the-future", "film-the-empire-strikes-back"}
    assert corr["film-back-to-the-future"]["newAlbum"]["url"] == EXPANDED
    assert "sequel guard" in corr["film-back-to-the-future"]["reason"]
    assert corr["film-the-empire-strikes-back"]["newAlbum"]["url"] == EMPIRE_OST
    assert corr["film-the-empire-strikes-back"]["reason"] == "outranked on fewer extra words"

    # Part III takes the album Part I wore, which is free once Part I moves on
    assert [(a["slot"], a["album"]["url"]) for a in plan["additions"]] == [(["film", "196"], PT3)]
    # Castlevania's series has no album of its own and the game keeps its compilation
    assert [o["row"] for o in plan["orphans"]] == ["tv-castlevania-season-2"]
    assert "rule 3" in plan["orphans"][0]["reason"]
    assert [u["row"] for u in plan["unverified"]] == ["film-unseen-film"]
    assert plan["unverified"][0]["reason"] == "current album not in today's search"
    assert [u["row"] for u in plan["unchanged"]] == ["film-the-lost-world-jurassic-park"]
    c = plan["counts"]
    assert (c["corrections"], c["additions"], c["orphans"], c["unverified"], c["unchanged"]) == (2, 1, 1, 1, 1)
    assert c["weakMatch"] == 0 and c["songsAlbum"] == 0


def test_resolve_is_the_same_in_any_processing_order(tmp_path, fake_tmdb):
    folder = tmp_path / "rewalk"
    releases = catalog()
    evaluate_fully(folder, releases)
    ev = rewalk.load_evaluations(folder)
    forward = rewalk.plan_rewalk(releases, ev)
    backward = rewalk.plan_rewalk(list(reversed(releases)), dict(reversed(list(ev.items()))))
    assert _core(forward) == _core(backward)


def _cand(title, url, **kw):
    c = {"title": title, "url": url, "art": None, "rule": "1 exact title", "klass": "exact",
         "credited": True, "extra": 0, "gap": 0, "worded": True, "weak": False, "season": None,
         "composers": ["Someone"], "rank": 0, "artists": ["Someone"], "plays": None}
    c.update(kw)
    return c


def _record(tid, name, accepted, seen=None, medium="film"):
    return {"medium": medium, "id": tid, "name": name, "original": name, "date": "2001-01-01",
            "years": [2001], "composers": ["Someone"], "aliases": [], "genres": None, "poster": None,
            "votes": 1000, "accepted": accepted, "seen": seen or {}}


def test_a_dead_heat_never_corrects_a_row():
    a = _cand("Tie (Original Motion Picture Soundtrack)", "https://music.youtube.com/browse/a", rank=0)
    b = _cand("Tie (Original Score)", "https://music.youtube.com/browse/b", rank=1)
    ev = {("film", "1"): _record("1", "Tie", [a, b], {b["url"]: "accepted"})}
    releases = [row("film-tie", "film", "Tie Soundtrack", b["title"], b["url"], 1)]
    plan = rewalk.plan_rewalk(releases, ev)
    assert plan["counts"]["corrections"] == 0
    assert [u["row"] for u in plan["unchanged"]] == ["film-tie"]


def test_songs_album_and_weak_match_are_counted_at_the_review_stop():
    # track evidence as read live: Pulp Fiction 22 artists, Lion King 15 with
    # Zimmer on 4 of 12, Grand Budapest Desplat on 28 of 32, Chamber of
    # Secrets every track "Various Artists"
    songs = _cand("Pulp Fiction (Music From The Motion Picture)", "https://music.youtube.com/browse/pf",
                  credited=False, artists=["Various Artists"], composers=[],
                  trackStats={"tracks": 20, "named": 20, "distinct": 22, "composerTracks": 0})
    weak = _cand("The Lion King", "https://music.youtube.com/browse/lk", credited=False, worded=False,
                 klass="weak", weak=True, rule="2 bare title by plays (weak)", artists=["Various Artists"],
                 composers=[], trackStats={"tracks": 12, "named": 12, "distinct": 15, "composerTracks": 4})
    score = _cand("Inception (Music from the Motion Picture)", "https://music.youtube.com/browse/in",
                  artists=["Hans Zimmer"])
    budapest = _cand("The Grand Budapest Hotel (Original Soundtrack)", "https://music.youtube.com/browse/gb",
                     credited=False, artists=["Various Artists"],
                     trackStats={"tracks": 32, "named": 32, "distinct": 5, "composerTracks": 28})
    potter = _cand("Harry Potter and The Chamber of Secrets/ Original Motion Picture Soundtrack",
                   "https://music.youtube.com/browse/hp", credited=False, artists=["Various Artists"],
                   trackStats={"tracks": 20, "named": 0, "distinct": 0, "composerTracks": 0})
    ev = {("film", "680"): _record("680", "Pulp Fiction", [songs]),
          ("film", "8587"): _record("8587", "The Lion King", [weak]),
          ("film", "27205"): _record("27205", "Inception", [score]),
          ("film", "120467"): _record("120467", "The Grand Budapest Hotel", [budapest]),
          ("film", "672"): _record("672", "Harry Potter and the Chamber of Secrets", [potter])}
    plan = rewalk.plan_rewalk([], ev)
    flags = {a["title"]["name"]: (a["weakMatch"], a["songsAlbum"], a["songsAlbumLiteral"])
             for a in plan["additions"]}
    assert flags == {"Pulp Fiction": (False, True, True), "The Lion King": (True, True, True),
                     "Inception": (False, False, False),
                     "The Grand Budapest Hotel": (False, False, True),
                     "Harry Potter and the Chamber of Secrets": (False, False, True)}
    c = plan["counts"]
    assert (c["songsAlbum"], c["songsAlbumLiteral"], c["songsAlbumUnknown"], c["weakMatch"]) == (2, 4, 0, 1)


def test_the_weak_path_keeps_various_artists_and_title_named_acts_only():
    cover = _cand("Bohemian Rhapsody", "https://music.youtube.com/browse/rpo", credited=False, worded=False,
                  klass="weak", weak=True, artists=["The Royal Philharmonic Orchestra London",
                                                     "The Royal Choral Society"])
    named = _cand("The Intouchables", "https://music.youtube.com/browse/int", credited=False, worded=False,
                  klass="weak", weak=True, artists=["The Intouchables (Motion Picture Soundtrack)"])
    ev = {("film", "424694"): _record("424694", "Bohemian Rhapsody", [cover]),
          ("film", "77338"): _record("77338", "The Intouchables", [named])}
    plan = rewalk.plan_rewalk([], ev)
    assert [a["title"]["name"] for a in plan["additions"]] == ["The Intouchables"]
    assert plan["counts"]["weakDroppedByArtistGuard"] == 1
    assert plan["weakDropped"][0]["album"] == "Bohemian Rhapsody"


def test_track_stats_count_named_artists_and_the_composer():
    album = {"tracks": [
        {"title": "a", "artists": [{"name": "Alexandre Desplat"}]},
        {"title": "b", "artists": [{"name": "Alexandre Desplat"}]},
        {"title": "c", "artists": [{"name": "Osipov State Russian Folk Orchestra"}]},
        {"title": "d", "artists": [{"name": "Various Artists"}]}]}
    assert rewalk.track_stats(album, ["Alexandre Desplat"]) == \
        {"tracks": 4, "named": 3, "distinct": 2, "composerTracks": 2}


def test_songs_album_detection():
    assert collect.is_songs_album({"credited": False, "artists": ["Various Artists"], "title": "The Lion King"})
    assert collect.is_songs_album({"credited": False, "artists": ["Urge Overkill", "Dusty Springfield"],
                                   "title": "Pulp Fiction (Music From The Motion Picture)"})
    assert not collect.is_songs_album({"credited": True, "artists": ["Hans Zimmer"],
                                       "title": "Inception (Music from the Motion Picture)"})
    assert not collect.is_songs_album({"credited": False, "artists": ["Infinity Train"],
                                       "title": "Infinity Train: Book 1 (Original Soundtrack)"})


# ---------------- apply ----------------

def test_apply_corrects_adds_retires_and_resets_checked_sets(tmp_path, fake_tmdb):
    folder = tmp_path / "rewalk"
    releases = catalog()
    evaluate_fully(folder, releases)
    ev = rewalk.load_evaluations(folder)
    plan = rewalk.plan_rewalk(releases, ev)
    tracks = tmp_path / "tracks"
    tracks.mkdir()
    (tracks / "film-back-to-the-future.json").write_text("[]", encoding="utf-8")
    bstate = tmp_path / "backfill-state.json"

    out = rewalk.apply_plan(releases, plan, ev, bstate, tracks, SEEN)
    by = {r["id"]: r for r in releases}
    bttf = by["film-back-to-the-future"]
    assert bttf["ytmAlbumUrl"] == EXPANDED and bttf["albumTitle"].startswith("Back To The Future (Original")
    assert not any(k in bttf for k in ("tracksN", "playsTotal", "ytmPlaylistId"))
    assert not (tracks / "film-back-to-the-future.json").exists()  # refetched on the next fill
    assert by["film-the-empire-strikes-back"]["ytmAlbumUrl"] == EMPIRE_OST
    assert by["tv-castlevania-season-2"]["retired"] is True
    assert by["tv-castlevania-season-2"]["ytmAlbumUrl"] == NOCTURNE_S2  # kept for the listener's history
    assert NOCTURNE_S2 not in collect.claimed_albums(releases)       # but it no longer holds the album
    assert out["added"] == ["film-back-to-the-future-part-iii"]
    assert by["film-back-to-the-future-part-iii"]["ytmAlbumUrl"] == PT3
    assert by["film-back-to-the-future-part-iii"]["medium"] == "film"
    assert out["stale"] == [] and len(out["corrected"]) == 2 and out["retired"] == ["tv-castlevania-season-2"]
    assert by["film-unseen-film"]["ytmAlbumUrl"] == "https://music.youtube.com/browse/MPREb_unseen"
    state = json.loads(bstate.read_text(encoding="utf-8"))
    assert state["tmdbFilmChecked"] == [105, 196, 330, 999, 1891] and state["tmdbTvChecked"] == [71024]
    assert len(releases) == 7  # nothing deleted: one row added, TRACK numbers unmoved
    assert [r["id"] for r in releases[:6]] == [r["id"] for r in catalog()]


def test_apply_skips_anything_that_moved_since_resolve(tmp_path, fake_tmdb):
    folder = tmp_path / "rewalk"
    releases = catalog()
    evaluate_fully(folder, releases)
    ev = rewalk.load_evaluations(folder)
    plan = rewalk.plan_rewalk(releases, ev)
    # the daily run touched the Empire row after resolve
    next(r for r in releases if r["id"] == "film-the-empire-strikes-back")["ytmAlbumUrl"] = \
        "https://music.youtube.com/browse/MPREb_hand_attached"
    out = rewalk.apply_plan(releases, plan, ev, tmp_path / "s.json", tmp_path, SEEN)
    assert {"kind": "correction", "ref": "film-the-empire-strikes-back",
            "why": "row changed since resolve"} in out["stale"]
    assert next(r for r in releases if r["id"] == "film-the-empire-strikes-back")["ytmAlbumUrl"] == \
        "https://music.youtube.com/browse/MPREb_hand_attached"


def test_retired_rows_hold_no_claim_and_are_never_merge_targets():
    url = "https://music.youtube.com/browse/a"
    releases = [row("tv-old-season-2", "tv", "Old Season 2 Soundtrack", "A", url, 5, retired=True)]
    assert collect.claimed_albums(releases) == set()
    added, merged = collect.merge(
        releases, [{"title": "Old Season 2 Soundtrack", "medium": "tv", "url": "https://x/new",
                    "date": "2020-01-01", "ytmAlbumUrl": url}],
        {"name": "tmdb-tv", "type": "catalog"}, SEEN)
    assert (added, merged) == (1, 0) and releases[1]["id"] == "tv-old-season-2-2020"
    assert collect.drop_claimed_newcomers(releases, {"tv-old-season-2"}) == [] and len(releases) == 2
