"""Backfill tests: cursor advance, checked-game skip, caps, idempotency."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import backfill
import collect
from test_collect import fake_resolve, no_album, raw

NOW = datetime(2026, 7, 28, 12, 0, 0, tzinfo=timezone.utc)


def make_fetch(counter=None):
    def fetch(url):
        if counter is not None:
            counter.append(url)
        if url.startswith("igdb-top:"):
            return raw("igdb-games.json")  # 25 games < page size -> leg exhausts
        if "store.steampowered.com" in url:
            return raw("steam-top-soundtracks.json")
        raise AssertionError("unexpected url " + url)
    return fetch


def counting_resolve(counter):
    def resolve(q):
        counter.append(q)
        return fake_resolve(q)
    return resolve


def run_once(tmp_path, monkeypatch, resolve=None, fetches=None, **caps):
    for k, v in caps.items():
        monkeypatch.setattr(backfill, k, v)
    data_path = tmp_path / "releases.json"
    state_path = tmp_path / "backfill-state.json"
    assert backfill.run(fetch_fn=make_fetch(fetches), resolve_fn=resolve or fake_resolve, album_fn=no_album,
                        data_path=data_path, state_path=state_path, now=NOW) == 0
    return (json.loads(data_path.read_text(encoding="utf-8")),
            json.loads(state_path.read_text(encoding="utf-8")))


def test_backfill_ingests_both_legs(tmp_path, monkeypatch, capsys):
    data, state = run_once(tmp_path, monkeypatch, STEAM_TARGET=50, STEAM_PAGES_PER_RUN=1)
    titles = " | ".join(r["title"] for r in data["releases"])
    assert "Hollow Knight - Official Soundtrack" in titles  # steam classics leg
    assert "Fading Echo (Original Soundtrack)" in titles    # igdb album leg
    hk = next(r for r in data["releases"] if r["title"] == "Hollow Knight - Official Soundtrack")
    assert hk["game"] == "Hollow Knight" and hk["art"].endswith("/header.jpg")
    assert hk["date"] == "2017-02-24"  # classics keep their historical dates
    fading = next(r for r in data["releases"] if r["game"] == "Fading Echo")
    assert fading["ytmAlbumUrl"] and fading["composers"] == ["Maxwell Sterling"] and fading["art"]
    assert state["steamStart"] == 50
    assert len(state["checked"]) == 25  # every fixture game checked exactly once
    assert "backfill complete" in capsys.readouterr().out  # both legs done at these targets


def test_backfill_second_run_skips_checked_and_rewrites_nothing(tmp_path, monkeypatch):
    data_path = tmp_path / "releases.json"
    state_path = tmp_path / "backfill-state.json"
    monkeypatch.setattr(backfill, "STEAM_TARGET", 50)
    monkeypatch.setattr(backfill, "STEAM_PAGES_PER_RUN", 1)
    backfill.run(fetch_fn=make_fetch(), resolve_fn=fake_resolve, album_fn=no_album,
                 data_path=data_path, state_path=state_path, now=NOW)
    first = data_path.read_text(encoding="utf-8")
    lookups = []
    backfill.run(fetch_fn=make_fetch(), resolve_fn=counting_resolve(lookups), album_fn=no_album,
                 data_path=data_path, state_path=state_path,
                 now=datetime(2026, 7, 29, 12, 0, 0, tzinfo=timezone.utc))
    assert lookups == []  # every game already checked: zero repeat album lookups
    assert data_path.read_text(encoding="utf-8") == first  # append-only: nothing rewritten


def test_backfill_respects_ytm_cap_and_reports_progress(tmp_path, monkeypatch, capsys):
    lookups = []
    data, state = run_once(tmp_path, monkeypatch, resolve=counting_resolve(lookups),
                           STEAM_TARGET=0, YTM_CAP=5)
    assert len(lookups) == 5
    assert len(state["checked"]) == 5  # only capped prefix marked done
    assert "in progress" in capsys.readouterr().out


def test_backfill_gives_canon_games_search_rows_when_no_album_exists(tmp_path, monkeypatch):
    page = json.dumps([
        {"id": 1, "name": "The Legend of Zelda: Breath of the Wild",
         "slug": "botw", "first_release_date": 1488499200, "rating_count": 2926,
         "cover": {"image_id": "co3p2d"}},
        {"id": 2, "name": "Obscure Indie Nobody Rated", "slug": "obscure",
         "first_release_date": 1488499200, "rating_count": 210},
    ]).encode()
    def fetch(url):
        if url.startswith("igdb-top:"):
            return page
        raise AssertionError(url)
    monkeypatch.setattr(backfill, "STEAM_TARGET", 0)
    data_path = tmp_path / "releases.json"
    backfill.run(fetch_fn=fetch, resolve_fn=lambda q: [], album_fn=no_album,  # YTM offers nothing
                 data_path=data_path, state_path=tmp_path / "s.json", now=NOW)
    data = json.loads(data_path.read_text(encoding="utf-8"))
    assert len(data["releases"]) == 1  # canon game lands, obscure one doesn't
    row = data["releases"][0]
    assert row["title"] == "The Legend of Zelda: Breath of the Wild Soundtrack"
    assert row["game"] == "The Legend of Zelda: Breath of the Wild"
    assert row["ytmAlbumUrl"] is None  # tap falls back to the YTM search
    assert row["art"] == "https://images.igdb.com/igdb/image/upload/t_cover_big/co3p2d.jpg"
    assert row["ytmSearchUrl"].startswith("https://music.youtube.com/search?q=")


def test_backfill_steam_cursor_pages_across_runs(tmp_path, monkeypatch):
    fetches = []
    _, state = run_once(tmp_path, monkeypatch, fetches=fetches,
                        STEAM_TARGET=150, STEAM_PAGES_PER_RUN=2, YTM_CAP=0)
    steam_urls = [u for u in fetches if "steampowered" in u]
    assert ["start=0" in steam_urls[0], "start=50" in steam_urls[1]] == [True, True]
    assert state["steamStart"] == 100  # resumes at page 3 next run
