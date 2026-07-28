"""vgm-finder collector: folds curated VGM release feeds into data/releases.json.

Deterministic, append-only. Run from anywhere: python collector/collect.py
IGDB needs TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET in the environment; without
them that one source warns and the rest still run.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from html import unescape
from pathlib import Path
from urllib.parse import quote_plus

import feedparser
import requests

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "data" / "releases.json"
USER_AGENT = "vgm-finder collector (+https://github.com/cjmerc39/vgm-finder)"
FUZZY_THRESHOLD = 0.92
IGDB_URL = "igdb:recent-games"
IGDB_WINDOW_DAYS = 14
IGDB_HYPES_MIN = 5
IGDB_LIMIT = 25
RESOLVE_WINDOW_DAYS = 60
RESOLVE_CAP = 40


def fetch_feed(url):
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    return resp.content  # bytes: feedparser sniffs the declared encoding itself


def igdb_fetch():
    cid = os.environ.get("TWITCH_CLIENT_ID")
    secret = os.environ.get("TWITCH_CLIENT_SECRET")
    if not cid or not secret:
        raise RuntimeError("TWITCH_CLIENT_ID / TWITCH_CLIENT_SECRET not set")
    tok = requests.post("https://id.twitch.tv/oauth2/token", timeout=30, params={
        "client_id": cid, "client_secret": secret,
        "grant_type": "client_credentials"}).json()["access_token"]
    now = int(time.time())
    start = now - IGDB_WINDOW_DAYS * 86400
    # game_type replaced the old (now dead) category field; 0/4/8/9 = main/expansion/remake/remaster
    query = (f"fields name, slug, first_release_date, hypes, game_type; "
             f"where first_release_date >= {start} & first_release_date <= {now} "
             f"& game_type = (0,4,8,9) & hypes >= {IGDB_HYPES_MIN}; "
             f"sort hypes desc; limit {IGDB_LIMIT};")
    resp = requests.post("https://api.igdb.com/v4/games", data=query.encode(), timeout=30,
                         headers={"Client-ID": cid, "Authorization": f"Bearer {tok}"})
    resp.raise_for_status()
    return resp.content


def fetch_any(url):
    return igdb_fetch() if url == IGDB_URL else fetch_feed(url)


_YT = None


def ytm_resolve(query):
    global _YT
    if _YT is None:
        from ytmusicapi import YTMusic  # lazy: only the resolver path needs it
        _YT = YTMusic()
    return _YT.search(query, filter="albums", limit=5)


def entry_categories(entry):
    return {t.get("term", "") for t in entry.get("tags", [])}


def entry_date(entry):
    for key in ("published_parsed", "updated_parsed"):
        parsed = entry.get(key)
        if parsed:
            return datetime(*parsed[:6], tzinfo=timezone.utc).strftime("%Y-%m-%d")
    return None


def _item(entry):
    title = re.sub(r"\s+", " ", entry.get("title", "")).strip()
    return {"title": title, "url": entry.get("link"), "date": entry_date(entry)}


def _feed(raw, keep):
    feed = feedparser.parse(raw)
    if not feed.entries:
        raise RuntimeError("feed parsed to zero entries")
    return [_item(e) for e in feed.entries if entry_categories(e) & keep]


def parse_vgmo(raw, resolve=None):
    return _feed(raw, {"News", "Album Reviews"})


def parse_nowplaying(raw, resolve=None):
    return _feed(raw, {"OST", "Vinyl"})


def parse_blipblop(raw, resolve=None):
    return _feed(raw, {"Confirmed Release"})


# Steam search rows: href sits before class in the <a>, so anchor on the pair
_STEAM_ROW = re.compile(
    r'href="(https://store\.steampowered\.com/app/[^"]+)"[^>]*class="search_result_row'
    r'[\s\S]*?<span class="title">([\s\S]*?)</span>'
    r'[\s\S]*?search_released[^>]*>\s*([^<]*)')
_MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def _steam_date(text):
    m = re.match(r"([A-Z][a-z]{2}) (\d{1,2}), (\d{4})$", text.strip())
    if not m or m.group(1) not in _MONTHS:
        return None
    return f"{m.group(3)}-{_MONTHS[m.group(1)]:02d}-{int(m.group(2)):02d}"


def parse_steam(raw, resolve=None):
    data = json.loads(raw)
    blob = data.get("results_html") or ""
    if not data.get("success") or not blob:
        raise RuntimeError("steam search returned no results_html")
    items = []
    for m in _STEAM_ROW.finditer(blob):
        date = _steam_date(m.group(3))
        if not date:
            continue  # "Coming soon" / quarter placeholders: not a release yet
        title = re.sub(r"\s+", " ", unescape(m.group(2))).strip()
        items.append({"title": title, "url": m.group(1).split("?")[0], "date": date})
    if not items:
        raise RuntimeError("steam rows parsed to zero items")
    return items


def _query(title):
    return title if "soundtrack" in title.lower() else f"{title} soundtrack"


_SOUNDTRACKY = re.compile(r"\b(soundtrack|ost|score|original sound)\b", re.IGNORECASE)


def _match_album(results, want_norm):
    """Strict: the album title must normalize to exactly the wanted name, must
    say it's a soundtrack, and must have a credited artist besides the game.
    Rejects fan albums, near-names (Combat vs Campaign Evolved), and
    same-name band albums (ZeroSpace the game vs Zerøspace the album)."""
    for r in results or []:
        if r.get("resultType") != "album" or not r.get("browseId"):
            continue
        if normalize_title(r.get("title", "")) != want_norm:
            continue
        if not _SOUNDTRACKY.search(r.get("title", "")):
            continue
        composers = [a["name"] for a in r.get("artists", [])
                     if a.get("name") and a["name"].lower() != "various artists"
                     and normalize_title(a["name"]) != want_norm]
        if not composers:
            continue  # only credit was the game/band name itself: too ambiguous
        return {"title": r["title"], "composers": composers,
                "url": "https://music.youtube.com/browse/" + r["browseId"]}
    return None


def parse_igdb(raw, resolve):
    games = json.loads(raw)
    if not isinstance(games, list):
        raise RuntimeError("igdb returned non-list")
    items, errors = [], 0
    for g in games:
        name = (g.get("name") or "").strip()
        stamp = g.get("first_release_date")
        if not name or not stamp:
            continue
        try:
            hit = _match_album(resolve(_query(name)), normalize_title(name))
        except Exception:
            errors += 1
            continue
        if not hit:
            continue  # released game, but no confidently-matching album on YTM
        items.append({
            "title": hit["title"], "game": name, "composers": hit["composers"],
            "url": f"https://www.igdb.com/games/{g.get('slug') or g.get('id')}",
            "date": datetime.fromtimestamp(stamp, tz=timezone.utc).strftime("%Y-%m-%d"),
            "ytmAlbumUrl": hit["url"]})
    if errors and not items:
        raise RuntimeError(f"all {errors} album lookups failed")
    return items


SOURCES = [
    {"name": "nowplaying", "type": "editorial",
     "url": "https://nowplaying.cool/rss/", "parse": parse_nowplaying},
    {"name": "blipblop", "type": "editorial",
     "url": "https://blipblop.net/feed/", "parse": parse_blipblop},
    {"name": "vgmo", "type": "editorial",
     "url": "https://www.vgmonline.net/feed/", "parse": parse_vgmo},
    {"name": "steam", "type": "catalog",
     "url": "https://store.steampowered.com/search/results/"
            "?query&start=0&count=25&category1=990&sort_by=Released_DESC&infinite=1&l=english&cc=US",
     "parse": parse_steam},
    {"name": "igdb", "type": "catalog", "url": IGDB_URL, "parse": parse_igdb},
]

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
# longest first so "original soundtrack" goes before "soundtrack" etc.
_SUFFIXES = (
    "original game soundtrack",
    "original sound track",
    "original soundtrack",
    "official soundtrack",
    "original score",
    "soundtrack",
    "ost",
)


def normalize_title(title):
    t = _PUNCT.sub(" ", title.lower())
    t = re.sub(r"\s+", " ", t).strip()
    base = t
    stripped = True
    while stripped:
        stripped = False
        for suffix in _SUFFIXES:
            if t.endswith(" " + suffix):
                t = t[: -len(suffix)].strip()
                stripped = True
    return t or base  # a title that IS just "OST" shouldn't normalize to nothing


def slugify(title):
    return "-".join(normalize_title(title).split()) or "untitled"


def ytm_search_url(title, game):
    q = " ".join(p for p in (title, game, "soundtrack") if p)
    return "https://music.youtube.com/search?q=" + quote_plus(re.sub(r"\s+", " ", q).strip())


def _fuzzy_find(norm, releases, norms):
    best, best_ratio = None, 0.0
    for r in releases:
        m = SequenceMatcher(None, norm, norms[id(r)])
        if m.real_quick_ratio() < FUZZY_THRESHOLD or m.quick_ratio() < FUZZY_THRESHOLD:
            continue
        ratio = m.ratio()
        if ratio > best_ratio:
            best, best_ratio = r, ratio
    return best if best_ratio >= FUZZY_THRESHOLD else None


def merge(releases, items, source, seen_at):
    """Fold one source's items in. Append-only: existing entries only ever gain
    a source, an earlier date, or a fill for a still-null enrichment field;
    id and title never change."""
    by_id = {r["id"]: r for r in releases}
    norms = {id(r): normalize_title(r["title"]) for r in releases}
    added = merged = 0
    for it in items:
        if not it["title"] or not it["url"]:
            continue
        slug = slugify(it["title"])
        target = by_id.get(slug) or _fuzzy_find(normalize_title(it["title"]), releases, norms)
        src = {"name": source["name"], "type": source["type"],
               "url": it["url"], "seenAt": seen_at}
        if target is not None:
            if not any(s["url"] == it["url"] for s in target["sources"]):
                target["sources"].append(src)
                merged += 1
            if it["date"] and (not target["date"] or it["date"] < target["date"]):
                target["date"] = it["date"]
            if not target.get("game") and it.get("game"):
                target["game"] = it["game"]
            if not target.get("composers") and it.get("composers"):
                target["composers"] = list(it["composers"])
            if not target.get("ytmAlbumUrl") and it.get("ytmAlbumUrl"):
                target["ytmAlbumUrl"] = it["ytmAlbumUrl"]
        else:
            entry = {"id": slug, "title": it["title"], "game": it.get("game"),
                     "composers": list(it.get("composers") or []),
                     "date": it["date"], "sources": [src],
                     "ytmSearchUrl": ytm_search_url(it["title"], it.get("game")),
                     "ytmAlbumUrl": it.get("ytmAlbumUrl"), "art": None, "notable": True}
            releases.append(entry)
            by_id[slug] = entry
            norms[id(entry)] = normalize_title(entry["title"])
            added += 1
    return added, merged


def resolve_albums(releases, resolve, now, cap=RESOLVE_CAP):
    """Fill ytmAlbumUrl for recent rows that lack one, with the same strict
    matcher. Bounded per run; unresolved rows retry until they age out."""
    cutoff = (now - timedelta(days=RESOLVE_WINDOW_DAYS)).strftime("%Y-%m-%d")
    looked = filled = 0
    for r in releases:
        if r.get("ytmAlbumUrl") or not r.get("date") or r["date"] < cutoff:
            continue
        if looked >= cap:
            break
        looked += 1
        try:
            hit = _match_album(resolve(_query(r["title"])), normalize_title(r["title"]))
        except Exception:
            continue
        if not hit:
            continue
        r["ytmAlbumUrl"] = hit["url"]
        if not r.get("composers") and hit["composers"]:
            r["composers"] = hit["composers"]
        filled += 1
    return looked, filled


def load_data(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("releases"), list):
            return data
    except (OSError, ValueError):
        pass
    return {"updatedAt": None, "releases": []}


def run(fetch_fn=fetch_any, resolve_fn=ytm_resolve, data_path=DATA_PATH, now=None):
    now = now or datetime.now(timezone.utc)
    seen_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    data = load_data(data_path)
    releases = data["releases"]
    before = json.dumps(releases, sort_keys=True, ensure_ascii=False)

    ok = 0
    for source in SOURCES:
        try:
            items = source["parse"](fetch_fn(source["url"]), resolve_fn)
            added, merged = merge(releases, items, source, seen_at)
            print(f"{source['name']}: {len(items)} items -> {added} new, {merged} merged")
            ok += 1
        except Exception as exc:  # one bad source must not kill the others
            print(f"::warning::{source['name']} failed: {exc}")
    if ok == 0:
        print("::error::every source failed")
        return 1

    looked, filled = resolve_albums(releases, resolve_fn, now)
    print(f"album resolver: {looked} lookups, {filled} filled")

    if json.dumps(releases, sort_keys=True, ensure_ascii=False) != before:
        data["updatedAt"] = seen_at
        path = Path(data_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"wrote {path.as_posix()}: {len(releases)} releases")
    else:
        print("no changes")  # leaves the file untouched so the Action commits nothing
    return 0


if __name__ == "__main__":
    sys.exit(run())
