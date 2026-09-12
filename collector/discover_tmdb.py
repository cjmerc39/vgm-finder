"""Phase B discovery probe, per FILM-TV-SPEC B1. Read-only: fetches TMDb
and prints findings to the Action log. Builds nothing, writes nothing.

Run by .github/workflows/discovery.yml with TMDB_API_KEY set. Accepts
either key TMDb hands out: the short v3 key (query param) or the long
v4 read token (bearer header).
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import date, timedelta

import requests

BASE = "https://api.themoviedb.org/3"
KEY = os.environ.get("TMDB_API_KEY", "")

FILMS = ["Star Wars", "Jaws", "Blade Runner", "The Lion King", "Pulp Fiction",
         "Titanic", "The Matrix", "Gladiator",
         "The Lord of the Rings: The Fellowship of the Ring", "Inception",
         "The Social Network", "Interstellar", "Mad Max: Fury Road", "La La Land",
         "Blade Runner 2049", "Dune", "The Batman", "Oppenheimer",
         "Challengers", "Dune: Part Two"]
FILM_YEARS = [1977, 1975, 1982, 1994, 1994, 1997, 1999, 2000, 2001, 2010,
              2010, 2014, 2015, 2016, 2017, 2021, 2022, 2023, 2024, 2024]
SHOWS = ["Twin Peaks", "The X-Files", "Buffy the Vampire Slayer", "The Sopranos",
         "Lost", "Battlestar Galactica", "Doctor Who", "Breaking Bad", "Sherlock",
         "Game of Thrones", "Stranger Things", "Westworld", "The Crown", "Dark",
         "Succession", "The Mandalorian", "Chernobyl", "The Witcher", "Arcane",
         "The Last of Us"]


def get(path, **params):
    time.sleep(0.15)
    headers = {}
    if KEY.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {KEY}"
    else:
        params["api_key"] = KEY
    resp = requests.get(f"{BASE}/{path}", params=params, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()


def section(title):
    print(f"\n===== {title} =====", flush=True)


def main():
    if not KEY:
        print("::error::TMDB_API_KEY not set")
        return 1
    today = date.today()

    section("volume: discover/movie by window and vote floor")
    for days in (14, 30):
        since = (today - timedelta(days=days)).isoformat()
        for floor in (5, 20, 50):
            d = get("discover/movie", **{"primary_release_date.gte": since,
                                         "primary_release_date.lte": today.isoformat(),
                                         "vote_count.gte": floor,
                                         "sort_by": "primary_release_date.desc"})
            print(f"movie window {days}d vote_count>={floor}: {d.get('total_results')} titles")

    section("volume: discover/tv by window and vote floor (first_air_date)")
    for days in (14, 30, 60):
        since = (today - timedelta(days=days)).isoformat()
        for floor in (1, 5, 20):
            d = get("discover/tv", **{"first_air_date.gte": since,
                                      "first_air_date.lte": today.isoformat(),
                                      "vote_count.gte": floor,
                                      "sort_by": "first_air_date.desc"})
            print(f"tv window {days}d vote_count>={floor}: {d.get('total_results')} titles")

    section("recent sample: what a 14d/20-vote movie daily would see")
    d = get("discover/movie", **{"primary_release_date.gte": (today - timedelta(days=14)).isoformat(),
                                 "primary_release_date.lte": today.isoformat(),
                                 "vote_count.gte": 20, "sort_by": "vote_count.desc"})
    for m in d.get("results", [])[:10]:
        print(f"  {m.get('primary_release_date') or m.get('release_date')} votes={m.get('vote_count'):>5} "
              f"lang={m.get('original_language')} {m.get('title')!r} orig={m.get('original_title')!r}")

    section("recent sample: what a 60d/5-vote tv daily would see")
    d = get("discover/tv", **{"first_air_date.gte": (today - timedelta(days=60)).isoformat(),
                              "first_air_date.lte": today.isoformat(),
                              "vote_count.gte": 5, "sort_by": "vote_count.desc"})
    for m in d.get("results", [])[:10]:
        print(f"  {m.get('first_air_date')} votes={m.get('vote_count'):>5} "
              f"lang={m.get('original_language')} {m.get('name')!r} orig={m.get('original_name')!r}")

    section("field inventory: one raw discover result each")
    d = get("discover/movie", **{"vote_count.gte": 1000, "sort_by": "vote_count.desc"})
    print("movie:", json.dumps(d["results"][0], ensure_ascii=False))
    d = get("discover/tv", **{"vote_count.gte": 500, "sort_by": "vote_count.desc"})
    print("tv:", json.dumps(d["results"][0], ensure_ascii=False))

    section("genre id maps")
    print("movie:", json.dumps(get("genre/movie/list").get("genres", []), ensure_ascii=False))
    print("tv:", json.dumps(get("genre/tv/list").get("genres", []), ensure_ascii=False))

    section("backfill sizing: total_results at candidate bars")
    for floor in (500, 1000, 2000, 5000):
        d = get("discover/movie", **{"vote_count.gte": floor})
        print(f"movies with vote_count>={floor}: {d.get('total_results')}")
    for floor in (100, 250, 500, 1000):
        d = get("discover/tv", **{"vote_count.gte": floor})
        print(f"tv with vote_count>={floor}: {d.get('total_results')}")

    section("film credits: is Original Music Composer reliable?")
    ok = 0
    for name, year in zip(FILMS, FILM_YEARS):
        s = get("search/movie", query=name, year=year)
        results = s.get("results", [])
        if not results:
            print(f"  {name!r}: NOT FOUND")
            continue
        mid = results[0]["id"]
        crew = get(f"movie/{mid}/credits").get("crew", [])
        comp = [c for c in crew if "composer" in (c.get("job") or "").lower()
                or (c.get("job") or "") == "Music" or "music" in (c.get("job") or "").lower()]
        omc = [c["name"] for c in comp if c.get("job") == "Original Music Composer"]
        if omc:
            ok += 1
        print(f"  {name!r}: OMC={omc or 'NONE'} other_music_jobs="
              f"{sorted({c.get('job') for c in comp if c.get('job') != 'Original Music Composer'})}")
    print(f"films with an Original Music Composer credit: {ok}/{len(FILMS)}")

    section("tv credits: series credits vs aggregate_credits")
    ok_plain = ok_agg = 0
    for name in SHOWS:
        s = get("search/tv", query=name)
        results = s.get("results", [])
        if not results:
            print(f"  {name!r}: NOT FOUND")
            continue
        tid = results[0]["id"]
        plain = [c["name"] for c in get(f"tv/{tid}/credits").get("crew", [])
                 if "composer" in (c.get("job") or "").lower()]
        agg = [c["name"] for c in get(f"tv/{tid}/aggregate_credits").get("crew", [])
               if any("composer" in (j.get("job") or "").lower() for j in c.get("jobs", []))]
        ok_plain += bool(plain)
        ok_agg += bool(agg)
        print(f"  {name!r}: credits={plain or 'NONE'} aggregate={agg or 'NONE'}")
    print(f"shows with composer via credits: {ok_plain}/{len(SHOWS)}; "
          f"via aggregate_credits: {ok_agg}/{len(SHOWS)}")

    print("\ndiscovery probe complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
