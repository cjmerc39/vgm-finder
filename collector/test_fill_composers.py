"""Game composers from public sources: the album's credit, Wikidata by IGDB
id, a Steam soundtrack page's Composer line. Nothing is guessed from a name."""
import fill_composers

SEEN = "2026-09-19T08:00:00Z"


def _game(rid, urls, game=None, album=None, composers=None):
    r = {"id": rid, "title": rid, "medium": "game", "game": game or rid, "date": "2021-01-01",
         "sources": [{"name": "x", "url": u, "seenAt": SEEN} for u in urls]}
    if album:
        r["ytmAlbumUrl"] = "https://music.youtube.com/browse/" + album
    if composers:
        r["composers"] = composers
    return r


STEAM_PAGE = """<table><tr><td class="label">Artist:</td>
  <td>Heartdust</td></tr><tr><td class="label">Composer:</td>
  <td><a href="#">Mariano Moya Barroso</a> &amp; Lena Raine</td></tr></table>"""
ARTIST_ONLY = """<tr><td>Artist:</td><td>Honorary Bearson</td></tr>"""
ECHO_ONLY = """<tr><td>Artist:</td><td>Endacopia</td></tr>"""


def test_three_sources_in_order_and_nothing_overwritten():
    rows = [_game("hades", ["https://www.igdb.com/games/hades"], album="MPREb_hades"),        # album wins over Wikidata
            _game("bioshock", ["https://www.igdb.com/games/bioshock"]),
            _game("heartdust", ["https://store.steampowered.com/app/4918360/"], game="HEARTDUST"),
            _game("hopsy", ["https://store.steampowered.com/app/4820540/"], game="Hopsy the Frog"),
            _game("endacopia", ["https://store.steampowered.com/app/4791940/"], game="Endacopia"),
            _game("va-album", ["https://www.igdb.com/games/nobody"], album="MPREb_va"),
            _game("done", ["https://www.igdb.com/games/done"], composers=["Someone"])]
    albums = {"MPREb_hades": {"artists": [{"name": "Darren Korb"}]}, "MPREb_va": {"artists": [{"name": "Various Artists"}]}}
    queries = []

    def post(q):
        queries.append(q)
        return {"results": {"bindings": [{"slug": {"value": "bioshock"}, "name": {"value": "Garry Schyman"}},
                                         {"slug": {"value": "hades"}, "name": {"value": "Not Asked"}}]}}
    pages = {"4918360": STEAM_PAGE, "4820540": ARTIST_ONLY, "4791940": ECHO_ONLY}
    logs = []
    got = fill_composers.fill(rows, album_fn=lambda b: albums[b], post=post,
                              get=lambda url: pages[url.split("/app/")[1].split("/")[0]], pause=0, log=logs.append)
    by = {r["id"]: r for r in rows}
    assert by["hades"]["composers"] == ["Darren Korb"] and by["hades"]["composersFrom"] == "album"
    assert by["bioshock"]["composers"] == ["Garry Schyman"] and by["bioshock"]["composersFrom"] == "wikidata"
    assert by["heartdust"]["composers"] == ["Mariano Moya Barroso", "Lena Raine"] and by["heartdust"]["composersFrom"] == "steam"
    assert by["hopsy"]["composers"] == ["Honorary Bearson"]            # no Composer line: the Artist line
    assert "composers" not in by["endacopia"]                           # the Artist line only echoes the game
    assert "composers" not in by["va-album"]                            # Various Artists is no credit, and Wikidata had none
    assert by["done"]["composers"] == ["Someone"] and "composersFrom" not in by["done"]
    assert '"hades"' not in queries[0]                                   # filled from the album: never asked of Wikidata
    assert got == {"album": 1, "wikidata": 1, "steam": 2}
    assert logs == ["composers: 6 rows had none, 4 filled (1 from the album, 1 from Wikidata, 2 from Steam), 2 still without"]


def test_credit_lines_split_into_names_and_drop_non_credits():
    assert fill_composers._names("Ann Lee, Bo Chen &amp; Cy Park and Di Wu / Ed Moe") == ["Ann Lee", "Bo Chen", "Cy Park", "Di Wu", "Ed Moe"]
    assert fill_composers.credited(["Various Artists", "Geek Music", "Tiny Game", "Real Person"], "Tiny Game") == ["Real Person"]


