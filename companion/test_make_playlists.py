"""Companion tests: everything drives sync_playlist/resolve with a fake
client — no network, no auth, no real account anywhere near pytest."""
import json

import pytest

import make_playlists as mp


class FakeYT:
    def __init__(self, playlists=None, search_hits=None):
        self.playlists = dict(playlists or {})   # pid -> {title, description, tracks:[videoId]}
        self.search_hits = dict(search_hits or {})  # query -> [search result dicts]
        self.created = []
        self.added = []
        self.searches = []
        self._n = 0

    def get_library_playlists(self, limit=None):
        return [{"playlistId": pid, "title": p["title"]} for pid, p in self.playlists.items()]

    def get_playlist(self, pid, limit=None):
        p = self.playlists[pid]
        return {"description": p.get("description", ""),
                "tracks": [{"videoId": v} for v in p.get("tracks", [])]}

    def create_playlist(self, title, description, privacy_status="PRIVATE"):
        self._n += 1
        pid = f"PL{self._n}"
        self.playlists[pid] = {"title": title, "description": description, "tracks": []}
        self.created.append((title, description, privacy_status))
        return pid

    def add_playlist_items(self, pid, video_ids, duplicates=False):
        self.playlists[pid]["tracks"].extend(video_ids)
        self.added.append((pid, list(video_ids)))
        return {"status": "STATUS_SUCCEEDED"}

    def search(self, query, filter=None, limit=None):
        self.searches.append(query)
        return self.search_hits.get(query, [])


def hit(title, video_id, album=None, artists=("Darren Korb",)):
    return {"title": title, "videoId": video_id,
            "album": {"name": album} if album else None,
            "artists": [{"name": a} for a in artists]}


# ---------------------------------------------------------------- load_export

def test_load_export_roundtrip(tmp_path):
    f = tmp_path / "playlist-x.json"
    f.write_text(json.dumps({"app": "vgm-finder-playlist", "name": " My Mix ", "tracks": [
        {"game": "Hades II", "title": "No Escape", "videoId": "v1", "searchQuery": "Hades II No Escape"},
        {"title": ""}, "junk", {"game": "X"},
    ]}), encoding="utf-8")
    name, tracks = mp.load_export(f)
    assert name == "My Mix"
    assert [t["title"] for t in tracks] == ["No Escape"]  # junk rows fold away


@pytest.mark.parametrize("body", [
    "not json", '"a string"', '{"tracks": []}', '{"name": "x"}',
    '{"name": "", "tracks": []}', '{"name": "x", "tracks": {}}',
])
def test_load_export_rejects_foreign_files(tmp_path, body):
    f = tmp_path / "bad.json"
    f.write_text(body, encoding="utf-8")
    with pytest.raises(ValueError):
        mp.load_export(f)


# ------------------------------------------------------------------- resolve

def test_resolve_strict_match_with_numfold():
    # PERSONA5 vs Persona 5 and case noise: the collector's folds close the gap
    yt = FakeYT(search_hits={"Persona 5 Aria of the Soul": [
        hit("ARIA OF THE SOUL", "vGood", album="PERSONA5 Original Soundtrack", artists=("Shoji Meguro",)),
    ]})
    t = {"game": "Persona 5", "title": "Aria of the Soul", "searchQuery": "Persona 5 Aria of the Soul"}
    assert mp.resolve_video_id(yt, t) == "vGood"


def test_resolve_rejects_covers_titles_and_gameless_hits():
    hits = [
        hit("No Escape", "vCover", album="Hades II", artists=("Geek Music",)),      # tribute act
        hit("No Escape (Live)", "vWrong", album="Hades II"),                        # title mismatch
        hit("No Escape", "vNoGame", album="Singles Collection"),                    # no game evidence
        hit("No Escape", "vGood", album="Hades II (Original Soundtrack)"),
    ]
    yt = FakeYT(search_hits={"Hades II No Escape": hits})
    t = {"game": "Hades II", "title": "No Escape", "searchQuery": "Hades II No Escape"}
    assert mp.resolve_video_id(yt, t) == "vGood"
    assert mp.resolve_video_id(FakeYT(), t) is None            # no hits at all
    assert mp.resolve_video_id(yt, {"title": "No Escape"}) is None  # gameless track: never guess


