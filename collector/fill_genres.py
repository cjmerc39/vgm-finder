"""Genre fills the daily legs cannot make for rows that already exist.

--anime: TMDb files anime under Animation, and anime is Animation made in
Japanese. New film and TV rows get "Anime" as they arrive
(collect._tmdb_genres); this reads every existing film and TV row's full
TMDb details once (stored genres keep only three, so Animation can be cut)
and adds "Anime" where it belongs. Needs TMDB_API_KEY.

--games: IGDB's themes (Horror, Fantasy, Science fiction, Thriller...) say
how a game feels, where its genres say how it plays, and they line up with
film and TV genres. Every game row with no themes list is looked up on
IGDB: by the slug in its IGDB link, by the app id in its Steam link, or,
with neither, by exact name with the release year within one year. A found
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


def games_fill(releases, query, recent_since=None, log=print):
    """query(endpoint, body) -> IGDB results. -> {how: count} for the rows found."""
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

    for part in _chunks(sorted(by_app)):
        body = (f"fields *, game.name, game.slug, game.first_release_date, game.genres.name, game.themes.name; "
                f"where uid = ({_quoted(part)}); limit 500;")
        for e in query("external_games", body):
            steam = "steampowered" in (e.get("url") or "") or e.get("external_game_source") == 1 or e.get("category") == 1
            g = e.get("game")
            if not steam or not isinstance(g, dict):
                continue  # the same uid can belong to another store
            for r in by_app.get(str(e.get("uid")), []):
                if "themes" not in r:
                    filled += _apply(r, g)
                    found["Steam id"] += 1

    for r in by_name:
        want = collect.normalize_title(r["game"])
        year = int((r.get("date") or "0")[:4] or 0)
        name = r["game"].replace('"', '\\"')
        hits = query("games", f'search "{name}"; fields {GAME_FIELDS}; limit 10;')
        match = [g for g in hits if collect.normalize_title(g.get("name") or "") == want and g.get("first_release_date")
                 and abs(datetime.fromtimestamp(g["first_release_date"], tz=timezone.utc).year - year) <= 1]
        if len(match) == 1:  # two games of one name and year: left for a person
            filled += _apply(r, match[0])
            found["name"] += 1

    total = sum(found.values())
    log(f"game genres: {len(rows)} rows looked up, {total} found "
        f"({found['IGDB link']} by IGDB link, {found['Steam id']} by Steam id, {found['name']} by name), "
        f"genres filled on {filled}, {len(rows) - total} not found")
    return found


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
            games_fill(data["releases"], igdb_query(), recent_since=since)
        except RuntimeError as e:
            print(f"::warning::game genres skipped: {e}")  # no Twitch credentials: the run carries on
    if json.dumps(data["releases"], sort_keys=True) != before:
        collect.DATA_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
