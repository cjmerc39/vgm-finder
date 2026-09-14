"""Scores versus songs, one track at a time: the composer set, the song
marks, the album flag, and the offline re-judge."""
import json

import collect
import fill_artists
import judge_songs


def _t(title, artists, plays=None):
    return {"title": title, "plays": plays, "videoId": None, "artists": list(artists)}


# ---------------------------------------------------------------- score_names

def test_tmdb_credits_and_aliases_always_count():
    names = collect.score_names(["Tom Holkenborg"], ["Junkie XL"], ["Junkie XL"],
                                [_t("Maximum Effort", ["Junkie XL"], "5M plays")])
    assert names == ["Tom Holkenborg", "Junkie XL"]


def test_an_album_act_stands_in_when_tmdb_names_no_composer():
    tracks = [_t("Main Title", ["Chris Tilton"], "40K plays"), _t("Olivia", ["Chris Tilton"], "9K plays")]
    assert collect.score_names([], [], ["Chris Tilton"], tracks, ["Drama"], "tv") == ["Chris Tilton"]


def test_an_album_act_joins_tmdb_credits_when_it_is_not_a_performer():
    # TMDb credits Zimmer, YouTube Music credits the album to his co-writer
    tracks = [_t("Cue", ["Lorne Balfe"], "2M plays")]
    assert collect.score_names(["Hans Zimmer"], [], ["Lorne Balfe"], tracks) == ["Hans Zimmer", "Lorne Balfe"]


def test_a_co_artist_is_a_co_composer_only_while_its_tracks_stay_quiet():
    # Kamen Rider: TMDb names one of two composers; the other's cues are small
    tracks = [_t("Theme", ["Go Sakabe"], "3M plays"), _t("Battle", ["Hiroshi Takaki"], "900K plays")]
    assert collect.score_names(["Go Sakabe"], [], ["Hiroshi Takaki", "Go Sakabe"], tracks) == ["Go Sakabe", "Hiroshi Takaki"]
    # Magnolia: Jon Brion's cues are on the album, so Aimee Mann's songs are a singer's, not a co-composer's
    tracks = [_t("Magnolia", ["Jon Brion"], "400K plays"), _t("Wise Up", ["Aimee Mann"], "12M plays")]
    assert collect.score_names(["Jon Brion"], [], ["Aimee Mann"], tracks) == ["Jon Brion"]
    # but with no credited composer anywhere on the album, the 50M hit line applies (Legend by Tangerine Dream)
    tracks = [_t("Loved by the Sun", ["Tangerine Dream"], "12M plays")]
    assert collect.score_names(["Jerry Goldsmith"], [], ["Tangerine Dream"], tracks) == ["Jerry Goldsmith", "Tangerine Dream"]


def test_short_names_match_exactly():
    assert collect._credited(["BT"], ["BT"]) and collect._credited(["Rob"], ["ROB"]) and collect._credited(["Air"], ["Air"])
    assert not collect._credited(["BT"], ["BTS"]) and not collect._credited(["Rob"], ["Robin Coudert"])
    tracks = [_t("Cue", ["BT"], "1M plays")]
    assert collect.mark_songs(tracks, collect.score_names(["BT"], [], ["BT"], tracks)) == (1, 1)


def test_a_band_with_a_hit_is_a_performer_not_a_composer():
    tracks = [_t("Somebody To Love", ["Queen"], "750M plays"), _t("Doing All Right", ["Smile"], "1.6M plays")]
    assert collect.score_names([], [], ["Queen"], tracks, ["Music", "Drama"], "film") == []
    # the hit alone decides it, whatever the genre
    assert collect.score_names([], [], ["Queen"], tracks, ["Drama"], "film") == []
    assert collect.score_names([], [], ["The Chipmunks"], [_t("Hot N Cold", ["The Chipmunks"], "822M plays")]) == []


def test_a_cast_credit_and_a_music_film_are_performers():
    tracks = [_t("Song", ["Cast of High School Musical: The Musical: The Series"], "1M plays")]
    assert collect.score_names([], [], ["Cast of High School Musical: The Musical: The Series", "Disney"], tracks) == ["Disney"]
    assert collect.score_names([], [], ["Elenco de Soy Luna"], tracks) == []
    quiet = [_t("Sugar Man", ["Rodriguez"], "15M plays")]
    assert collect.score_names([], [], ["Rodriguez"], quiet, ["Music", "Documentary"], "film") == []
    assert collect.score_names([], [], ["Rodriguez"], quiet, ["Music"], "tv") == ["Rodriguez"]  # films only


