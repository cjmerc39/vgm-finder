"""Migration tests: the one-time split of tracklists out of releases.json."""
import copy
import json

import split_tracks

ROWS = [
    {"id": "with-tracks", "title": "A Soundtrack", "game": "A", "date": "2020-01-01",
     "tracks": [{"title": "One", "plays": "1K plays", "videoId": "v1"},
                {"title": "Two", "plays": None, "videoId": None}],
     "ytmPlaylistId": "OLAK5uy_a"},
    {"id": "checked-empty", "title": "B Soundtrack", "game": "B",
     "date": "2021-01-01", "tracks": []},
    {"id": "never-checked", "title": "C Soundtrack", "game": "C", "date": "2022-01-01"},
]


def test_split_moves_tracks_and_stamps_medium(tmp_path):
    rows = copy.deepcopy(ROWS)
    changed = split_tracks.split(rows, tmp_path)
    assert changed == 3  # every row at least gains medium
    assert all(r["medium"] == "game" for r in rows)
    assert all("tracks" not in r for r in rows)
    assert rows[0]["tracksN"] == 2 and rows[0]["playsTotal"] == 1000
    assert json.loads((tmp_path / "with-tracks.json").read_text(encoding="utf-8")) == ROWS[0]["tracks"]
    assert rows[0]["ytmPlaylistId"] == "OLAK5uy_a"  # the row keeps its album-context id
    assert rows[1]["tracksN"] == 0 and not (tmp_path / "checked-empty.json").exists()
    assert "tracksN" not in rows[2]  # never checked stays never checked


def test_split_is_idempotent(tmp_path):
    rows = copy.deepcopy(ROWS)
    split_tracks.split(rows, tmp_path)
    snapshot = copy.deepcopy(rows)
    assert split_tracks.split(rows, tmp_path) == 0
    assert rows == snapshot


def test_split_then_rejoin_equals_the_original(tmp_path):
    rows = copy.deepcopy(ROWS)
    split_tracks.split(rows, tmp_path)
    split_tracks.rejoin(rows, tmp_path)
    for before, after in zip(ROWS, rows):
        assert {k: v for k, v in after.items() if k != "medium"} == before


def test_run_writes_once_then_stops(tmp_path):
    data_path = tmp_path / "releases.json"
    data_path.write_text(json.dumps({"updatedAt": "2026-01-01T00:00:00Z",
                                     "releases": copy.deepcopy(ROWS)},
                                    ensure_ascii=False), encoding="utf-8")
    assert split_tracks.run(data_path=data_path) == 0
    first = data_path.read_text(encoding="utf-8")
    assert (tmp_path / "tracks" / "with-tracks.json").exists()
    assert all(r["medium"] == "game" for r in json.loads(first)["releases"])
    assert split_tracks.run(data_path=data_path) == 0  # second run: nothing to do
    assert data_path.read_text(encoding="utf-8") == first
