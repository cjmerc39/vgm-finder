"""Anime on film and TV rows, and IGDB themes on game rows: the daily legs
tag new rows, the fill tags the ones already there, and nothing is guessed."""
import collect
import fill_genres

SEEN = "2026-09-19T08:00:00Z"
GMAP = {"16": "Animation", "35": "Comedy", "10751": "Family", "12": "Adventure", "18": "Drama"}


def test_new_titles_get_anime_from_animation_in_japanese_even_past_the_first_three():
    four = {"genre_ids": [10751, 35, 12, 16], "original_language": "ja"}
    assert collect._tmdb_genres(four, GMAP) == ["Family", "Comedy", "Adventure", "Anime"]
    assert collect._tmdb_genres({"genre_ids": [16, 18], "original_language": "en"}, GMAP) == ["Animation", "Drama"]
    assert collect._tmdb_genres({"genre_ids": [18], "original_language": "ja"}, GMAP) == ["Drama"]  # Japanese live action
    assert collect._tmdb_genres({"genre_ids": [], "original_language": "ja"}, GMAP) is None


def _screen(rid, medium, tid, genres):
    kind = "movie" if medium == "film" else "tv"
    return {"id": rid, "title": rid, "medium": medium, "genres": genres,
            "sources": [{"name": "tmdb-" + medium, "url": f"https://www.themoviedb.org/{kind}/{tid}", "seenAt": SEEN}]}


def test_the_anime_fill_reads_full_details_once_and_tags_only_japanese_animation():
    rows = [_screen("film-spirited-away", "film", "129", ["Family", "Fantasy", "Adventure"]),  # Animation cut by the three
            _screen("film-toy-story", "film", "862", ["Animation", "Comedy"]),
            _screen("tv-frieren", "tv", "209867", ["Animation", "Anime"]),                     # already tagged: not looked up
            _screen("film-drive", "film", "64690", ["Drama"]),
            {"id": "hades", "title": "hades", "medium": "game", "sources": []}]
    details = {("movie", "129"): {"genres": [{"name": "Animation"}, {"name": "Family"}], "original_language": "ja"},
               ("movie", "862"): {"genres": [{"name": "Animation"}], "original_language": "en"},
               ("movie", "64690"): {"genres": [{"name": "Drama"}], "original_language": "en"}}
    asked, logs = [], []

    def lookup(kind, tid):
        asked.append((kind, tid))
        return details[(kind, tid)]
    assert fill_genres.anime_fill(rows, lookup, log=logs.append) == 1
    assert rows[0]["genres"] == ["Family", "Fantasy", "Adventure", "Anime"] and "Anime" not in rows[1]["genres"]
    assert ("tv", "209867") not in asked and len(asked) == 3
    assert logs == ["anime: 3 film and TV rows checked, 1 tagged Anime, 0 lookups failed"]
    assert fill_genres.anime_fill(rows, lookup, log=lambda *_: None) == 0 and len(asked) == 5  # a rerun adds nothing twice


def _game(rid, url=None, genres=None, date="2021-05-01", game=None):
    r = {"id": rid, "title": rid, "medium": "game", "game": game or rid, "date": date,
         "sources": [{"name": "x", "url": url or "https://music.youtube.com/browse/x", "seenAt": SEEN}]}
    if genres:
        r["genres"] = genres
    return r


def _t(stamp_year):
    import calendar
    return calendar.timegm((stamp_year, 6, 1, 0, 0, 0))