def test_various_artists_never_stand_in():
    assert collect.score_names([], [], ["Various Artists"], [_t("x", ["A"])]) == []
    assert collect.score_names([], [], ["Varios Artistas"], [_t("x", ["A"])]) == []


# ----------------------------------------------------------------- mark_songs

def test_mark_songs_flags_tracks_by_anyone_but_the_composer():
    tracks = [_t("Cue", ["Fil Eisler"], "2K plays"), _t("Girls Just Want To Have Fun", ["Cyndi Lauper"], "2.1B plays"),
              _t("Zimmer: Dear Clarice", ["Hollywood Studio Orchestra"]), _t("Untitled", []), _t("Medley", ["Various Artists"])]
    named, score = collect.mark_songs(tracks, ["Fil Eisler", "Hans Zimmer"])
    assert (named, score) == (3, 2)
    assert [t.get("song") for t in tracks] == [None, True, None, None, None]
    assert collect.mark_songs([_t("Zimmer: Untitled", [])], ["Hans Zimmer"]) == (0, 0)  # a byline needs an artist to be a credit


def test_mark_songs_with_no_composer_at_all_flags_every_named_track():
    tracks = [_t("Misirlou", ["Dick Dale"]), _t("Dialogue", [])]
    assert collect.mark_songs(tracks, []) == (1, 0)
    assert tracks[0]["song"] is True and "song" not in tracks[1]


def test_mark_songs_clears_a_stale_mark():
    tracks = [dict(_t("Cue", ["Fil Eisler"]), song=True)]
    collect.mark_songs(tracks, ["Fil Eisler"])
    assert "song" not in tracks[0]


# --------------------------------------------------------------- judge_tracks

def test_judge_flags_an_album_the_credited_composer_barely_touches():
    r = {"id": "film-alvin", "medium": "film", "composers": ["David Newman"], "albumArtists": ["Alvin And The Chipmunks"],
         "genres": ["Comedy", "Family"]}
    tracks = [_t(f"Song {i}", ["The Chipmunks"], "822M plays") for i in range(9)] + \
             [_t(f"Song {i}", ["The Chipettes"], "9M plays") for i in range(6)]
    tally = collect.judge_tracks(r, tracks)
    assert tally["songs"] is True and r["songsAlbum"] is True and r["scoresN"] == 0
    assert all(t["song"] for t in tracks)  # two named acts used to be too few to call it


def test_judge_keeps_a_mostly_score_album_and_marks_its_songs():
    r = {"id": "film-lotp", "medium": "film", "composers": ["Fil Eisler"], "albumArtists": ["Various Artists"], "songsAlbum": True}
    tracks = [_t(f"Cue {i}", ["Fil Eisler"], "3K plays") for i in range(17)] + \
             [_t("Girls Just Want To Have Fun", ["Cyndi Lauper"], "2.1B plays"), _t("Rapper's Delight", ["The Sugarhill Gang"], "500M plays")]
    tally = collect.judge_tracks(r, tracks)
    assert tally["songs"] is False and "songsAlbum" not in r and r["scoresN"] == 17
    assert [t.get("song") for t in tracks[-2:]] == [True, True]


def test_judge_treats_album_act_composers_as_album_acts():
    # Bohemian Rhapsody: the row's composers are Queen only because the album is
    queen = {"id": "film-br", "medium": "film", "composers": ["Queen"], "composersFrom": "album",
             "albumArtists": ["Queen"], "genres": ["Music", "Drama"]}
    tracks = [_t("Bohemian Rhapsody", ["Queen"], "2.9B plays"), _t("Doing All Right", ["Smile"], "1.6M plays")]
    tally = collect.judge_tracks(queen, tracks)
    assert tally["names"] == [] and queen["songsAlbum"] is True and queen["scoresN"] == 0
    # Fringe: the same provenance, but the act is a working composer
    fringe = {"id": "tv-fringe", "medium": "tv", "composers": ["Chris Tilton"], "composersFrom": "album",
              "albumArtists": ["Chris Tilton"], "genres": ["Drama"]}
    tracks = [_t("Main Title", ["Chris Tilton"], "40K plays"), _t("Olivia", ["Chris Tilton"], "9K plays")]
    tally = collect.judge_tracks(fringe, tracks)
    assert tally["names"] == ["Chris Tilton"] and "songsAlbum" not in fringe and fringe["scoresN"] == 2