def test_the_daily_step_only_touches_recent_rows():
    old = _game("old", ["https://www.igdb.com/games/old"])
    old["sources"][0]["seenAt"] = "2026-07-01T00:00:00Z"
    got = fill_composers.fill([old], recent_since="2026-09-01T00:00:00Z", post=lambda q: 1 / 0, pause=0, log=lambda *_: None)
    assert got == {"album": 0, "wikidata": 0, "steam": 0}


def test_prose_credit_lines_give_the_composers_and_paragraphs_give_nothing():
    kingdom = ("Music composed &amp; orchestrated by Jan Valta Tracks [4, 7, 12] composed by Adam Sporka "
               "Lyrics by John Comer [42] Produced by Jan Valta")
    assert fill_composers._names(kingdom) == ["Jan Valta", "Adam Sporka"]          # the lyricist and producer lines are skipped
    assert fill_composers._names("Additional music by by Adam Sporka") == ["Adam Sporka"]
    assert fill_composers._names("光碟一： 駱集益 音樂製作人，曾以《海角七號》電影配樂獲得第45屆金馬獎最佳原創電影音樂獎。") == []
    assert fill_composers._names("C418") == ["C418"] and fill_composers._names("Tracks [4, 7]") == []


def test_labels_and_the_game_s_own_name_are_never_composers():
    assert fill_composers.credited(["SEGA", "Killing Floor 3", "Jan Valta"], "Killing Floor III") == ["Jan Valta"]


def test_a_various_artists_album_credits_the_artists_on_most_of_its_tracks():
    album = {"artists": [{"name": "Various Artists"}],
             "tracks": [{"artists": [{"name": "LudoWic"}]}, {"artists": [{"name": "LudoWic"}, {"name": "Bill Kiley"}]},
                        {"artists": [{"name": "Bill Kiley"}]}, {"artists": [{"name": "One Off"}]},
                        {"artists": [{"name": "Various Artists"}]}]}
    assert fill_composers.album_artists("x", album_fn=lambda b: album) == ["LudoWic", "Bill Kiley"]  # One Off has one track
    assert fill_composers.album_artists("x", album_fn=lambda b: {"artists": [{"name": "Darren Korb"}]}) == ["Darren Korb"]


def test_a_slow_wikidata_batch_is_retried_and_never_sinks_the_rest(monkeypatch):
    monkeypatch.setattr(fill_composers.time, "sleep", lambda s: None)
    calls = []

    def post(q):
        calls.append(q)
        if '"slow-0"' in q and len([c for c in calls if '"slow-0"' in c]) < 3:
            raise TimeoutError("read timed out")
        if '"dead-0"' in q:
            raise TimeoutError("read timed out")
        slug = q.split('"')[1]
        return {"results": {"bindings": [{"slug": {"value": slug}, "name": {"value": "Composer " + slug}}]}}
    slugs = [f"slow-{i}" for i in range(25)] + [f"dead-{i}" for i in range(25)] + [f"fine-{i}" for i in range(25)]
    out = fill_composers.wikidata_composers(slugs, post=post)
    assert out == {"slow-0": ["Composer slow-0"], "fine-0": ["Composer fine-0"]}  # the dead batch alone is lost


def test_a_shared_track_credit_counts_for_each_name_in_it():
    album = {"artists": [{"name": "Various Artists"}],
             "tracks": [{"artists": [{"name": "Nobuko Toda/Shuichi Kobori"}]}, {"artists": [{"name": "Nobuko Toda/Shuichi Kobori"}]},
                        {"artists": [{"name": "Mick Gordon & Martin Stig Andersen"}]}, {"artists": [{"name": "Mick Gordon & Martin Stig Andersen"}]}]}
    assert fill_composers.album_artists("x", album_fn=lambda b: album) == ["Nobuko Toda", "Shuichi Kobori", "Mick Gordon", "Martin Stig Andersen"]


