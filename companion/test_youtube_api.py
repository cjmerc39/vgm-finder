"""The YouTube Data API adapter, driven against a small fake YouTube: the
sync logic runs through it unchanged, the sign-in refreshes itself, a
refused track is reported, and the daily limit stops the run clearly."""
import json

import pytest

import make_playlists as mp
import youtube_api as ya


class Resp:
    def __init__(self, status, body=None):
        self.status_code, self._body = status, body
        self.ok = 200 <= status < 300
        self.content = b"" if body is None else json.dumps(body).encode()

    def json(self):
        return self._body if self._body is not None else {}


def _err(status, reason, message="nope"):
    return Resp(status, {"error": {"code": status, "message": message, "errors": [{"reason": reason}]}})


class FakeYouTube:
    """Playlists and their items, paged two at a time so paging is exercised."""
    def __init__(self, playlists=None, refuse=(), quota_after=None):
        self.playlists = {}       # pid -> {title, description, privacy, items: [(item id, videoId)]}
        self.refuse, self.quota_after = set(refuse), quota_after
        self.calls, self.tokens, self._n = [], 0, 0
        self.expire_next = False
        for pid, p in (playlists or {}).items():
            self.playlists[pid] = {"title": p["title"], "description": p.get("description", ""), "privacy": "private",
                                   "items": [(self._item(), v) for v in p.get("tracks", [])]}

    def _item(self):
        self._n += 1
        return f"item{self._n}"

    def post(self, url, data=None, timeout=None):  # the token endpoint
        assert url == ya.TOKEN_URL and data["grant_type"] == "refresh_token" and data["refresh_token"] == "r1"
        self.tokens += 1
        return Resp(200, {"access_token": f"at{self.tokens}", "expires_in": 3599})

    def request(self, method, url, params=None, json=None, headers=None, timeout=None):
        assert headers["Authorization"] == f"Bearer at{self.tokens}"
        if self.expire_next:
            self.expire_next = False
            return Resp(401, {"error": {"message": "expired"}})
        path = url[len(ya.API) + 1:]
        self.calls.append((method, path))
        writes = sum(1 for m, _ in self.calls if m != "GET")
        if self.quota_after is not None and method != "GET" and writes > self.quota_after:
            return _err(403, "quotaExceeded", "The request cannot be completed because you have exceeded your quota.")
        params = params or {}
        if (method, path) == ("GET", "channels"):
            return Resp(200, {"items": [{"snippet": {"title": "CJ"}}]})
        if (method, path) == ("GET", "playlists"):
            if "id" in params:
                p = self.playlists[params["id"]]
                return Resp(200, {"items": [{"id": params["id"], "snippet": {"title": p["title"], "description": p["description"]}}]})
            return self._page([{"id": pid, "snippet": {"title": p["title"], "description": p["description"]}}
                               for pid, p in self.playlists.items()], params)
        if (method, path) == ("GET", "playlistItems"):
            return self._page([{"id": i, "snippet": {"resourceId": {"kind": "youtube#video", "videoId": v}}}
                               for i, v in self.playlists[params["playlistId"]]["items"]], params)
        if (method, path) == ("POST", "playlists"):
            self._n += 1
            pid = f"PL{self._n}"
            self.playlists[pid] = {"title": json["snippet"]["title"], "description": json["snippet"]["description"],
                                   "privacy": json["status"]["privacyStatus"], "items": []}
            return Resp(200, {"id": pid})
        if (method, path) == ("POST", "playlistItems"):
            v = json["snippet"]["resourceId"]["videoId"]
            if v in self.refuse:
                return _err(404, "videoNotFound", "Video not found.")
            self.playlists[json["snippet"]["playlistId"]]["items"].append((self._item(), v))
            return Resp(200, {"id": "new"})
        if (method, path) == ("DELETE", "playlistItems"):
            for p in self.playlists.values():
                p["items"] = [(i, v) for i, v in p["items"] if i != params["id"]]
            return Resp(204)
        if (method, path) == ("PUT", "playlists"):
            p = self.playlists[json["id"]]
            p["title"], p["description"] = json["snippet"]["title"], json["snippet"]["description"]
            return Resp(200, {"id": json["id"]})
        raise AssertionError(f"unexpected {method} {path}")

    @staticmethod
    def _page(items, params):
        start = int(params.get("pageToken") or 0)
        body = {"items": items[start:start + 2]}
        if start + 2 < len(items):
            body["nextPageToken"] = str(start + 2)
        return Resp(200, body)

    def videos(self, pid):
        return [v for _, v in self.playlists[pid]["items"]]


def _api(tmp_path, fake):
    tok = tmp_path / "oauth.json"
    tok.write_text(json.dumps({"refresh_token": "r1", "access_token": "stale"}), encoding="utf-8")
    return ya.YouTubeApi(tok, "cid", "secret", session=fake, searcher=object())