def test_judge_never_flags_on_one_song_among_uncredited_tracks():
    # Quantum of Solace: 23 cues nobody is credited on, one named song
    r = {"id": "film-qos", "medium": "film", "composers": ["David Arnold"], "albumArtists": ["Original Soundtrack"]}
    tracks = [_t(f"Cue {i}", [], "50K plays") for i in range(23)] + [_t("Another Way to Die", ["Jack White", "Alicia Keys"], "30M plays")]
    tally = collect.judge_tracks(r, tracks)
    assert tally == {"named": 1, "score": 0, "songs": False, "names": ["David Arnold", "Original Soundtrack"], "pinned": None}
    assert r["scoresN"] == 23 and "songsAlbum" not in r and tracks[-1]["song"] is True


def test_songs_pins_are_applied_after_the_rule():
    pins = collect.screen_override_sets({"songs": [
        {"medium": "film", "tmdb": 3604, "name": "Flash Gordon", "album": "MPREb_fg", "verdict": "score", "why": "Queen wrote it"},
        {"medium": "film", "tmdb": 10501, "name": "The Road to El Dorado", "album": "MPREb_eld", "verdict": "songs", "why": "Elton John"},
        {"medium": "film", "tmdb": 1, "name": "Bad", "album": "MPREb_bad", "verdict": "maybe", "why": "not a verdict"},
    ]})["songs"]
    assert pins == {"https://music.youtube.com/browse/MPREb_fg": "score", "https://music.youtube.com/browse/MPREb_eld": "songs"}
    # force score: Queen's Flash Gordon reads as songs under the rule (TMDb credits Howard Blake)
    fg = {"id": "film-flash-gordon", "medium": "film", "composers": ["Howard Blake"], "albumArtists": ["Queen"],
          "songsAlbum": True, "ytmAlbumUrl": "https://music.youtube.com/browse/MPREb_fg"}
    tracks = [_t("Flash's Theme", ["Queen"], "80M plays"), _t("In the Space Capsule", ["Queen"], "3M plays")]
    tally = collect.judge_tracks(fg, tracks, pins)
    assert tally["pinned"] == "score" and tally["songs"] is False
    assert "songsAlbum" not in fg and fg["scoresN"] == 2 and not any(t.get("song") for t in tracks)
    # force songs: Elton John stands in under the rule, the pin says otherwise
    eld = {"id": "film-the-road-to-el-dorado", "medium": "film", "composers": ["Hans Zimmer", "John Powell"],
           "albumArtists": ["Elton John"], "ytmAlbumUrl": "https://music.youtube.com/browse/MPREb_eld"}
    tracks = [_t("El Dorado", ["Elton John"], "9M plays"), _t("The Trail We Blaze", ["Elton John"], "4M plays")]
    tally = collect.judge_tracks(eld, tracks, pins)
    assert tally["pinned"] == "songs" and eld["songsAlbum"] is True and eld["scoresN"] == 0 and all(t["song"] for t in tracks)
    # an album without a pin is judged by the rule alone
    other = {"id": "film-x", "medium": "film", "composers": ["A"], "ytmAlbumUrl": "https://music.youtube.com/browse/MPREb_x"}
    assert collect.judge_tracks(other, [_t("Cue", ["A"])], pins)["pinned"] is None


def test_fill_tracks_reads_the_songs_pins_itself(tmp_path, monkeypatch):
    monkeypatch.setattr(collect, "load_screen_overrides", lambda path=None: {"songs": [
        {"medium": "film", "tmdb": 3604, "name": "Flash Gordon", "album": "MPREb_fg", "verdict": "score", "why": "Queen"}]})
    def album(bid):
        return {"artists": [{"name": "Queen"}],
                "tracks": [{"title": "Flash's Theme", "views": "80M plays", "videoId": "v1", "artists": [{"name": "Queen"}]}]}
    r = {"id": "film-flash-gordon", "medium": "film", "composers": ["Howard Blake"],
         "ytmAlbumUrl": "https://music.youtube.com/browse/MPREb_fg"}
    collect.fill_tracks([r], album, lambda q: None, cap=5, tracks_dir=tmp_path, playlist_fn=None)
    saved = json.loads((tmp_path / "film-flash-gordon.json").read_text(encoding="utf-8"))
    assert "song" not in saved[0] and r["scoresN"] == 1 and "songsAlbum" not in r  # the daily run honours the pin


