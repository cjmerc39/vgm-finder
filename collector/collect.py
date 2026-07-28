"""vgm-finder collector: folds curated VGM release feeds into data/releases.json.

Deterministic, append-only. Run from anywhere: python collector/collect.py
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import quote_plus

import feedparser
import requests

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "data" / "releases.json"
USER_AGENT = "vgm-finder collector (+https://github.com/cjmerc39/vgm-finder)"
FUZZY_THRESHOLD = 0.92
REDDIT_TOP_N = 10


def fetch_feed(url):
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    return resp.content  # bytes: feedparser sniffs the declared encoding itself


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


def parse_vgmo(feed):
    keep = {"News", "Album Reviews"}
    return [_item(e) for e in feed.entries if entry_categories(e) & keep]


def parse_nowplaying(feed):
    keep = {"OST", "Vinyl"}
    return [_item(e) for e in feed.entries if entry_categories(e) & keep]


def parse_blipblop(feed):
    keep = {"Confirmed Release"}
    return [_item(e) for e in feed.entries if entry_categories(e) & keep]


def parse_gamemusic(feed):
    return [_item(e) for e in feed.entries[:REDDIT_TOP_N]]


SOURCES = [
    {"name": "nowplaying", "type": "editorial",
     "url": "https://nowplaying.cool/rss/", "parse": parse_nowplaying},
    {"name": "blipblop", "type": "editorial",
     "url": "https://blipblop.net/feed/", "parse": parse_blipblop},
    {"name": "vgmo", "type": "editorial",
     "url": "https://www.vgmonline.net/feed/", "parse": parse_vgmo},
    {"name": "r/gamemusic", "type": "community",
     "url": "https://www.reddit.com/r/gamemusic/top/.rss?t=week", "parse": parse_gamemusic},
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
    a source or an earlier date; id and title never change."""
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
        else:
            entry = {"id": slug, "title": it["title"], "game": None, "composers": [],
                     "date": it["date"], "sources": [src],
                     "ytmSearchUrl": ytm_search_url(it["title"], None),
                     "ytmAlbumUrl": None, "art": None, "notable": True}
            releases.append(entry)
            by_id[slug] = entry
            norms[id(entry)] = normalize_title(entry["title"])
            added += 1
    return added, merged


def load_data(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("releases"), list):
            return data
    except (OSError, ValueError):
        pass
    return {"updatedAt": None, "releases": []}


def run(fetch_fn=fetch_feed, data_path=DATA_PATH, now=None):
    now = now or datetime.now(timezone.utc)
    seen_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    data = load_data(data_path)
    releases = data["releases"]
    before = json.dumps(releases, sort_keys=True, ensure_ascii=False)

    ok = 0
    for source in SOURCES:
        try:
            feed = feedparser.parse(fetch_fn(source["url"]))
            if not feed.entries:
                raise RuntimeError("feed parsed to zero entries")
            items = source["parse"](feed)
            added, merged = merge(releases, items, source, seen_at)
            print(f"{source['name']}: {len(items)} items -> {added} new, {merged} merged")
            ok += 1
        except Exception as exc:  # one bad source must not kill the others
            print(f"::warning::{source['name']} failed: {exc}")
    if ok == 0:
        print("::error::every source failed")
        return 1

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