def test_a_film_or_tv_row_takes_the_album_credit_then_wikidata():
    """TMDb credits Marvel's Luke Cage no composer. Its album says Various
    Artists, and on a screen row that is a song compilation, so the track
    credits are never read; Wikidata's composer, found by TMDb id, is."""
    cage = {"id": "tv-luke-cage", "medium": "tv", "game": "Marvel's Luke Cage", "date": "2016-09-30",
            "ytmAlbumUrl": "https://music.youtube.com/browse/MPREb_cage",
            "sources": [{"name": "tmdb-tv", "url": "https://www.themoviedb.org/tv/62126", "seenAt": SEEN}]}
    wolf = {"id": "film-wolf", "medium": "film", "game": "The Wolf of Wall Street", "date": "2013-12-25",
            "ytmAlbumUrl": "https://music.youtube.com/browse/MPREb_wolf",
            "sources": [{"name": "tmdb-film", "url": "https://www.themoviedb.org/movie/106646", "seenAt": SEEN}]}
    warrior = {"id": "tv-warrior", "medium": "tv", "game": "Warrior", "date": "2019-04-05",
               "ytmAlbumUrl": "https://music.youtube.com/browse/MPREb_warrior",
               "sources": [{"name": "tmdb-tv", "url": "https://www.themoviedb.org/tv/73544", "seenAt": SEEN}]}
    albums = {"MPREb_cage": {"artists": [{"name": "Various Artists"}],
                             "tracks": [{"title": "Good Man", "artists": [{"name": "Raphael Saadiq"}]},
                                        {"title": "Soliloquy of Chaos",
                                         "artists": [{"name": "Ali Shaheed Muhammad & The Midnight Hour"}]}]},
              "MPREb_wolf": {"artists": [{"name": "Various Artists"}],
                             "tracks": [{"title": "Bo Diddley", "artists": [{"name": "Bo Diddley"}]},
                                        {"title": "Dust My Broom", "artists": [{"name": "Bo Diddley"}]}]},
              "MPREb_warrior": {"artists": [{"name": "Reza Safinia"}, {"name": "H. Scott Salinas"}]}}
    asked = []

    def post(q):
        asked.append(q)
        return {"results": {"bindings": [{"tid": {"value": "62126"}, "name": {"value": "Ali Shaheed Muhammad"}},
                                         {"tid": {"value": "62126"}, "name": {"value": "Adrian Younge"}},
                                         {"tid": {"value": "106646"}, "name": {"value": "Howard Shore"}}]}}
    got = fill_composers.fill([cage, wolf, warrior], album_fn=lambda b: albums[b], post=post,
                              get=lambda url: "", pause=0, log=lambda *_: None)
    assert warrior["composers"] == ["Reza Safinia", "H. Scott Salinas"] and warrior["composersFrom"] == "album"
    assert cage["composers"] == ["Ali Shaheed Muhammad"] and cage["composersFrom"] == "wikidata"
    assert "Adrian Younge" not in cage["composers"]     # Wikidata named him; this album's credits do not
    assert "composers" not in wolf                      # Wikidata says Howard Shore; no track credits him
    assert "Raphael Saadiq" not in str(cage) and "Bo Diddley" not in str(wolf)  # performers never become composers
    assert fill_composers.on_album("Ali Shaheed Muhammad", {"ali shaheed muhammad the midnight hour"})
    assert not fill_composers.on_album("Howard Shore", {"bo diddley"})
    assert got == {"album": 1, "wikidata": 1, "steam": 0}
    assert len(asked) == 2 and "P4947" in asked[0] and "P4983" in asked[1]      # films by movie id, shows by series id
    assert '"73544"' not in asked[1]                    # filled from its album: never asked of Wikidata


def test_a_games_album_still_reads_its_track_credits():
    va = _game("va-game", ["https://www.igdb.com/games/va-game"], album="MPREb_va")
    albums = {"MPREb_va": {"artists": [{"name": "Various Artists"}],
                           "tracks": [{"title": "a", "artists": [{"name": "Lena Raine"}]},
                                      {"title": "b", "artists": [{"name": "Lena Raine"}]}]}}
    fill_composers.fill([va], album_fn=lambda b: albums[b], post=lambda q: {"results": {"bindings": []}},
                        get=lambda url: "", pause=0, log=lambda *_: None)
    assert va["composers"] == ["Lena Raine"] and va["composersFrom"] == "album"
