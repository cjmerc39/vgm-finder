"""Genre fills the daily legs cannot make for rows that already exist.

--anime: TMDb files anime under Animation, and anime is Animation made in
Japanese. New film and TV rows get "Anime" as they arrive
(collect._tmdb_genres); this reads every existing film and TV row's full
TMDb details once (stored genres keep only three, so Animation can be cut)
and adds "Anime" where it belongs. Needs TMDB_API_KEY.

--games: IGDB's themes (Horror, Fantasy, Science fiction, Thriller...) say
how a game feels, where its genres say how it plays, and they line up with
film and TV genres. Every game row with no themes list is looked up on
IGDB: by the slug in its IGDB link; for a Steam row, whose link is the
soundtrack's own app, by the game's app id that Steam's store names for it;
or, when neither finds it, by exact name with the release year within one
year. A found
row gains `themes` (present even when empty) and, when it had no genres,
IGDB's genres. A row not found is tried again on a later run. --recent
limits it to rows first seen in the last 30 days (the daily step). Needs
TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET.

  python collector/fill_genres.py --anime --games     # the one-time fill (genres.yml)
  python collector/fill_genres.py --games --recent    # the daily step (collect.yml)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect

STEAM_APP = re.compile(r"store\.steampowered\.com/app/(\d+)")
IGDB_GAME = re.compile(r"igdb\.com/games/([^/?#]+)")
TMDB_TITLE = re.compile(r"themoviedb\.org/(movie|tv)/(\d+)")
GAME_FIELDS = "name, slug, first_release_date, genres.name, themes.name"
BATCH = 100
RECENT_DAYS = 30


def _first_seen(r):
    return min((s.get("seenAt") or "9999") for s in r.get("sources") or [{}])


def _chunks(items, n=BATCH):
    return [items[i:i + n] for i in range(0, len(items), n)]


def _quoted(values):
    return ",".join('"' + str(v).replace('"', '\\"') + '"' for v in values)


# ------------------------------------------------------------------- anime
def anime_fill(releases, details, log=print):
    """details(kind, tmdb id) -> the title's TMDb details. -> rows tagged."""
    checked = tagged = failed = 0
    for r in releases:
        if r.get("retired") or r.get("medium") not in ("film", "tv") or collect.ANIME in (r.get("genres") or []):
            continue
        m = next((TMDB_TITLE.search(s.get("url") or "") for s in r.get("sources") or []
                  if TMDB_TITLE.search(s.get("url") or "")), None)
        if not m:
            continue
        try:
            d = details(m.group(1), m.group(2))
        except Exception:
            failed += 1
            continue
        checked += 1
        if collect.is_anime([g.get("name") for g in d.get("genres") or []], d.get("original_language")):
            r["genres"] = list(r.get("genres") or []) + [collect.ANIME]
            tagged += 1
    log(f"anime: {checked} film and TV rows checked, {tagged} tagged Anime, {failed} lookups failed")
    return tagged


def tmdb_details(kind, tid):
    for attempt in (1, 2, 3):
        try:
            return collect._tmdb_get(f"{kind}/{tid}")
        except Exception as e:
            if attempt == 3 or "429" not in str(e):
                raise
            time.sleep(2 * attempt)  # rate limited: wait and try again


# ------------------------------------------------------------ game themes
def _apply(r, g):
    r["themes"] = collect.themes_of(g)
    if not r.get("genres"):
        genres = collect.genres_of(g)
        if genres:
            r["genres"] = genres
            return True
    return False


def _by_name(query, r, name):
    """The one IGDB game of exactly this name released within a year of the
    row's date, or None (none, or two of one name and year: left for a person)."""
    want = collect.normalize_title(name)
    year = int((r.get("date") or "0")[:4] or 0)
    hits = query("games", f'search "{name.replace(chr(34), chr(92) + chr(34))}"; fields {GAME_FIELDS}; limit 10;')
    match = [g for g in hits if collect.normalize_title(g.get("name") or "") == want and g.get("first_release_date")
             and abs(datetime.fromtimestamp(g["first_release_date"], tz=timezone.utc).year - year) <= 1]
    return match[0] if len(match) == 1 else None


