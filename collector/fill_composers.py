"""Composers for rows that have none (1,646 of 2,638 game rows in 2026-09).

Three sources, tried in order, each only for rows the one before left empty:
  album     the row's YT Music album: its credited artists, or, when the
            album is credited to Various Artists, the artists credited on
            most of its tracks (up to four, each on two tracks or more)
  wikidata  the game's composer (P86) on Wikidata, found exactly by the IGDB
            id (P5794) in the row's IGDB link
  steam     the "Composer:" line on the row's Steam soundtrack page, else its
            "Artist:" line unless that only repeats the game's name; a line
            written as prose ("composed and orchestrated by X") gives the
            names after "by", and fragments, track numbers and role words are
            dropped, so a paragraph gives nothing rather than junk
A film or TV row usually has TMDb's credits; the few TMDb credits nobody
(Marvel's Luke Cage, Warrior) reach the album source the same way, while
Wikidata and Steam are keyed to a game's own links and pass them by.
The row gains `composers` and `composersFrom` saying which source spoke. No
key is needed; every source is public. --recent limits it to rows first
seen in the last 30 days (the daily step).

  python collector/fill_composers.py            # every row with no composer
  python collector/fill_composers.py --recent   # the daily step
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect

IGDB_GAME = re.compile(r"igdb\.com/games/([^/?#]+)")
STEAM_APP = re.compile(r"store\.steampowered\.com/app/(\d+)")
TMDB_TITLE = re.compile(r"themoviedb\.org/(movie|tv)/(\d+)")
WIKIDATA = "https://query.wikidata.org/sparql"
AGENT = "Scorekeep-collector/1.0 (personal soundtrack tracker; github.com/cjmerc39/vgm-finder)"
RECENT_DAYS = 30
_STEAM_LINE = re.compile(r"(Composer|Artist):\s*</td>\s*<td[^>]*>(.*?)</td>", re.IGNORECASE | re.DOTALL)
_ROLE_WORDS = re.compile(r"\b(compos\w*|orchestrat\w*|produc\w*|lyric\w*|arrang\w*|perform\w*|mix\w*|master\w*|"
                         r"tracks?|additional|music|sound\s*design|written|featuring|feat)\b", re.IGNORECASE)
_BY_NAME = re.compile(r"\bby\s+(?:by\s+)?([A-Z\u00C0-\u024F][\w'.\-\u00C0-\u024F]*(?:\s+[A-Z\u00C0-\u024F][\w'.\-\u00C0-\u024F]*){0,3})")
# publishers and labels that YT Music sometimes lists as an album's artist: never a composer
_LABELS = {"sega", "nintendo", "capcom", "square enix", "bandai namco", "konami", "ubisoft", "electronic arts",
           "ea games", "microsoft", "xbox", "playstation", "sony", "activision", "blizzard entertainment",
           "bethesda", "2k", "devolver digital", "annapurna interactive", "atlus", "sony music", "universal music"}


def _first_seen(r):
    return min((s.get("seenAt") or "9999") for s in r.get("sources") or [{}])


def _plausible(name):
    """A credit that reads as a name: short, no brackets or bare numbers, no role words."""
    return (1 < len(name) <= 40 and len(name.split()) <= 5 and not re.search(r"[\[\]():]", name)
            and not name.isdigit() and not _ROLE_WORDS.search(name))


def _names(text):
    """A credit line as names. A plain list is split on commas, ampersands
    and "and"; a line written as prose gives the names after "by"; anything
    that does not read as a name is dropped."""
    flat = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", text or ""))).strip()  # tags and &amp; first
    if re.search(r"\bby\b", flat, re.IGNORECASE):
        # names after "by", unless the role before it is lyrics, production or performance
        parts = [m.group(1) for m in _BY_NAME.finditer(flat)
                 if not re.search(r"(lyric|produc|perform|mix|master|vocal|sung)\w*\s*$", flat[:m.start()], re.IGNORECASE)]
    else:
        parts = re.split(r",|;|&|\band\b|/", flat)
    out = []
    for part in parts:
        name = re.sub(r"\s+(Tracks?|Lyrics|Produced|Additional|Music)$", "", part.strip())
        if _plausible(name) and name not in out:
            out.append(name)
    return out


def credited(names, game=None):
    """Names that stand for a person or a sound team, not Various Artists, a
    known cover act, or the game's own name echoed back."""
    game_norm = collect._numfold(collect.normalize_title(game or ""))
    return [n for n in names if n and not n.lower().startswith(("various", "varios"))
            and n.lower() not in collect._COVERS_ARTISTS and n.lower() not in _LABELS
            and collect._numfold(collect.normalize_title(n)) != game_norm]


# ---------------------------------------------------------------- sources
def album_artists(browse_id, album_fn=None, tracks_fallback=True):
    """The album's credited artists; for a Various Artists album, the artists
    on most of its tracks: up to four, each on two tracks or more (one, on an
    album of three tracks or fewer). A film or TV row asks without that
    fallback: a Various Artists album there is a song compilation, and its
    track credits are the performers, not the score's composer (Bo Diddley
    on The Wolf of Wall Street, Harvey Keitel on Reservoir Dogs)."""
    album = (album_fn or collect.ytm_album)(browse_id) or {}
    names = [a for a in collect.album_artists_of(album) if not a.lower().startswith(("various", "varios"))]
    if names or not tracks_fallback:
        return names
    tracks = album.get("tracks") or []
    tally = Counter(a["name"].strip() for t in tracks for a in t.get("artists") or []
                    if isinstance(a, dict) and (a.get("name") or "").strip()
                    and not a["name"].lower().startswith(("various", "varios")))
    need = 1 if len(tracks) <= 3 else 2
    out = []
    for n, c in tally.most_common(4):  # a shared credit ("A & B", "A/B/C") counts for each name in it
        if c >= need:
            out += [x for x in _names(n) if x not in out]
    return out


