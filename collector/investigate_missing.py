"""Matcher probe (MATCHER-FIX-SPEC Phase 1 verification). Read-only:
prints findings to the Action log, writes nothing, fixes nothing.

For every title it runs the production screen matcher exactly as the
collector does (both searches, composer aliases, season years), reports
each YouTube Music candidate with the rule that accepted it or the first
rule that turned it away, then resolves all titles as one batch with
only game-owned albums reserved, which is how the Phase 2 re-walk will
hand albums out. The title list is the missing-titles investigation set
plus its Lost World counterpart and the 40-title discovery simulation set.

Run by .github/workflows/investigate.yml with TMDB_API_KEY set.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect

FILMS = [
    ("Jurassic Park", 1993), ("The Lost World: Jurassic Park", 1997), ("Back to the Future", 1985),
    ("Back to the Future Part II", 1989), ("Back to the Future Part III", 1990),
    ("Star Wars", 1977), ("The Empire Strikes Back", 1980), ("Return of the Jedi", 1983),
    ("Star Wars: Episode I - The Phantom Menace", 1999),
    ("Star Wars: Episode II - Attack of the Clones", 2002),
    ("Star Wars: Episode III - Revenge of the Sith", 2005),
    ("Star Wars: The Force Awakens", 2015), ("Star Wars: The Last Jedi", 2017),
    ("Star Wars: The Rise of Skywalker", 2019), ("Rogue One: A Star Wars Story", 2016),
    ("Solo: A Star Wars Story", 2018),
    ("Ip Man", 2008), ("Ip Man 2", 2010), ("Ip Man 3", 2015), ("Ip Man 4: The Finale", 2019),
    # discovery simulation set
    ("Jaws", 1975), ("Blade Runner", 1982), ("The Lion King", 1994), ("Pulp Fiction", 1994),
    ("Titanic", 1997), ("The Matrix", 1999), ("Gladiator", 2000),
    ("The Lord of the Rings: The Fellowship of the Ring", 2001), ("Inception", 2010),
    ("The Social Network", 2010), ("Interstellar", 2014), ("Mad Max: Fury Road", 2015),
    ("La La Land", 2016), ("Blade Runner 2049", 2017), ("Dune", 2021), ("The Batman", 2022),
    ("Oppenheimer", 2023), ("Challengers", 2024), ("Dune: Part Two", 2024),
]
SHOWS = [
    ("Castlevania", 2017), ("Castlevania: Nocturne", 2023), ("Infinity Train", 2019),
    ("Scavengers Reign", 2023), ("Common Side Effects", 2025),
    # discovery simulation set
    ("Twin Peaks", 1990), ("The X-Files", 1993), ("Buffy the Vampire Slayer", 1997),
    ("The Sopranos", 1999), ("Lost", 2004), ("Battlestar Galactica", 2004), ("Doctor Who", 2005),
    ("Breaking Bad", 2008), ("Sherlock", 2010), ("Game of Thrones", 2011),
    ("Stranger Things", 2016), ("Westworld", 2016), ("The Crown", 2016), ("Dark", 2017),
    ("Succession", 2018), ("The Mandalorian", 2019), ("Chernobyl", 2019), ("The Witcher", 2019),
    ("Arcane", 2021), ("The Last of Us", 2023),
]

ROOT = collect.ROOT
ROWS = json.loads((ROOT / "data" / "releases.json").read_text(encoding="utf-8"))["releases"]


def emit(tag, obj):
    print(f"{tag} " + json.dumps(obj, ensure_ascii=False), flush=True)


def tmdb_id_of(row):
    for s in row.get("sources", []):
        m = re.search(r"themoviedb\.org/(movie|tv)/(\d+)", s.get("url", ""))
        if m:
            return m.group(2)
    return None


def build_info(kind, name, year):
    """The same info the collector builds from a discover bundle."""
    if kind == "movie":
        found = collect._tmdb_get("search/movie", query=name, year=year).get("results", [])
        date_key = "release_date"
    else:
        found = collect._tmdb_get("search/tv", query=name, first_air_date_year=year).get("results", [])
        date_key = "first_air_date"
    entry = next((x for x in found if (x.get(date_key) or "")[:4] == str(year)),
                 found[0] if found else None)
    if not entry:
        return None, None
    tid = str(entry["id"])
    names, aliases = collect.tmdb_credits(kind, entry["id"])
    data = {"composers": {tid: names}, "aliases": {tid: aliases}}
    if kind == "movie":
        return collect.film_info(entry, data), entry
    data["seasons"] = {tid: collect.tmdb_seasons(entry["id"])}
    return collect.tv_info(entry, data), entry


def main():
    reserved = {r["ytmAlbumUrl"] for r in ROWS if r.get("medium", "game") == "game" and r.get("ytmAlbumUrl")}
    owners = {}
    for r in ROWS:
        if r.get("ytmAlbumUrl"):
            owners.setdefault(r["ytmAlbumUrl"], []).append(r["id"])
    reports, slots = [], {}
    for kind, titles in (("movie", FILMS), ("tv", SHOWS)):
        for name, year in titles:
            medium = "film" if kind == "movie" else "tv"
            rep = {"medium": medium, "asked": name}
            try:
                info, entry = build_info(kind, name, year)
                if not info:
                    rep["status"] = "not found on TMDb"
                    reports.append(rep)
                    continue
                results = collect.screen_search(collect.ytm_resolve, info)
                judged = collect.screen_classify(results, info, album_fn=collect.ytm_album)
                accepted = [c for c in judged if c["accepted"]]
                slots.update(collect.screen_slots(info, accepted))
                rep.update({
                    "tmdb_id": info["id"], "tmdb_title": info["name"], "original_title": info["original"],
                    "date": info["date"], "years": info["years"], "vote_count": entry.get("vote_count"),
                    "composers": info["composers"], "aliases": info["aliases"],
                    "queries": [collect._query(info["name"])] + (
                        [collect._query(info["original"])] if info["original"]
                        and collect._screen_base(info["original"]) != collect._screen_base(info["name"]) else []),
                    "rows_now": [{"id": r["id"], "album": r.get("albumTitle")} for r in ROWS
                                 if r.get("medium") == medium and tmdb_id_of(r) == info["id"]],
                    "candidates": [{k: c.get(k) for k in ("title", "year", "artists", "verdict", "normalized",
                                                          "credited", "gap", "extra", "plays")}
                                   for c in judged],
                })
            except Exception as exc:
                rep["error"] = repr(exc)
            reports.append(rep)
    winners, conflicts = collect.resolve_screen(slots, reserved=reserved)
    for rep in reports:
        if "tmdb_id" not in rep:
            emit("MATCHER-REPORT", rep)
            continue
        keys = sorted((k for k in winners if k[0] == rep["medium"] and k[1] == rep["tmdb_id"]),
                      key=lambda k: (k[-1] is None, k[-1] or 0) if rep["medium"] == "tv" else 0)
        rep["winners"] = []
        for k in keys:
            w = winners[k]
            rep["winners"].append({
                "season": k[2] if rep["medium"] == "tv" else None, "title": w["title"],
                "rule": w["rule"], "class": w["klass"], "weak": w["weak"],
                "credited": w["credited"], "gap": w["gap"],
                "worn_now_by": [o for o in owners.get(w["url"], [])
                                if o not in {x["id"] for x in rep["rows_now"]}]})
        rep["reserved_hits"] = [c["title"] for k, cs in slots.items()
                                if k[0] == rep["medium"] and k[1] == rep["tmdb_id"]
                                for c in cs if c["url"] in reserved]
        emit("MATCHER-REPORT", rep)
    emit("CONFLICTS", [{"album": u, "winner": list(w), "loser": list(l)} for u, w, l in conflicts])
    print("probe complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