def games_fill(releases, query, recent_since=None, steam_parent=None, log=print):
    """query(endpoint, body) -> IGDB results; steam_parent(app id) -> (game
    app id, game name) or None, since a Steam row's link is the soundtrack's
    own app, which IGDB does not know. -> {how: count} for the rows found."""
    rows = [r for r in releases if not r.get("retired") and (r.get("medium") or "game") == "game"
            and "themes" not in r and (recent_since is None or _first_seen(r) >= recent_since)]
    by_slug, by_app, by_name = {}, {}, []
    for r in rows:
        urls = [s.get("url") or "" for s in r.get("sources") or []]
        slug = next((m.group(1) for u in urls for m in [IGDB_GAME.search(u)] if m), None)
        app = next((m.group(1) for u in urls for m in [STEAM_APP.search(u)] if m), None)
        if slug:
            by_slug.setdefault(slug, []).append(r)
        elif app:
            by_app.setdefault(app, []).append(r)
        elif r.get("game"):
            by_name.append(r)
    found = {"IGDB link": 0, "Steam id": 0, "name": 0}
    filled = 0

    for part in _chunks(sorted(by_slug)):
        for g in query("games", f"fields {GAME_FIELDS}; where slug = ({_quoted(part)}); limit 500;"):
            for r in by_slug.get(g.get("slug"), []):
                if "themes" not in r:
                    filled += _apply(r, g)
                    found["IGDB link"] += 1

    # Steam: the soundtrack's app names its game's app, which IGDB knows by uid
    parents, by_game = {}, {}
    for app in sorted(by_app):
        parent = steam_parent(app) if steam_parent else None
        parents[app] = parent
        if parent:
            by_game.setdefault(str(parent[0]), []).extend(by_app[app])
    for part in _chunks(sorted(by_game)):
        body = (f"fields *, game.name, game.slug, game.first_release_date, game.genres.name, game.themes.name; "
                f"where uid = ({_quoted(part)}); limit 500;")
        for e in query("external_games", body):
            steam = "steampowered" in (e.get("url") or "") or e.get("external_game_source") == 1 or e.get("category") == 1
            g = e.get("game")
            if not steam or not isinstance(g, dict):
                continue  # the same uid can belong to another store
            for r in by_game.get(str(e.get("uid")), []):
                if "themes" not in r:
                    filled += _apply(r, g)
                    found["Steam id"] += 1
    # a Steam game IGDB does not link, and rows with no link at all: by name
    for app, rows_ in sorted(by_app.items()):
        parent_name = (parents.get(app) or (None, None))[1]
        for r in rows_:
            name = parent_name or r.get("game")
            g = _by_name(query, r, name) if "themes" not in r and name else None
            if g:
                filled += _apply(r, g)
                found["name"] += 1
    for r in by_name:
        g = _by_name(query, r, r["game"])
        if g:
            filled += _apply(r, g)
            found["name"] += 1

    total = sum(found.values())
    log(f"game genres: {len(rows)} rows looked up, {total} found "
        f"({found['IGDB link']} by IGDB link, {found['Steam id']} by Steam id, {found['name']} by name), "
        f"genres filled on {filled}, {len(rows) - total} not found")
    return found


def steam_parent(app, pause=1.6):
    """(game app id, game name) for a Steam soundtrack app, from the store
    API's fullgame field, or None. Paced for Steam's ~200 calls per 5 minutes."""
    for attempt in (1, 2, 3):
        time.sleep(pause)
        try:
            resp = collect.requests.get("https://store.steampowered.com/api/appdetails",
                                        params={"appids": app}, timeout=30)
        except Exception:
            continue
        if resp.status_code == 429:
            time.sleep(30 * attempt)  # rate limited: back off hard
            continue
        if not resp.ok:
            return None
        full = (((resp.json() or {}).get(str(app)) or {}).get("data") or {}).get("fullgame") or {}
        return (str(full["appid"]), full.get("name") or "") if full.get("appid") else None
    return None


def igdb_query():
    cid, tok = collect.igdb_auth()

    def query(endpoint, body):
        for attempt in (1, 2, 3):
            time.sleep(0.3)  # IGDB allows four requests a second
            resp = collect.requests.post(f"https://api.igdb.com/v4/{endpoint}", data=body.encode(), timeout=30,
                                         headers={"Client-ID": cid, "Authorization": f"Bearer {tok}"})
            if resp.status_code == 429 and attempt < 3:
                time.sleep(2 * attempt)
                continue
            resp.raise_for_status()
            return resp.json()
    return query


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--anime", action="store_true")
    ap.add_argument("--games", action="store_true")
    ap.add_argument("--recent", action="store_true", help=f"games first seen in the last {RECENT_DAYS} days only")
    args = ap.parse_args(argv)
    data = collect.load_data(collect.DATA_PATH)
    before = json.dumps(data["releases"], sort_keys=True)
    if args.anime:
        anime_fill(data["releases"], tmdb_details)
    if args.games:
        since = None
        if args.recent:
            since = (datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            games_fill(data["releases"], igdb_query(), recent_since=since, steam_parent=steam_parent)
        except RuntimeError as e:
            print(f"::warning::game genres skipped: {e}")  # no Twitch credentials: the run carries on
    if json.dumps(data["releases"], sort_keys=True) != before:
        collect.DATA_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