def _sparql(q):
    return collect.requests.post(WIKIDATA, data={"query": q}, timeout=90,
                                 headers={"User-Agent": AGENT,
                                          "Accept": "application/sparql-results+json"}).json()


def wikidata_composers(slugs, post=None):
    """{IGDB slug: [composer names]} for the slugs Wikidata credits a composer on."""
    post = post or _sparql
    out, failed = {}, 0
    for i in range(0, len(slugs), 25):
        part = slugs[i:i + 25]
        values = " ".join('"' + s.replace('"', "") + '"' for s in part)
        q = (f'SELECT ?slug ?name WHERE {{ VALUES ?slug {{ {values} }} ?game wdt:P5794 ?slug . '
             f'?game wdt:P86 ?c . ?c rdfs:label ?name . FILTER(lang(?name) = "en") }}')
        for attempt in (1, 2, 3):
            try:
                bindings = (post(q).get("results") or {}).get("bindings") or []
                break
            except Exception:
                bindings = None
                time.sleep(5 * attempt)  # a slow query: wait, then ask again
        if bindings is None:
            failed += len(part)  # this batch only; the rest carry on
            continue
        for b in bindings:
            names = out.setdefault(b["slug"]["value"], [])
            if b["name"]["value"] not in names:
                names.append(b["name"]["value"])
        time.sleep(1)  # Wikidata asks for patience
    if failed:
        print(f"::warning::wikidata: {failed} games not asked after three tries; the next run asks again")
    return out


def album_names(browse_id, album_fn=None):
    """Every name the album credits, at album level and on its tracks, folded
    for comparison. This is what confirms a composer Wikidata names really
    made this record."""
    album = (album_fn or collect.ytm_album)(browse_id) or {}
    names = list(collect.album_artists_of(album))
    for t in album.get("tracks") or []:
        names += [a["name"] for a in t.get("artists") or [] if isinstance(a, dict) and a.get("name")]
    return {collect.normalize_title(n) for n in names if n}


def on_album(name, folded):
    """A name the album credits, whole or inside a shared credit ("Adrian
    Younge & The Delfonics")."""
    n = collect.normalize_title(name)
    return bool(n) and any(n == f or n in f for f in folded)


def wikidata_screen_composers(ids, post=None):
    """{(medium, TMDb id): [composer names]} from Wikidata's composer (P86),
    found by the TMDb id the row's source link carries (P4947 for a film,
    P4983 for a series). This is the source for a title TMDb itself credits
    nobody: Marvel's Luke Cage, Warrior."""
    post = post or _sparql
    out = {}
    for medium, prop in (("film", "P4947"), ("tv", "P4983")):
        want = sorted({tid for m, tid in ids if m == medium})
        for i in range(0, len(want), 25):
            part = want[i:i + 25]
            values = " ".join('"' + t.replace('"', "") + '"' for t in part)
            q = (f'SELECT ?tid ?name WHERE {{ VALUES ?tid {{ {values} }} ?item wdt:{prop} ?tid . '
                 f'?item wdt:P86 ?c . ?c rdfs:label ?name . FILTER(lang(?name) = "en") }}')
            for attempt in (1, 2, 3):
                try:
                    bindings = (post(q).get("results") or {}).get("bindings") or []
                    break
                except Exception:
                    bindings = None
                    time.sleep(5 * attempt)
            if bindings is None:
                print(f"::warning::wikidata: {len(part)} {medium} titles not asked; the next run asks again")
                continue
            for b in bindings:
                names = out.setdefault((medium, b["tid"]["value"]), [])
                if b["name"]["value"] not in names:
                    names.append(b["name"]["value"])
            time.sleep(1)
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
    rows = [r for r in releases if not r.get("retired") and not r.get("composers")
            and (recent_since is None or _first_seen(r) >= recent_since)]
    got = {"album": 0, "wikidata": 0, "steam": 0}

    def give(r, names, source):
        names = credited(names, r.get("game"))
        if names:
            r["composers"], r["composersFrom"] = names, source
            got[source] += 1

    credits = {}
    for r in rows:
        url = r.get("ytmAlbumUrl") or ""
        if "/browse/" in url:
            screen = (r.get("medium") or "game") != "game"
            bid = url.rsplit("/", 1)[-1]
            try:
                give(r, album_artists(bid, album_fn, tracks_fallback=not screen), "album")
                if screen and not r.get("composers"):
                    credits[r["id"]] = album_names(bid, album_fn)
            except Exception:
                pass
            time.sleep(pause / 5)
    screen_ids = {}
    for r in rows:
        if r.get("composers") or (r.get("medium") or "game") == "game":
            continue
        m = next((TMDB_TITLE.search(s.get("url") or "") for s in r.get("sources") or []
                  if TMDB_TITLE.search(s.get("url") or "")), None)
        if m:
            key = ("film" if m.group(1) == "movie" else "tv", m.group(2))
            screen_ids.setdefault(key, []).append(r)
    if screen_ids:
        try:
            found = wikidata_screen_composers(sorted(screen_ids), post)
        except Exception as e:
            found = {}
            log(f"::warning::wikidata (screen) skipped: {e}")
        for key, names in found.items():
            for r in screen_ids.get(key, []):
                # Wikidata names the work's composer, which on a film of
                # licensed songs is whoever wrote the hit (Howard Shore has
                # no note on The Wolf of Wall Street). The album has to
                # credit the name for it to be this record's composer.
                give(r, [n for n in names if on_album(n, credits.get(r["id"], set()))], "wikidata")
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
    log(f"composers: {len(rows)} rows had none, {total} filled "
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
