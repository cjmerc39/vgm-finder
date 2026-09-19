"""The publisher's playlist calls through YouTube's official Data API v3.

YouTube Music refuses app sign-ins on its own internal API (HTTP 400 on
every call, even a search, as of 2026-09), and copied browser logins were
ended by Google within hours when used from GitHub's runners. YouTube Music
playlists are YouTube playlists, so the official API can make and edit
them. YouTubeApi answers the handful of ytmusicapi calls make_playlists.py
makes, in the same shapes, so the sync logic does not change. Search stays
on ytmusicapi, which needs no sign-in for it.

Quota: a Google Cloud project gets 10,000 units a day, reset at midnight
Pacific. A page of listing costs 1 unit; creating a playlist, renaming it,
and adding or removing one track cost 50 each, so a day holds about 200
track changes. A run that meets the limit stops with QuotaExceeded; what it
already did stays, and the next run tops up the rest.
"""
import json
import re
import time
from pathlib import Path

API = "https://www.googleapis.com/youtube/v3"
TOKEN_URL = "https://oauth2.googleapis.com/token"
LIST, WRITE = 1, 50   # quota units per call
RETRY_WAITS = (2, 5, 10)   # seconds before trying an aborted insert again


class QuotaExceeded(RuntimeError):
    pass


class YouTubeApi:
    def __init__(self, token_path, client_id, client_secret, session=None, searcher=None, sleep=time.sleep):
        token = json.loads(Path(token_path).read_text(encoding="utf-8"))
        self.refresh_token = token["refresh_token"]
        self.client_id, self.client_secret = client_id, client_secret
        if session is None:
            import requests  # lazy: tests pass a fake session
            session = requests.Session()
        self.http = session
        self._searcher = searcher
        self._sleep = sleep
        self._access = None
        self._descriptions = {}
        self.units = 0

    # ------------------------------------------------------------ plumbing
    def _refresh(self):
        r = self.http.post(TOKEN_URL, data={"client_id": self.client_id, "client_secret": self.client_secret,
                                            "refresh_token": self.refresh_token, "grant_type": "refresh_token"},
                           timeout=30)
        d = r.json()
        if "access_token" not in d:
            raise RuntimeError(f"YouTube sign-in could not be refreshed: {d.get('error')}: "
                               f"{d.get('error_description', '')}")
        self._access = d["access_token"]

    def _call(self, method, path, cost, params=None, body=None):
        if self._access is None:
            self._refresh()
        for attempt in (1, 2):
            r = self.http.request(method, f"{API}/{path}", params=params, json=body,
                                  headers={"Authorization": f"Bearer {self._access}"}, timeout=30)
            if r.status_code == 401 and attempt == 1:
                self._refresh()  # the access token lapsed mid-run
                continue
            break
        self.units += cost
        d = r.json() if r.content else {}
        if not r.ok:
            err = d.get("error") or {}
            reasons = {e.get("reason") for e in err.get("errors") or []}
            if reasons & {"quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded"}:
                raise QuotaExceeded("YouTube's daily allowance for the publisher is used up; it resets at "
                                    "midnight Pacific time, and the next publish tops up what is missing")
            raise RuntimeError(f"YouTube API {method} {path}: HTTP {r.status_code}: {err.get('message', '')}")
        return d

    def _pages(self, path, params):
        page = None
        while True:
            d = self._call("GET", path, LIST, dict(params, maxResults=50, **({"pageToken": page} if page else {})))
            yield from d.get("items") or []
            page = d.get("nextPageToken")
            if not page:
                return

    # ------------------------------------------- the calls make_playlists makes
    def channel_title(self):
        items = self._call("GET", "channels", LIST, {"part": "snippet", "mine": "true"}).get("items") or []
        return (items[0].get("snippet") or {}).get("title") if items else None

    def get_library_playlists(self, limit=None):
        out = []
        for it in self._pages("playlists", {"part": "snippet", "mine": "true"}):
            s = it.get("snippet") or {}
            self._descriptions[it["id"]] = s.get("description") or ""
            out.append({"playlistId": it["id"], "title": s.get("title") or ""})
        return out

    def get_playlist(self, pid, limit=None):
        if pid not in self._descriptions:
            items = self._call("GET", "playlists", LIST, {"part": "snippet", "id": pid}).get("items") or []
            self._descriptions[pid] = ((items[0].get("snippet") or {}).get("description") or "") if items else ""
        tracks = []
        for it in self._pages("playlistItems", {"part": "snippet", "playlistId": pid}):
            vid = ((it.get("snippet") or {}).get("resourceId") or {}).get("videoId")
            if vid:
                tracks.append({"videoId": vid, "setVideoId": it["id"]})  # the item id removes it
        return {"description": self._descriptions[pid], "tracks": tracks}

    def create_playlist(self, title, description, privacy_status="PRIVATE"):
        d = self._call("POST", "playlists", WRITE, {"part": "snippet,status"},
                       {"snippet": {"title": title, "description": description},
                        "status": {"privacyStatus": privacy_status.lower()}})
        self._descriptions[d["id"]] = description
        return d["id"]

    def add_playlist_items(self, pid, video_ids, duplicates=False):
        """One insert per track. YouTube aborts some inserts with a 409 (a
        playlist made a second ago, inserts close together) or a 5xx; those
        are tried again after RETRY_WAITS. A track YouTube still will not add
        (removed, private, blocked) is reported and the rest carry on; the
        daily limit stops the run."""
        failed = []
        for v in video_ids:
            for wait in RETRY_WAITS + (None,):
                try:
                    self._call("POST", "playlistItems", WRITE, {"part": "snippet"},
                               {"snippet": {"playlistId": pid, "resourceId": {"kind": "youtube#video", "videoId": v}}})
                    break
                except QuotaExceeded:
                    raise
                except RuntimeError as e:
                    if wait is None or not re.search(r"HTTP (409|5\d\d)\b", str(e)):
                        failed.append((v, str(e)))
                        break
                    self._sleep(wait)
        return {"status": "STATUS_SUCCEEDED", "failed": failed}

    def remove_playlist_items(self, pid, videos):
        for v in videos:
            self._call("DELETE", "playlistItems", WRITE, {"id": v["setVideoId"]})
        return "STATUS_SUCCEEDED"

    def edit_playlist(self, pid, title=None, description=None):
        if title is None:
            raise ValueError("YouTube needs the title on every playlist edit")
        desc = self._descriptions.get(pid, "") if description is None else description
        self._call("PUT", "playlists", WRITE, {"part": "snippet"},
                   {"id": pid, "snippet": {"title": title, "description": desc}})
        self._descriptions[pid] = desc
        return "STATUS_SUCCEEDED"

    def search(self, query, filter=None, limit=None):
        if self._searcher is None:
            from ytmusicapi import YTMusic
            self._searcher = YTMusic()  # public search needs no sign-in
        return self._searcher.search(query, filter=filter, limit=limit)