TRACKS = [{"game": "Hades", "title": "No Escape", "videoId": "v1"},
          {"game": "Hades", "title": "Good Riddance", "videoId": "v2"},
          {"game": "Hades", "title": "In the Blood", "videoId": "v3"}]


def test_the_sync_creates_a_private_marked_playlist_through_the_api(tmp_path):
    fake = FakeYouTube({"PLold": {"title": "Road trip", "tracks": ["x"]}})
    api = _api(tmp_path, fake)
    rep = mp.sync_playlist(api, "Scorekeep · Liked Songs", TRACKS)
    assert rep["created"] and rep["added"] == 3 and rep["unresolved"] == []
    pid = next(p for p, v in fake.playlists.items() if v["title"] == "Scorekeep · Liked Songs")
    assert fake.playlists[pid]["privacy"] == "private" and mp.MARKER in fake.playlists[pid]["description"]
    assert fake.videos(pid) == ["v1", "v2", "v3"] and fake.tokens == 1  # the stored access token is never trusted
    assert api.units == 1 + 50 + 3 * 50  # one list page, the playlist, three inserts


def test_replace_swaps_the_mix_and_pages_through_a_long_playlist(tmp_path):
    fake = FakeYouTube({"PLa": {"title": "Other", "tracks": []}, "PLb": {"title": "More", "tracks": []},
                        "PLmix": {"title": "Scorekeep · Random Mix", "description": mp.DESCRIPTION,
                                  "tracks": ["v1", "old1", "old2", "old3", "old4"]}})
    api = _api(tmp_path, fake)
    rep = mp.sync_playlist(api, "Scorekeep · Random Mix", TRACKS, replace=True)
    assert not rep["created"] and rep["removed"] == 4 and rep["added"] == 2 and rep["already"] == 1
    assert sorted(fake.videos("PLmix")) == ["v1", "v2", "v3"]


def test_a_playlist_from_before_the_rename_is_renamed_in_place(tmp_path):
    fake = FakeYouTube({"PLv": {"title": "vgm-finder · Liked Songs", "description": "old # vgm-finder", "tracks": ["v1"]}})
    rep = mp.sync_playlist(_api(tmp_path, fake), "Scorekeep · Liked Songs", TRACKS)
    assert rep["renamed"] == "vgm-finder · Liked Songs" and fake.playlists["PLv"]["title"] == "Scorekeep · Liked Songs"
    assert fake.playlists["PLv"]["description"] == mp.DESCRIPTION and fake.videos("PLv") == ["v1", "v2", "v3"]


def test_an_unmarked_namesake_is_left_alone(tmp_path):
    fake = FakeYouTube({"PLhand": {"title": "Scorekeep · Liked Songs", "description": "made by hand", "tracks": ["z"]}})
    rep = mp.sync_playlist(_api(tmp_path, fake), "Scorekeep · Liked Songs", TRACKS)
    assert rep["skipped"] and fake.videos("PLhand") == ["z"] and all(m == "GET" for m, _ in fake.calls)


def test_a_refused_track_is_reported_and_the_rest_are_added(tmp_path):
    fake = FakeYouTube(refuse={"v2"})
    rep = mp.sync_playlist(_api(tmp_path, fake), "Scorekeep · Liked Songs", TRACKS)
    assert rep["added"] == 2 and len(rep["unresolved"]) == 1 and "v2" in rep["unresolved"][0]


def test_the_daily_limit_stops_the_run_with_a_plain_message(tmp_path):
    fake = FakeYouTube(quota_after=2)  # the playlist and one track, then the limit
    with pytest.raises(ya.QuotaExceeded, match="resets at midnight Pacific"):
        mp.sync_playlist(_api(tmp_path, fake), "Scorekeep · Liked Songs", TRACKS)
    pid = next(iter(fake.playlists))
    assert fake.videos(pid) == ["v1"]  # what was done stays; the next run tops up


def test_a_lapsed_access_token_is_refreshed_once_mid_run(tmp_path):
    fake = FakeYouTube()
    api = _api(tmp_path, fake)
    assert api.channel_title() == "CJ" and fake.tokens == 1
    fake.expire_next = True
    assert api.get_library_playlists() == [] and fake.tokens == 2


def test_a_failed_refresh_says_so(tmp_path):
    class Dead(FakeYouTube):
        def post(self, url, data=None, timeout=None):
            return Resp(400, {"error": "invalid_grant", "error_description": "Token has been expired or revoked."})
    with pytest.raises(RuntimeError, match="could not be refreshed: invalid_grant"):
        _api(tmp_path, Dead()).get_library_playlists()
