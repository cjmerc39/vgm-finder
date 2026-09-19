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
        self.removed = []
        self.edited = []
        self.searches = []
        self._n = 0

    def get_library_playlists(self, limit=None):
        return [{"playlistId": pid, "title": p["title"]} for pid, p in self.playlists.items()]

    def get_playlist(self, pid, limit=None):
        p = self.playlists[pid]
        return {"description": p.get("description", ""),
                "tracks": [{"videoId": v, "setVideoId": "set-" + v} for v in p.get("tracks", [])]}

    def create_playlist(self, title, description, privacy_status="PRIVATE"):
        self._n += 1
        pid = f"PL{self._n}"
        self.playlists[pid] = {"title": title, "description": description, "tracks": []}
        self.created.append((title, description, privacy_status))
        return pid

    def edit_playlist(self, pid, title=None, description=None, privacyStatus=None):
        p = self.playlists[pid]
        if title is not None:
            p["title"] = title
        if description is not None:
            p["description"] = description
        self.edited.append((pid, title, description))
        return "STATUS_SUCCEEDED"

    def add_playlist_items(self, pid, video_ids, duplicates=False):
        self.playlists[pid]["tracks"].extend(video_ids)
        self.added.append((pid, list(video_ids)))
        return {"status": "STATUS_SUCCEEDED"}

    def remove_playlist_items(self, pid, videos):
        gone = {v["videoId"] for v in videos}
        assert all(v.get("setVideoId") == "set-" + v["videoId"] for v in videos)  # removal needs the set ids
        self.playlists[pid]["tracks"] = [v for v in self.playlists[pid]["tracks"] if v not in gone]
        self.removed.append((pid, [v["videoId"] for v in videos]))
        return "STATUS_SUCCEEDED"

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
    assert mp.read_export(f)["replace"] is False  # no flag: top up as always


def test_read_export_reads_the_replace_flag(tmp_path):
    f = tmp_path / "playlist-random.json"
    f.write_text(json.dumps({"app": "scorekeep-playlist", "name": "Scorekeep · Random Mix", "replace": True,
                             "tracks": [{"game": "Hades II", "title": "No Escape", "videoId": "v1"}]}), encoding="utf-8")
    assert mp.read_export(f)["replace"] is True
    f.write_text(json.dumps({"name": "x", "replace": "yes", "tracks": []}), encoding="utf-8")
    assert mp.read_export(f)["replace"] is False  # only a literal true counts


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
    rep = mp.sync_playlist(yt, "Scorekeep · Liked Songs", TRACKS)
    assert rep["created"] is True and rep["added"] == 2 and rep["already"] == 0
    (title, description, privacy), = yt.created
    assert title == "Scorekeep · Liked Songs"
    assert mp.MARKER in description and mp.LEGACY_MARKER not in description
    assert privacy == "PRIVATE"
    assert yt.added == [("PL1", ["v1", "v2"])] and yt.edited == []


LEGACY_DESCRIPTION = "Built by vgm-finder from your exported picks. # vgm-finder"


def test_sync_tops_up_and_renames_a_playlist_from_before_the_rename():
    yt = FakeYT(playlists={"PLX": {"title": "vgm-finder · Liked Songs", "description": LEGACY_DESCRIPTION,
                                   "tracks": ["v1"]}})
    rep = mp.sync_playlist(yt, "Scorekeep · Liked Songs", TRACKS)
    assert rep["created"] is False and rep["added"] == 1 and rep["already"] == 1
    assert rep["renamed"] == "vgm-finder · Liked Songs"
    assert yt.created == [] and yt.added == [("PLX", ["v2"])]  # the same playlist, never a second one
    assert yt.edited == [("PLX", "Scorekeep · Liked Songs", mp.DESCRIPTION)]
    assert yt.playlists["PLX"]["title"] == "Scorekeep · Liked Songs"
    rep = mp.sync_playlist(yt, "Scorekeep · Liked Songs", TRACKS)  # the rerun finds it under the new name
    assert rep["renamed"] is None and rep["added"] == 0 and len(yt.edited) == 1


def test_sync_refreshes_the_marker_on_a_custom_list_without_renaming_it():
    yt = FakeYT(playlists={"PLX": {"title": "Mix", "description": LEGACY_DESCRIPTION, "tracks": ["v1", "v2"]}})
    rep = mp.sync_playlist(yt, "Mix", TRACKS)
    assert rep["renamed"] is None and rep["added"] == 0
    assert yt.edited == [("PLX", "Mix", mp.DESCRIPTION)]


def test_sync_prefers_the_current_name_over_the_old_one():
    yt = FakeYT(playlists={
        "PLOLD": {"title": "vgm-finder · Queue", "description": LEGACY_DESCRIPTION, "tracks": ["z"]},
        "PLNEW": {"title": "Scorekeep · Queue", "description": mp.DESCRIPTION, "tracks": ["v1"]},
    })
    rep = mp.sync_playlist(yt, "Scorekeep · Queue", TRACKS)
    assert rep["renamed"] is None and yt.added == [("PLNEW", ["v2"])] and yt.edited == []


def test_sync_skips_an_unmarked_namesake_under_the_old_name_too():
    yt = FakeYT(playlists={"PLX": {"title": "vgm-finder · Queue", "description": "hand-made", "tracks": ["z"]}})
    rep = mp.sync_playlist(yt, "Scorekeep · Queue", TRACKS)
    assert rep["skipped"] is True and yt.created == [] and yt.edited == []


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