def test_judge_uses_aliases_and_skips_games_and_unfilled_rows():
    r = {"id": "film-deadpool", "medium": "film", "composers": ["Tom Holkenborg"], "composerAliases": ["Junkie XL"],
         "albumArtists": ["Junkie XL"]}
    tracks = [_t("Maximum Effort", ["Junkie XL"], "5M plays"), _t("Careless Whisper", ["Wham!"], "1B plays")]
    assert collect.judge_tracks(r, tracks)["score"] == 1 and r["scoresN"] == 1 and "songsAlbum" not in r
    game = {"id": "hades", "medium": "game", "composers": ["Darren Korb"]}
    assert collect.judge_tracks(game, [_t("No Escape", ["Darren Korb"])]) is None and "scoresN" not in game
    bare = {"id": "film-x", "medium": "film", "composers": ["A"]}
    assert collect.judge_tracks(bare, [{"title": "t", "plays": None, "videoId": None}]) is None and "scoresN" not in bare


def test_fill_tracks_judges_a_film_row_and_keeps_the_album_acts(tmp_path):
    def album(bid):
        return {"artists": [{"name": "Junkie XL"}],
                "tracks": [{"title": "Maximum Effort", "views": "5M plays", "videoId": "v1", "artists": [{"name": "Junkie XL"}]},
                           {"title": "Careless Whisper", "views": "1B plays", "videoId": "v2", "artists": [{"name": "Wham!"}]}]}
    r = {"id": "film-deadpool", "medium": "film", "composers": ["Tom Holkenborg"], "composerAliases": ["Junkie XL"],
         "ytmAlbumUrl": "https://music.youtube.com/browse/MPREb_dp"}
    collect.fill_tracks([r], album, lambda q: None, cap=5, tracks_dir=tmp_path, playlist_fn=None)
    saved = json.loads((tmp_path / "film-deadpool.json").read_text(encoding="utf-8"))
    assert saved[0] == {"title": "Maximum Effort", "plays": "5M plays", "videoId": "v1", "artists": ["Junkie XL"]}
    assert saved[1]["artists"] == ["Wham!"] and saved[1]["song"] is True
    assert r["albumArtists"] == ["Junkie XL"] and r["tracksN"] == 2 and r["scoresN"] == 1
    game = {"id": "hades", "ytmAlbumUrl": "https://music.youtube.com/browse/MPREb_h"}
    collect.fill_tracks([game], album, lambda q: None, cap=5, tracks_dir=tmp_path, playlist_fn=None)
    assert "albumArtists" not in game and "scoresN" not in game  # games are scores by definition


def test_daily_items_and_merge_carry_credit_provenance():
    hit = {"title": "Bohemian Rhapsody (The Original Soundtrack)", "url": "https://music.youtube.com/browse/MPREb_q",
           "art": None, "composers": ["Queen"], "composersFrom": "album", "weak": False}
    info = {"medium": "film", "id": "424694", "name": "Bohemian Rhapsody", "date": "2018-10-24",
            "composers": [], "aliases": []}
    items = collect.screen_items({("film", "424694"): hit}, [(info, {"id": 424694}, {})])
    assert items[0]["composersFrom"] == "album" and "composerAliases" not in items[0]
    hit2 = dict(hit, composers=["Tom Holkenborg"], composersFrom="tmdb")
    info2 = dict(info, id="293660", name="Deadpool", composers=["Tom Holkenborg"], aliases=["Junkie XL"])
    items2 = collect.screen_items({("film", "293660"): hit2}, [(info2, {"id": 293660}, {})])
    assert "composersFrom" not in items2[0] and items2[0]["composerAliases"] == ["Junkie XL"]
    releases = []
    src = {"name": "tmdb-film", "type": "catalog"}
    collect.merge(releases, items + items2, src, "2026-09-14T00:00:00Z")
    rows = {r["id"]: r for r in releases}
    assert rows["film-bohemian-rhapsody"]["composersFrom"] == "album"
    assert rows["film-deadpool"]["composerAliases"] == ["Junkie XL"] and "composersFrom" not in rows["film-deadpool"]


