"""Composers for game rows that have none (1,646 of 2,638 in 2026-09).

Three sources, tried in order, each only for rows the one before left empty:
  album     the row's YT Music album: its credited artists (not Various
            Artists, not a known cover act)
  wikidata  the game's composer (P86) on Wikidata, found exactly by the IGDB
            id (P5794) in the row's IGDB link
  steam     the "Composer:" line on the row's Steam soundtrack page, else its
            "Artist:" line unless that only repeats the game's name
The row gains `composers` and `composersFrom` saying which source spoke. No
key is needed; every source is public. --recent limits it to rows first
seen in the last 30 days (the daily step).

  python collector/fill_composers.py            # every game row with no composer
  python collector/fill_composers.py --recent   # the daily step
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect

IGDB_GAME = re.compile(r"igdb\.com/games/([^/?#]+)")
STEAM_APP = re.compile(r"store\.steampowered\.com/app/(\d+)")
WIKIDATA = "https://query.wikidata.org/sparql"
AGENT = "Scorekeep-collector/1.0 (personal soundtrack tracker; github.com/cjmerc39/vgm-finder)"
RECENT_DAYS = 30
_STEAM_LINE = re.compile(r"(Composer|Artist):\s*</td>\s*<td[^>]*>(.*?)</td>", re.IGNORECASE | re.DOTALL)


def _first_seen(r):
    return min((s.get("seenAt") or "9999") for s in r.get("sources") or [{}])


def _names(text):
    """A credit line as names: split on commas, ampersands and "and"."""
    flat = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", text or "")))  # tags and &amp; first, then split
    out = []
    for part in re.split(r",|;|&|\band\b|/", flat):
        name = part.strip()
        if name and name not in out:
            out.append(name)
    return out


def credited(names, game=None):
    """Names that stand for a person or a sound team, not Various Artists, a
    known cover act, or the game's own name echoed back."""
    game_norm = collect.normalize_title(game or "")
    return [n for n in names if n and not n.lower().startswith(("various", "varios"))
            and n.lower() not in collect._COVERS_ARTISTS and collect.normalize_title(n) != game_norm]


# ---------------------------------------------------------------- sources
def album_artists(browse_id, album_fn=None):
    album = (album_fn or collect.ytm_album)(browse_id) or {}
    return collect.album_artists_of(album)


def wikidata_composers(slugs, post=None):
    """{IGDB slug: [composer names]} for the slugs Wikidata credits a composer on."""
    post = post or (lambda q: collect.requests.post(WIKIDATA, data={"query": q}, timeout=90,
                                                   headers={"User-Agent": AGENT,
                                                            "Accept": "application/sparql-results+json"}).json())
    out = {}
    for i in range(0, len(slugs), 50):
        values = " ".join('"' + s.replace('"', "") + '"' for s in slugs[i:i + 50])
        q = (f'SELECT ?slug ?name WHERE {{ VALUES ?slug {{ {values} }} ?game wdt:P5794 ?slug . '
             f'?game wdt:P86 ?c . ?c rdfs:label ?name . FILTER(lang(?name) = "en") }}')
        for b in (post(q).get("results") or {}).get("bindings") or []:
            names = out.setdefault(b["slug"]["value"], [])
            if b["name"]["value"] not in names:
                names.append(b["name"]["value"])
        time.sleep(1)  # Wikidata asks for patience
    return out


def steam_credits(app, get=None):
    """The names on a Steam soundtrack page's Composer line, else its Artist line."""
    get = get or (lambda url: collect.requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0",
                                                                             "Cookie": "birthtime=0; mature_content=1"}).text)
    html = get(f"https://store.steampowered.com/app/{app}/?l=english")
    lines = {k.lower(): v for k, v in _STEAM_LINE.findall(html or "")}
    return ("composer", _names(lines["composer"])) if lines.get("composer") else \
           ("artist", _names(lines.get("artist", "")))


# -------------------------------------------------------------------- fill
def fill(releases, recent_since=None, album_fn=None, post=None, get=None, pause=1.5, log=print):
    rows = [r for r in releases if not r.get("retired") and (r.get("medium") or "game") == "game"
            and not r.get("composers") and (recent_since is None or _first_seen(r) >= recent_since)]
    got = {"album": 0, "wikidata": 0, "steam": 0}

    def give(r, names, source):
        names = credited(names, r.get("game"))
        if names:
            r["composers"], r["composersFrom"] = names, source
            got[source] += 1

    for r in rows:
        url = r.get("ytmAlbumUrl") or ""
        if "/browse/" in url:
            try:
                give(r, album_artists(url.rsplit("/", 1)[-1], album_fn), "album")
            except Exception:
                pass
            time.sleep(pause / 5)
    slugs = {}
    for r in rows:
        if r.get("composers"):
            continue
        m = next((IGDB_GAME.search(s.get("url") or "") for s in r.get("sources") or []
                  if IGDB_GAME.search(s.get("url") or "")), None)
        if m:
            slugs.setdefault(m.group(1), []).append(r)
    if slugs:
        try:
            found = wikidata_composers(sorted(slugs), post)
        except Exception as e:
            found = {}
            log(f"::warning::wikidata skipped: {e}")
        for slug, names in found.items():
            for r in slugs.get(slug, []):
                give(r, names, "wikidata")
    for r in rows:
        if r.get("composers"):
            continue
        m = next((STEAM_APP.search(s.get("url") or "") for s in r.get("sources") or []
                  if STEAM_APP.search(s.get("url") or "")), None)
        if not m:
            continue
        try:
            _, names = steam_credits(m.group(1), get)
        except Exception:
            continue
        give(r, names, "steam")
        time.sleep(pause)
    total = sum(got.values())
    log(f"composers: {len(rows)} game rows had none, {total} filled "
        f"({got['album']} from the album, {got['wikidata']} from Wikidata, {got['steam']} from Steam), "
        f"{len(rows) - total} still without")
    return got


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--recent", action="store_true", help=f"rows first seen in the last {RECENT_DAYS} days only")
    args = ap.parse_args(argv)
    data = collect.load_data(collect.DATA_PATH)
    since = None
    if args.recent:
        since = (datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    got = fill(data["releases"], recent_since=since)
    if sum(got.values()):
        collect.DATA_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