def test_sync_replace_makes_the_playlist_match_the_export():
    # the random mix: yesterday's 3 tracks, today's export keeps one and brings two
    yt = FakeYT(playlists={"PLX": {"title": "Scorekeep · Random Mix", "description": mp.DESCRIPTION,
                                   "tracks": ["old1", "v1", "old2"]}})
    rep = mp.sync_playlist(yt, "Scorekeep · Random Mix", TRACKS, replace=True)
    assert rep["removed"] == 2 and rep["added"] == 1 and rep["already"] == 1 and rep["created"] is False
    assert yt.removed == [("PLX", ["old1", "old2"])] and yt.added == [("PLX", ["v2"])]
    assert yt.playlists["PLX"]["tracks"] == ["v1", "v2"]
    assert yt.created == []  # the same playlist, never a second one


def test_sync_replace_on_a_fresh_playlist_removes_nothing():
    yt = FakeYT()
    rep = mp.sync_playlist(yt, "Scorekeep · Random Mix", TRACKS, replace=True)
    assert rep["created"] is True and rep["removed"] == 0 and rep["added"] == 2
    assert yt.removed == []


def test_sync_replace_leaves_a_matching_playlist_alone():
    yt = FakeYT(playlists={"PLX": {"title": "Mix", "description": mp.DESCRIPTION, "tracks": ["v1", "v2"]}})
    rep = mp.sync_playlist(yt, "Mix", TRACKS, replace=True)
    assert rep["removed"] == 0 and rep["added"] == 0 and rep["already"] == 2
    assert yt.removed == [] and yt.added == []


def test_sync_replace_never_touches_a_hand_made_namesake():
    yt = FakeYT(playlists={"PLX": {"title": "Scorekeep · Random Mix", "description": "my own", "tracks": ["z"]}})
    rep = mp.sync_playlist(yt, "Scorekeep · Random Mix", TRACKS, replace=True)
    assert rep["skipped"] is True and yt.removed == [] and yt.playlists["PLX"]["tracks"] == ["z"]


def test_sync_without_replace_still_only_tops_up():
    yt = FakeYT(playlists={"PLX": {"title": "Mix", "description": mp.DESCRIPTION, "tracks": ["old1", "v1"]}})
    rep = mp.sync_playlist(yt, "Mix", TRACKS)
    assert rep["removed"] == 0 and yt.removed == [] and yt.playlists["PLX"]["tracks"] == ["old1", "v1", "v2"]


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


def test_sync_retries_the_fresh_playlist_409(monkeypatch):
    naps = []
    monkeypatch.setattr(mp.time, "sleep", naps.append)
    yt = FakeYT()
    real_add = yt.add_playlist_items
    fails = ["Server returned HTTP 409: Conflict."] * 2
    def flaky(pid, video_ids, duplicates=False):
        if fails:
            raise RuntimeError(fails.pop(0))
        return real_add(pid, video_ids, duplicates=duplicates)
    yt.add_playlist_items = flaky
    rep = mp.sync_playlist(yt, "Mix", TRACKS)
    assert rep["created"] is True and rep["added"] == 2
    assert yt.added == [("PL1", ["v1", "v2"])]
    assert naps == [2, 5]  # backed off twice, then the settle landed


def test_sync_does_not_retry_non_409_errors(monkeypatch):
    naps = []
    monkeypatch.setattr(mp.time, "sleep", naps.append)
    yt = FakeYT()
    def dead(pid, video_ids, duplicates=False):
        raise RuntimeError("Server returned HTTP 500: oops.")
    yt.add_playlist_items = dead
    with pytest.raises(RuntimeError):
        mp.sync_playlist(yt, "Mix", TRACKS)
    assert naps == []  # a real failure surfaces immediately


# ---------------------------------------------------------------------- glob

def test_expand_args_globs_for_windows_shells(tmp_path, monkeypatch):
    (tmp_path / "playlist-a.json").write_text("{}", encoding="utf-8")
    (tmp_path / "playlist-b.json").write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert mp.expand_args(["playlist-*.json"]) == ["playlist-a.json", "playlist-b.json"]
    assert mp.expand_args(["missing.json"]) == ["missing.json"]


def test_pick_auth_prefers_the_app_sign_in_only_when_it_is_complete(tmp_path):
    browser, oauth = tmp_path / "browser.json", tmp_path / "oauth.json"
    keys = {"YTM_CLIENT_ID": "id.apps.googleusercontent.com", "YTM_CLIENT_SECRET": "s3cret"}
    assert mp.pick_auth(browser, oauth, keys) is None  # neither file: nothing to sign in with
    browser.write_text("{}", encoding="utf-8")
    assert mp.pick_auth(browser, oauth, keys) == ("browser", browser)  # no oauth.json yet
    oauth.write_text("", encoding="utf-8")
    assert mp.pick_auth(browser, oauth, keys)[0] == "browser"  # an empty file (an unset secret) is not a sign-in
    oauth.write_text('{"refresh_token": "r"}', encoding="utf-8")
    assert mp.pick_auth(browser, oauth, keys) == ("youtube-api", oauth, keys["YTM_CLIENT_ID"], "s3cret")
    assert mp.pick_auth(browser, oauth, {"YTM_CLIENT_ID": "id"})[0] == "browser"  # the secret missing
    browser.unlink()
    assert mp.pick_auth(browser, oauth, keys)[0] == "youtube-api"  # the API sign-in alone is enough