class FakeIGDB:
    def __init__(self):
        self.bodies = []

    def __call__(self, endpoint, body):
        self.bodies.append((endpoint, body))
        if endpoint == "games" and "where slug" in body:
            return [{"slug": "hades", "name": "Hades", "genres": [{"name": "Role-playing (RPG)"}],
                     "themes": [{"name": "Action"}, {"name": "Fantasy"}]}]
        if endpoint == "external_games":
            return [{"uid": "1145360", "url": "https://store.steampowered.com/app/1145360",
                     "game": {"name": "Inscryption", "genres": [{"name": "Card & Board Game"}], "themes": [{"name": "Horror"}]}},
                    {"uid": "999", "url": "https://www.gog.com/game/other",   # another store's id 999: not ours
                     "game": {"name": "Wrong", "themes": [{"name": "Comedy"}]}}]
        if endpoint == "games" and body.startswith('search "Celeste"'):
            return [{"name": "Celeste", "first_release_date": _t(2018), "themes": [{"name": "Drama"}], "genres": [{"name": "Platform"}]},
                    {"name": "Celeste Classic", "first_release_date": _t(2015)}]
        if endpoint == "games" and body.startswith('search "Doom"'):
            return [{"name": "Doom", "first_release_date": _t(2016)}, {"name": "DOOM", "first_release_date": _t(2016)}]
        return []


def test_games_are_found_by_igdb_link_steam_id_or_exact_name_and_year():
    rows = [_game("hades", "https://www.igdb.com/games/hades", genres=["Indie"]),
            _game("inscryption", "https://store.steampowered.com/app/1145360/Inscryption/"),
            _game("gog-game", "https://store.steampowered.com/app/999/"),
            _game("celeste", date="2018-01-25", game="Celeste"),
            _game("doom", date="2016-05-13", game="Doom"),
            _game("old-row", "https://www.igdb.com/games/old-row"),
            dict(_game("done", "https://www.igdb.com/games/done"), themes=[])]
    logs = []
    found = fill_genres.games_fill(rows, FakeIGDB(), log=logs.append)
    assert found == {"IGDB link": 1, "Steam id": 1, "name": 1}
    by = {r["id"]: r for r in rows}
    assert by["hades"]["themes"] == ["Action", "Fantasy"] and by["hades"]["genres"] == ["Indie"]  # genres kept as they were
    assert by["inscryption"]["themes"] == ["Horror"] and by["inscryption"]["genres"] == ["Card & Board Game"]
    assert "themes" not in by["gog-game"]            # another store's uid is never taken
    assert by["celeste"]["themes"] == ["Drama"] and by["celeste"]["genres"] == ["Platform"]
    assert "themes" not in by["doom"]                # two games of one name and year: left for a person
    assert "themes" not in by["old-row"]             # not found: tried again next run
    assert logs == ["game genres: 6 rows looked up, 3 found (1 by IGDB link, 1 by Steam id, 1 by name), "
                    "genres filled on 2, 3 not found"]


def test_the_daily_step_looks_only_at_recent_rows():
    old = _game("old", "https://www.igdb.com/games/hades")
    old["sources"][0]["seenAt"] = "2026-07-01T00:00:00Z"
    fake = FakeIGDB()
    assert fill_genres.games_fill([old], fake, recent_since="2026-09-01T00:00:00Z", log=lambda *_: None) == \
        {"IGDB link": 0, "Steam id": 0, "name": 0}
    assert fake.bodies == []


def test_new_igdb_rows_carry_their_themes_and_merge_fills_them_once():
    item = {"title": "Hades Soundtrack", "game": "Hades", "medium": "game", "genres": ["Role-playing (RPG)"],
            "themes": ["Action", "Fantasy"], "url": "https://www.igdb.com/games/hades", "date": "2020-09-17",
            "composers": []}
    releases = []
    collect.merge(releases, [item], {"name": "igdb", "type": "catalog"}, SEEN)
    assert releases[0]["themes"] == ["Action", "Fantasy"]
    releases[0]["themes"] = ["Fantasy"]
    collect.merge(releases, [dict(item, url="https://store.steampowered.com/app/1145350")], {"name": "steam", "type": "catalog"}, SEEN)
    assert releases[0]["themes"] == ["Fantasy"]  # present already: a second source never overwrites it
    assert collect.themes_of({"themes": [{"name": "Horror"}, {"name": ""}, {}]}) == ["Horror"]
