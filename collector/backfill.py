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
SEEDS_PATH = collect.ROOT / "collector" / "seeds.json"
IGDB_BAR = 200          # rating_count floor: the "deep catalog" tier, ~900 games
IGDB_RECENT_BAR = 15    # recent releases can't have old-game rating counts
IGDB_RECENT_YEARS = 3
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


def _igdb_query(where, offset):
    cid = os.environ.get("TWITCH_CLIENT_ID")
    secret = os.environ.get("TWITCH_CLIENT_SECRET")
    if not cid or not secret:
        raise RuntimeError("TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET not set")
    tok = requests.post("https://id.twitch.tv/oauth2/token", timeout=30, params={
        "client_id": cid, "client_secret": secret,
        "grant_type": "client_credentials"}).json()["access_token"]
    query = (f"fields name, slug, first_release_date, rating_count, cover.image_id, platforms, "
             f"involved_companies.company.name, involved_companies.developer; "
             f"where {where} & game_type = (0,4,8,9); "
             f"sort rating_count desc; limit {IGDB_PAGE}; offset {offset};")
    resp = requests.post("https://api.igdb.com/v4/games", data=query.encode(), timeout=30,
                         headers={"Client-ID": cid, "Authorization": f"Bearer {tok}"})
    resp.raise_for_status()
    return resp.content


def load_seeds(path=None):
    try:
        d = json.loads(Path(path or SEEDS_PATH).read_text(encoding="utf-8"))
        return [s for s in d.get("igdb", []) if isinstance(s, str) and s]
    except (OSError, ValueError):
        return []


def default_fetch(url):
    if url.startswith("igdb-seeds:"):
        slugs = load_seeds()
        if not slugs:
            return b"[]"
        quoted = ",".join(f'"{s}"' for s in slugs)
        return _igdb_query(f"slug = ({quoted})", 0)
    if url.startswith("igdb-top:"):
        return _igdb_query(f"rating_count >= {IGDB_BAR}", int(url.split(":", 1)[1]))
    if url.startswith("igdb-recent:"):
        import time
        cutoff = int(time.time()) - IGDB_RECENT_YEARS * 365 * 86400
        return _igdb_query(f"rating_count >= {IGDB_RECENT_BAR} & first_release_date >= {cutoff}",
                           int(url.split(":", 1)[1]))
    return collect.fetch_feed(url)


def load_state(path):
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(d, dict):
            return {"steamStart": int(d.get("steamStart", 0)),
                    "igdbOffset": int(d.get("igdbOffset", 0)),
                    "igdbRecentOffset": int(d.get("igdbRecentOffset", 0)),
                    "checked": list(d.get("checked", []))}
    except (OSError, ValueError):
        pass
    return {"steamStart": 0, "igdbOffset": 0, "igdbRecentOffset": 0, "checked": []}


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


def seeds_leg(releases, fetch_fn, resolve_fn, seen_at):
    """Hand-picked franchise favorites: always a row, no rating bars, and the
    checked set is ignored so seeds keep self-upgrading toward real albums."""
    try:
        games = json.loads(fetch_fn("igdb-seeds:0"))
    except Exception as exc:
        print(f"::warning::seeds leg failed: {exc}")
        return 0
    added = 0
    for g in games if isinstance(games, list) else []:
        name = (g.get("name") or "").strip()
        stamp = g.get("first_release_date")
        if not name or not stamp:
            continue
        when = datetime.fromtimestamp(stamp, tz=timezone.utc)
        try:
            results = resolve_fn(collect._query(name))
            # seeds are hand-vouched single games: strict first, then the
            # token-vocabulary relaxation, and no year anchor (classic albums
            # often reach streaming decades late)
            hit = (collect._match_album(results, collect.normalize_title(name))
                   or collect._match_album_tokens(results, name))
        except Exception:
            continue
        cover = (g.get("cover") or {}).get("image_id")
        cover_url = (f"https://images.igdb.com/igdb/image/upload/t_cover_big/{cover}.jpg"
                     if cover else None)
        item = {"game": name, "company": collect.company_of(g), "console": collect.is_console(g),
                "url": f"https://www.igdb.com/games/{g.get('slug') or g.get('id')}",
                "date": when.strftime("%Y-%m-%d"),
                "title": f"{name} Soundtrack", "composers": []}  # stable slug: upgrades the existing row
        if hit:
            item.update({"albumTitle": hit["title"], "composers": hit["composers"],
                         "ytmAlbumUrl": hit["url"], "art": hit["art"] or cover_url})
        else:
            item.update({"art": cover_url})
        a, _ = collect.merge(releases, [item], IGDB_SRC, seen_at)
        added += a
    print(f"seeds leg: {len(games) if isinstance(games, list) else 0} seeds, {added} new rows")
    return added


def igdb_leg(releases, state, fetch_fn, resolve_fn, seen_at,
             prefix="igdb-top", offset_key="igdbOffset", cap=None):
    cap = YTM_CAP if cap is None else cap
    checked = set(state["checked"])
    looked = added = 0
    exhausted = False
    while looked < cap and not exhausted:
        try:
            games = json.loads(fetch_fn(f"{prefix}:{state[offset_key]}"))
        except Exception as exc:
            print(f"::warning::{prefix} backfill page {state[offset_key]} failed: {exc}")
            return added, False, looked
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
            if looked >= cap:
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
            console = collect.is_console(g)
            if hit:
                item = {"title": hit["title"], "game": name, "composers": hit["composers"],
                        "company": company, "console": console,
                        "url": f"https://www.igdb.com/games/{g.get('slug') or gid}",
                        "date": when.strftime("%Y-%m-%d"),
                        "ytmAlbumUrl": hit["url"], "art": hit["art"] or cover_url}
            elif (g.get("rating_count") or 0) >= NOALBUM_BAR:
                # canon-tier game with no verifiable album (Nintendo, licensed
                # compilations): a search row beats absence, and it upgrades
                # itself by slug collision if a real album ever appears
                item = {"title": f"{name} Soundtrack", "game": name, "composers": [],
                        "company": company, "console": console,
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
                state[offset_key] += IGDB_PAGE
    state["checked"] = sorted(checked)
    print(f"{prefix} leg: {looked} lookups, {len(checked)} games checked, {added} albums added"
          + (", exhausted" if exhausted else ""))
    return added, exhausted, looked


TRACKS_CAP_BACKFILL = 250


def run(fetch_fn=default_fetch, resolve_fn=collect.ytm_resolve, album_fn=collect.ytm_album,
        itunes_fn=collect.catalog_tracks, data_path=collect.DATA_PATH,
        state_path=STATE_PATH, now=None):
    now = now or datetime.now(timezone.utc)
    seen_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    data = collect.load_data(data_path)
    releases = data["releases"]
    state = load_state(state_path)
    before = json.dumps(releases, sort_keys=True, ensure_ascii=False)

    seeds_leg(releases, fetch_fn, resolve_fn, seen_at)
    steam_leg(releases, state, fetch_fn, seen_at)
    _, top_done, spent = igdb_leg(releases, state, fetch_fn, resolve_fn, seen_at)
    _, recent_done, _ = igdb_leg(releases, state, fetch_fn, resolve_fn, seen_at,
                                 prefix="igdb-recent", offset_key="igdbRecentOffset",
                                 cap=YTM_CAP - spent)
    igdb_done = top_done and recent_done
    fetched = collect.fill_tracks(releases, album_fn, itunes_fn, cap=TRACKS_CAP_BACKFILL)
    print(f"tracklists: {fetched} looked up")

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