def test_screen_classify_says_where_a_candidates_composers_came_from():
    results = [{"resultType": "album", "browseId": "MPREb_q", "title": "Bohemian Rhapsody (The Original Soundtrack)",
                "year": "2018", "artists": [{"name": "Queen"}]}]
    info = {"medium": "film", "name": "Bohemian Rhapsody", "original": None, "years": [2018], "composers": [], "aliases": []}
    c = collect.screen_matches(results, info)[0]
    assert c["composers"] == ["Queen"] and c["composersFrom"] == "album"
    info2 = dict(info, composers=["John Ottman"])
    c2 = collect.screen_matches(results, info2)[0]
    assert c2["composers"] == ["John Ottman"] and c2["composersFrom"] == "tmdb"


# --------------------------------------------------------------- fill_artists

def test_attach_by_position_then_by_title():
    tracks = [{"title": "A", "plays": None, "videoId": None}, {"title": "B", "plays": None, "videoId": None}]
    page = {"tracks": [{"title": "A", "artists": [{"name": "X"}]}, {"title": "B", "artists": [{"name": "Y"}, {"name": "Z"}]}]}
    assert fill_artists.attach(tracks, page) == 2
    assert [t["artists"] for t in tracks] == [["X"], ["Y", "Z"]]
    tracks = [{"title": "A", "plays": None, "videoId": None}, {"title": "Gone", "plays": None, "videoId": None}]
    page = {"tracks": [{"title": "a", "artists": [{"name": "X"}]}, {"title": "B", "artists": []}, {"title": "C", "artists": []}]}
    assert fill_artists.attach(tracks, page) == 1
    assert [t["artists"] for t in tracks] == [["X"], []]


def test_fill_artists_run_reads_stored_pages_first_and_resumes(tmp_path):
    tracks_dir = tmp_path / "tracks"
    tracks_dir.mkdir()
    rows = [{"id": "film-a", "medium": "film", "tracksN": 1, "ytmAlbumUrl": "https://music.youtube.com/browse/MPREb_a"},
            {"id": "film-b", "medium": "film", "tracksN": 1, "ytmAlbumUrl": "https://music.youtube.com/browse/MPREb_b"},
            {"id": "hades", "medium": "game", "tracksN": 1, "ytmAlbumUrl": "https://music.youtube.com/browse/MPREb_g"}]
    for r in rows:
        (tracks_dir / f"{r['id']}.json").write_text(json.dumps([{"title": "T", "plays": None, "videoId": None}]), encoding="utf-8")
    data_path = tmp_path / "releases.json"
    data_path.write_text(json.dumps({"updatedAt": "x", "releases": rows}), encoding="utf-8")
    fetched = []
    def album(bid):
        fetched.append(bid)
        return {"artists": [{"name": "Live Act"}], "tracks": [{"title": "T", "artists": [{"name": "Live Act"}]}]}
    pages = {"MPREb_a": {"artists": [{"name": "Stored Act"}], "tracks": [{"title": "T", "artists": [{"name": "Stored Act"}]}]}}
    out = fill_artists.run(data_path, tracks_dir, album, pause=0, pages=pages, log=lambda s: None)
    assert out == {"done": 2, "fetched": 1, "failed": 0, "remaining": 0} and fetched == ["MPREb_b"]
    saved = json.loads(data_path.read_text(encoding="utf-8"))["releases"]
    assert saved[0]["albumArtists"] == ["Stored Act"] and saved[1]["albumArtists"] == ["Live Act"] and "albumArtists" not in saved[2]
    assert json.loads((tracks_dir / "film-a.json").read_text(encoding="utf-8"))[0]["artists"] == ["Stored Act"]
    out = fill_artists.run(data_path, tracks_dir, album, pause=0, pages=pages, log=lambda s: None)
    assert out["done"] == 0 and fetched == ["MPREb_b"]  # nothing left: a rerun fetches nothing


# ---------------------------------------------------------------- judge_songs

