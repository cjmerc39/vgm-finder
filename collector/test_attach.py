"""Attach-tool tests: fakes only, no network, no data file."""
import pytest

import attach


def fake_album(**kw):
    base = {"title": "Game (Original Soundtrack)", "audioPlaylistId": "OLAK5uy_pl",
            "thumbnails": [{"url": "small"}, {"url": "big"}],
            "tracks": [
                {"title": "Opening", "views": "1M plays", "videoId": "vA", "videoType": "MUSIC_VIDEO_TYPE_ATV"},
                {"title": "Finale", "views": None, "videoId": "vOMV", "videoType": "MUSIC_VIDEO_TYPE_OMV"},
            ]}
    base.update(kw)
    return base


def data():
    return {"updatedAt": None, "releases": [
        {"id": "game", "title": "Game Soundtrack", "composers": [], "ytmAlbumUrl": None,
         "art": "https://images.igdb.com/old.jpg", "topTracks": [{"title": "Opening", "plays": None}]},
        {"id": "other", "ytmAlbumUrl": "https://music.youtube.com/browse/MPREb_taken"},
    ]}


def test_attach_fills_the_row_like_the_pipeline():
    d = data()
    row, _ = attach.attach(d, "game", "MPREb_new", composers=["Sea Power"],
                           album_fn=lambda b: fake_album(),
                           playlist_fn=lambda pid: {"tracks": [
                               {"title": "Opening", "videoId": "vA"},
                               {"title": "Finale", "videoId": "vATV"}]})
    assert row["ytmAlbumUrl"] == "https://music.youtube.com/browse/MPREb_new"
    assert row["ytmPlaylistId"] == "OLAK5uy_pl"
    assert [t["videoId"] for t in row["tracks"]] == ["vA", "vATV"]  # OMV id nulled, patched from the audio playlist
    assert row["composers"] == ["Sea Power"]
    assert row["art"] == "big" and "topTracks" not in row


def test_attach_honors_the_claimed_url_doctrine():
    with pytest.raises(SystemExit, match="already worn by other"):
        attach.attach(data(), "game", "MPREb_taken", album_fn=lambda b: fake_album())


def test_attach_refuses_an_already_attached_row():
    d = data()
    d["releases"][0]["ytmAlbumUrl"] = "https://music.youtube.com/browse/MPREb_old"
    with pytest.raises(SystemExit, match="already wears"):
        attach.attach(d, "game", "MPREb_new", album_fn=lambda b: fake_album())


def test_attach_refuses_unknown_rows_and_empty_albums():
    with pytest.raises(SystemExit, match="no row"):
        attach.attach(data(), "ghost", "MPREb_new", album_fn=lambda b: fake_album())
    with pytest.raises(SystemExit, match="empty"):
        attach.attach(data(), "game", "MPREb_new", album_fn=lambda b: {"tracks": []})
