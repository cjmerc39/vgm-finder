import json

import fill_tracklists as ft


def _row(rid, medium, album=True, **extra):
    r = {"id": rid, "title": f"{rid} Soundtrack", "medium": medium, "game": rid, "composers": [],
         "date": "2024-01-01", "sources": [], "ytmSearchUrl": "https://music.youtube.com/search?q=x",
         "ytmAlbumUrl": f"https://music.youtube.com/browse/MPREb_{rid}" if album else None,
         "art": None, "notable": True}
    r.update(extra)
    return r


def _album(n, plays="1K plays"):
    return {"audioPlaylistId": "OLAK5uy_x",
            "tracks": [{"title": f"Track {i}", "videoId": f"v{i}", "videoType": "MUSIC_VIDEO_TYPE_ATV",
                        "views": plays} for i in range(n)]}


def _write(tmp_path, rows):
    data_path = tmp_path / "data" / "releases.json"
    data_path.parent.mkdir()
    data_path.write_text(json.dumps({"updatedAt": None, "releases": rows}), encoding="utf-8")
    return data_path


def test_pending_is_visible_screen_rows_with_an_album_and_no_check():
    rows = [_row("film-a", "film"), _row("tv-b", "tv"), _row("game-c", "game"),
            _row("film-done", "film", tracksN=3), _row("film-empty", "film", tracksN=0),
            _row("film-retired", "film", retired=True), _row("film-noalbum", "film", album=False),
            _row("film-legacy", "film", tracks=[])]
    assert [r["id"] for r in ft.pending(rows)] == ["film-a", "tv-b"]


def test_run_fills_under_the_cap_and_leaves_the_rest_for_the_next_run(tmp_path, capsys):
    rows = [_row("film-a", "film"), _row("tv-b", "tv"), _row("film-c", "film"), _row("game-d", "game")]
    data_path = _write(tmp_path, rows)
    albums = {"MPREb_film-a": _album(3), "MPREb_tv-b": _album(0), "MPREb_film-c": _album(2)}
    fetched = []
    album_fn = lambda bid: fetched.append(bid) or albums[bid]
    out = ft.run(data_path, tmp_path / "data" / "tracks", album_fn, playlist_fn=False, cap=2, now=None)
    assert out == {"looked": 2, "filled": 1, "empty": 1, "failed": 0, "remaining": 1}
    assert fetched == ["MPREb_film-a", "MPREb_tv-b"]  # file order, capped, the game row never read
    saved = {r["id"]: r for r in json.loads(data_path.read_text(encoding="utf-8"))["releases"]}
    assert saved["film-a"]["tracksN"] == 3 and saved["film-a"]["playsTotal"] == 3000
    assert saved["tv-b"]["tracksN"] == 0 and "playsTotal" not in saved["tv-b"]
    assert "tracksN" not in saved["film-c"] and "tracksN" not in saved["game-d"]
    assert (tmp_path / "data" / "tracks" / "film-a.json").exists()
    assert not (tmp_path / "data" / "tracks" / "tv-b.json").exists()  # an empty check writes no file
    assert "tracklists in progress" in capsys.readouterr().out
    out = ft.run(data_path, tmp_path / "data" / "tracks", album_fn, playlist_fn=False, cap=2)
    assert out == {"looked": 1, "filled": 1, "empty": 0, "failed": 0, "remaining": 0}
    assert "tracklists complete" in capsys.readouterr().out


def test_run_keeps_a_failed_fetch_for_the_next_run(tmp_path):
    data_path = _write(tmp_path, [_row("film-a", "film"), _row("film-b", "film")])

    def flaky(bid):
        if bid.endswith("film-a"):
            raise ConnectionResetError("reset")
        return _album(1)
    out = ft.run(data_path, tmp_path / "data" / "tracks", flaky, playlist_fn=False, cap=5)
    assert out == {"looked": 2, "filled": 1, "empty": 0, "failed": 1, "remaining": 1}
    saved = {r["id"]: r for r in json.loads(data_path.read_text(encoding="utf-8"))["releases"]}
    assert "tracksN" not in saved["film-a"] and saved["film-b"]["tracksN"] == 1