def test_judge_songs_backfills_credits_and_rejudges_offline(tmp_path):
    tracks_dir = tmp_path / "tracks"
    tracks_dir.mkdir()
    rows = [
        {"id": "film-br", "medium": "film", "composers": ["Queen"], "albumArtists": ["Queen"], "genres": ["Music", "Drama"],
         "tracksN": 2, "ytmAlbumUrl": "https://music.youtube.com/browse/MPREb_q"},
        {"id": "film-dp", "medium": "film", "composers": ["Tom Holkenborg"], "albumArtists": ["Junkie XL"],
         "tracksN": 2, "songsAlbum": True, "ytmAlbumUrl": "https://music.youtube.com/browse/MPREb_dp"},
        {"id": "film-bare", "medium": "film", "composers": ["A"], "tracksN": 1, "songsAlbum": True,
         "ytmAlbumUrl": "https://music.youtube.com/browse/MPREb_bare"},
    ]
    (tracks_dir / "film-br.json").write_text(json.dumps([_t("Bohemian Rhapsody", ["Queen"], "2.9B plays"),
                                                          _t("Doing All Right", ["Smile"], "1M plays")]), encoding="utf-8")
    (tracks_dir / "film-dp.json").write_text(json.dumps([_t("Maximum Effort", ["Junkie XL"], "5M plays"),
                                                          _t("Careless Whisper", ["Wham!"], "1B plays")]), encoding="utf-8")
    (tracks_dir / "film-bare.json").write_text(json.dumps([{"title": "t", "plays": None, "videoId": None}]), encoding="utf-8")
    data_path = tmp_path / "releases.json"
    data_path.write_text(json.dumps({"updatedAt": "x", "releases": rows}), encoding="utf-8")
    evaluations = {
        ("film", "1"): {"composers": [], "aliases": [], "accepted": [{"url": "https://music.youtube.com/browse/MPREb_q"}]},
        ("film", "2"): {"composers": ["Tom Holkenborg"], "aliases": ["Junkie XL"],
                        "accepted": [{"url": "https://music.youtube.com/browse/MPREb_dp"}]},
    }
    out = judge_songs.run(data_path, tracks_dir, evaluations=evaluations, log=lambda s: None, songs_pins={})
    assert out["judged"] == 2 and out["unjudged"] == 1 and out["creditsBackfilled"] == 2 and out["pinned"] == 0
    assert out["newlyFlagged"] == ["film-br"] and out["cleared"] == ["film-dp"]
    assert (out["flaggedBefore"], out["flaggedAfter"]) == (2, 2)  # bare keeps its old flag, unjudged
    saved = {r["id"]: r for r in json.loads(data_path.read_text(encoding="utf-8"))["releases"]}
    assert saved["film-br"]["composersFrom"] == "album" and saved["film-br"]["songsAlbum"] is True and saved["film-br"]["scoresN"] == 0
    assert saved["film-dp"]["composerAliases"] == ["Junkie XL"] and "songsAlbum" not in saved["film-dp"] and saved["film-dp"]["scoresN"] == 1
    assert saved["film-bare"]["songsAlbum"] is True and "scoresN" not in saved["film-bare"]
    dp = json.loads((tracks_dir / "film-dp.json").read_text(encoding="utf-8"))
    assert "song" not in dp[0] and dp[1]["song"] is True
    # a dry run reports the same without touching anything
    stamp = data_path.read_text(encoding="utf-8")
    out = judge_songs.run(data_path, tracks_dir, evaluations=evaluations, write=False, log=lambda s: None, songs_pins={})
    assert out["filesWritten"] == 0 and data_path.read_text(encoding="utf-8") == stamp
    # a songs pin is honoured by the offline re-judge too
    pins = {"https://music.youtube.com/browse/MPREb_dp": "songs"}
    out = judge_songs.run(data_path, tracks_dir, evaluations=evaluations, log=lambda s: None, songs_pins=pins)
    assert out["pinned"] == 1 and out["newlyFlagged"] == ["film-dp"] and out["cleared"] == []
    saved = {r["id"]: r for r in json.loads(data_path.read_text(encoding="utf-8"))["releases"]}
    assert saved["film-dp"]["songsAlbum"] is True and saved["film-dp"]["scoresN"] == 0
    assert all(t["song"] for t in json.loads((tracks_dir / "film-dp.json").read_text(encoding="utf-8")))
