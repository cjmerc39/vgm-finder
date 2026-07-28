"""Backfill classic soundtracks into data/releases.json.

Walks two legs with a committed cursor (collector/backfill-state.json):
- Steam's most-reviewed soundtracks (Reviews_DESC), up to STEAM_TARGET rows
- IGDB's top-rated games (rating_count >= IGDB_BAR), each checked once
  against YouTube Music with the same strict matcher the daily run uses

Manual: dispatch .github/workflows/backfill.yml (or run locally with
TWITCH_CLIENT_ID/SECRET set). Each run is capped; dispatch until it reports
"backfill complete". Idempotent: re-seen albums merge, checked games skip.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect

STATE_PATH = collect.ROOT / "collector" / "backfill-state.json"
IGDB_BAR = 200          # rating_count floor: the "deep catalog" tier, ~900 games
NOALBUM_BAR = 400       # canon tier: games this notable get a search row even with no YTM album
IGDB_PAGE = 500
STEAM_TARGET = 600      # most-reviewed soundtracks to ingest overall
STEAM_PAGE = 50
STEAM_PAGES_PER_RUN = 6
YTM_CAP = 250           # album lookups per run

STEAM_SRC = {"name": "steam", "type": "catalog"}
IGDB_SRC = {"name": "igdb", "type": "catalog"}


def steam_page_url(start):
    return ("https://store.steampowered.com/search/results/"
            f"?query&start={start}&count={STEAM_PAGE}&category1=990"
            "&sort_by=Reviews_DESC&infinite=1&l=english&cc=US")


def igdb_top_fetch(offset):
    cid = os.environ.get("TWITCH_CLIENT_ID")
    secret = os.environ.get("TWITCH_CLIENT_SECRET")
    if not cid or not secret:
        raise RuntimeError("TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET not set")
    tok = requests.post("https://id.twitch.tv/oauth2/token", timeout=30, params={
        "client_id": cid, "client_secret": secret,
        "grant_type": "client_credentials"}).json()["access_token"]
    query = (f"fields name, slug, first_release_date, rating_count, cover.image_id, "
             f"involved_companies.company.name, involved_companies.developer; "
             f"where rating_count >= {IGDB_BAR} & game_type = (0,4,8,9); "
             f"sort rating_count desc; limit {IGDB_PAGE}; offset {offset};")
    resp = requests.post("https://api.igdb.com/v4/games", data=query.encode(), timeout=30,
                         headers={"Client-ID": cid, "Authorization": f"Bearer {tok}"})
    resp.raise_for_status()
    return resp.content


def default_fetch(url):
    if url.startswith("igdb-top:"):
        return igdb_top_fetch(int(url.split(":", 1)[1]))
    return collect.fetch_feed(url)


def load_state(path):
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(d, dict):
            return {"steamStart": int(d.get("steamStart", 0)),
                    "igdbOffset": int(d.get("igdbOffset", 0)),
                    "checked": list(d.get("checked", []))}
    except (OSError, ValueError):
        pass
    return {"steamStart": 0, "igdbOffset": 0, "checked": []}


def steam_leg(releases, state, fetch_fn, seen_at):
    pages = 0
    added = merged = 0
    while state["steamStart"] < STEAM_TARGET and pages < STEAM_PAGES_PER_RUN:
        try:
            items = collect.parse_steam(fetch_fn(steam_page_url(state["steamStart"])))
        except Exception as exc:
            print(f"::warning::steam backfill page {state['steamStart']} failed: {exc}")
            break
        a, m = collect.merge(releases, items, STEAM_SRC, seen_at)
        added += a
        merged += m
        state["steamStart"] += STEAM_PAGE
        pages += 1
    print(f"steam leg: cursor {state['steamStart']}/{STEAM_TARGET}, {added} new, {merged} merged")
    return added


def igdb_leg(releases, state, fetch_fn, resolve_fn, seen_at):
    checked = set(state["checked"])
    looked = added = 0
    exhausted = False
    while looked < YTM_CAP and not exhausted:
        try:
            games = json.loads(fetch_fn(f"igdb-top:{state['igdbOffset']}"))
        except Exception as exc:
            print(f"::warning::igdb backfill page {state['igdbOffset']} failed: {exc}")
            return added, False
        if not isinstance(games, list) or not games:
            exhausted = True
            break
        page_done = True
        for g in games:
            gid = g.get("id")
            name = (g.get("name") or "").strip()
            stamp = g.get("first_release_date")
            if gid is None or gid in checked:
                continue
            if not name or not stamp:
                checked.add(gid)
                continue
            if looked >= YTM_CAP:
                page_done = False
                break
            looked += 1
            when = datetime.fromtimestamp(stamp, tz=timezone.utc)
            try:
                hit = collect._match_album(resolve_fn(collect._query(name)),
                                           collect.normalize_title(name), year=when.year)
            except Exception:
                continue  # transient lookup failure: leave unchecked, retry next run
            checked.add(gid)
            cover = (g.get("cover") or {}).get("image_id")
            cover_url = (f"https://images.igdb.com/igdb/image/upload/t_cover_big/{cover}.jpg"
                         if cover else None)
            company = collect.company_of(g)
            if hit:
                item = {"title": hit["title"], "game": name, "composers": hit["composers"],
                        "company": company,
                        "url": f"https://www.igdb.com/games/{g.get('slug') or gid}",
                        "date": when.strftime("%Y-%m-%d"),
                        "ytmAlbumUrl": hit["url"], "art": hit["art"] or cover_url}
            elif (g.get("rating_count") or 0) >= NOALBUM_BAR:
                # canon-tier game with no verifiable album (Nintendo, licensed
                # compilations): a search row beats absence, and it upgrades
                # itself by slug collision if a real album ever appears
                item = {"title": f"{name} Soundtrack", "game": name, "composers": [],
                        "company": company,
                        "url": f"https://www.igdb.com/games/{g.get('slug') or gid}",
                        "date": when.strftime("%Y-%m-%d"), "art": cover_url}
            else:
                continue
            a, _ = collect.merge(releases, [item], IGDB_SRC, seen_at)
            added += a
        if page_done:
            if len(games) < IGDB_PAGE:
                exhausted = True
            else:
                state["igdbOffset"] += IGDB_PAGE
    state["checked"] = sorted(checked)
    print(f"igdb leg: {looked} lookups, {len(checked)} games checked, {added} albums added"
          + (", exhausted" if exhausted else ""))
    return added, exhausted


TOPTRACKS_CAP_BACKFILL = 150


def run(fetch_fn=default_fetch, resolve_fn=collect.ytm_resolve, album_fn=collect.ytm_album,
        data_path=collect.DATA_PATH, state_path=STATE_PATH, now=None):
    now = now or datetime.now(timezone.utc)
    seen_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    data = collect.load_data(data_path)
    releases = data["releases"]
    state = load_state(state_path)
    before = json.dumps(releases, sort_keys=True, ensure_ascii=False)

    steam_leg(releases, state, fetch_fn, seen_at)
    _, igdb_done = igdb_leg(releases, state, fetch_fn, resolve_fn, seen_at)
    fetched = collect.fill_top_tracks(releases, album_fn, cap=TOPTRACKS_CAP_BACKFILL)
    print(f"top tracks: {fetched} albums fetched")

    if json.dumps(releases, sort_keys=True, ensure_ascii=False) != before:
        data["updatedAt"] = seen_at
        Path(data_path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                                   encoding="utf-8")
        print(f"wrote {Path(data_path).as_posix()}: {len(releases)} releases")
    Path(state_path).write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    if igdb_done and state["steamStart"] >= STEAM_TARGET:
        print("backfill complete — no need to dispatch again")
    else:
        print("backfill in progress — dispatch again to continue")
    return 0


if __name__ == "__main__":
    sys.exit(run())