# ---------------------------------------------------------------------- sync

TRACKS = [
    {"game": "Hades II", "title": "No Escape", "videoId": "v1"},
    {"game": "Hades II", "title": "Coral Crown", "videoId": "v2"},
    {"game": "Hades II", "title": "No Escape", "videoId": "v1"},  # dupe collapses
]


def test_sync_creates_private_marked_playlist():
    yt = FakeYT()
    rep = mp.sync_playlist(yt, "vgm-finder · Liked Songs", TRACKS)
    assert rep["created"] is True and rep["added"] == 2 and rep["already"] == 0
    (title, description, privacy), = yt.created
    assert title == "vgm-finder · Liked Songs"
    assert mp.MARKER in description
    assert privacy == "PRIVATE"
    assert yt.added == [("PL1", ["v1", "v2"])]


def test_sync_rerun_is_idempotent():
    yt = FakeYT()
    mp.sync_playlist(yt, "Mix", TRACKS)
    rep = mp.sync_playlist(yt, "Mix", TRACKS)
    assert rep["created"] is False and rep["added"] == 0 and rep["already"] == 2
    assert len(yt.added) == 1  # nothing re-added on the second pass


def test_sync_tops_up_only_missing_tracks():
    yt = FakeYT(playlists={"PLX": {"title": "Mix", "description": mp.DESCRIPTION, "tracks": ["v1"]}})
    rep = mp.sync_playlist(yt, "Mix", TRACKS)
    assert rep["created"] is False and rep["added"] == 1 and rep["already"] == 1
    assert yt.added == [("PLX", ["v2"])]


def test_sync_never_touches_a_hand_made_namesake():
    yt = FakeYT(playlists={"PLX": {"title": "Mix", "description": "my own list", "tracks": ["z"]}})
    rep = mp.sync_playlist(yt, "Mix", TRACKS)
    assert rep["skipped"] is True
    assert yt.created == [] and yt.added == []
    assert yt.playlists["PLX"]["tracks"] == ["z"]


def test_sync_prefers_the_marked_namesake():
    yt = FakeYT(playlists={
        "PLA": {"title": "Mix", "description": "hand-made", "tracks": ["z"]},
        "PLB": {"title": "Mix", "description": mp.DESCRIPTION, "tracks": ["v1"]},
    })
    rep = mp.sync_playlist(yt, "Mix", TRACKS)
    assert rep["skipped"] is False and rep["added"] == 1
    assert yt.added == [("PLB", ["v2"])]
    assert yt.playlists["PLA"]["tracks"] == ["z"]


def test_sync_resolves_and_reports_unresolved():
    yt = FakeYT(search_hits={"Hades II Bonus Reel": [
        hit("Bonus Reel", "vBR", album="Hades II (Original Soundtrack)"),
    ]})
    tracks = [
        {"game": "Hades II", "title": "Bonus Reel", "searchQuery": "Hades II Bonus Reel"},
        {"game": "Sifu", "title": "Club Fight", "searchQuery": "Sifu Club Fight"},
    ]
    rep = mp.sync_playlist(yt, "Mix", tracks)
    assert rep["added"] == 1
    assert yt.added == [("PL1", ["vBR"])]
    assert rep["unresolved"] == ["Sifu — Club Fight"]


# ---------------------------------------------------------------------- glob

def test_expand_args_globs_for_windows_shells(tmp_path, monkeypatch):
    (tmp_path / "playlist-a.json").write_text("{}", encoding="utf-8")
    (tmp_path / "playlist-b.json").write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert mp.expand_args(["playlist-*.json"]) == ["playlist-a.json", "playlist-b.json"]
    assert mp.expand_args(["missing.json"]) == ["missing.json"]
