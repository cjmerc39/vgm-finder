"""Missing-titles investigation. Read-only: prints findings to the Action
log, writes nothing, fixes nothing.

For each title it answers: did the backfill ever check it, and if so,
which matcher rule turned away each YouTube Music candidate. The trace
mirrors collect._screen_candidates rule for rule and proves the mirror
by comparing its accepted set against the real function on every title.

Also sizes the vote bands below the current bars, and sweeps every
discover page at the bars to find titles the walk never recorded.

Run by .github/workflows/investigate.yml with TMDB_API_KEY set.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backfill
import collect

FILMS = [
    ("Jurassic Park", 1993), ("Back to the Future", 1985),
    ("Back to the Future Part II", 1989), ("Back to the Future Part III", 1990),
    ("Star Wars", 1977), ("The Empire Strikes Back", 1980), ("Return of the Jedi", 1983),
    ("Star Wars: Episode I - The Phantom Menace", 1999),
    ("Star Wars: Episode II - Attack of the Clones", 2002),
    ("Star Wars: Episode III - Revenge of the Sith", 2005),
    ("Star Wars: The Force Awakens", 2015), ("Star Wars: The Last Jedi", 2017),
    ("Star Wars: The Rise of Skywalker", 2019), ("Rogue One: A Star Wars Story", 2016),
    ("Solo: A Star Wars Story", 2018),
    ("Ip Man", 2008), ("Ip Man 2", 2010), ("Ip Man 3", 2015), ("Ip Man 4: The Finale", 2019),
]
SHOWS = [
    ("Castlevania", 2017), ("Castlevania: Nocturne", 2023), ("Infinity Train", 2019),
    ("Scavengers Reign", 2023), ("Common Side Effects", 2025),
]

ROOT = collect.ROOT
STATE = json.loads((ROOT / "collector" / "backfill-state.json").read_text(encoding="utf-8"))
ROWS = json.loads((ROOT / "data" / "releases.json").read_text(encoding="utf-8"))["releases"]


def emit(tag, obj):
    print(f"{tag} " + json.dumps(obj, ensure_ascii=False), flush=True)


def tmdb_id_of(row):
    for s in row.get("sources", []):
        m = re.search(r"themoviedb\.org/(movie|tv)/(\d+)", s.get("url", ""))
        if m:
            return int(m.group(2))
    return None


def rows_for(kind_medium, tid):
    return [r for r in ROWS if r.get("medium") == kind_medium and tmdb_id_of(r) == tid]


def owner_of(url, tid):
    for r in ROWS:
        if r.get("ytmAlbumUrl") == url and tmdb_id_of(r) != tid:
            return r["id"]
    return None


def trace(r, name, year, composers):
    """One candidate through the screen gates, in the real order. Returns
    the first rule that stops it, plus diagnostics that do not change the
    verdict: whether the album name contains the TMDb title somewhere, and
    whether the credited composer is aboard."""
    want = collect._numfold(collect.normalize_title(name))
    comp = [collect.normalize_title(c) for c in composers or [] if c]
    title = r.get("title", "")
    artists = [a["name"] for a in r.get("artists", []) if a.get("name")]
    out = {"title": title, "year": r.get("year"), "artists": artists}
    overlap = any(c and any(c in collect.normalize_title(a) or collect.normalize_title(a) in c
                            for a in artists) for c in comp)
    out["composer_aboard"] = overlap
    if r.get("resultType") != "album" or not r.get("browseId"):
        out["verdict"] = "not an album result"
        return out
    m = collect._SCREEN_REJECT.search(title)
    if m:
        out["verdict"] = f"reject vocabulary '{m.group(0)}'"
        return out
    if not collect._SCREEN_WORDING.search(title):
        out["verdict"] = "no soundtrack wording in the album title"
        return out
    bad = [a for a in artists if a.lower() in collect._COVERS_ARTISTS
           or a.lower() in collect._SCREEN_TRIBUTE]
    if bad:
        out["verdict"] = f"tribute artist '{bad[0]}'"
        return out
    n2 = collect._numfold(collect.normalize_screen(title))
    out["normalized"], out["want"] = n2, want
    out["contains_title"] = (f" {want} " in f" {n2} ")
    prefix, tail = False, ""
    if n2 != want:
        if not n2.startswith(want + " "):
            out["verdict"] = "title gate"
            return out
        tail = n2[len(want):].strip()
        if re.match(r"^(part\s+)?\d", tail):
            out["verdict"] = f"sequel guard (tail '{tail}')"
            return out
        prefix = True
    yr = None
    try:
        yr = int(r.get("year"))
    except (TypeError, ValueError):
        pass
    near = yr is not None and year is not None and abs(yr - year) <= 2
    out["year_gap"] = abs(yr - year) if yr is not None else None
    if prefix and not overlap:
        out["verdict"] = f"subtitle drift without the composer (tail '{tail}')"
        return out
    if not overlap and not near:
        out["verdict"] = "no composer aboard and album year outside 2 years"
        return out
    out["verdict"] = "ACCEPTED" + (f" by subtitle drift (tail '{tail}')" if prefix else "")
    out["url"] = "https://music.youtube.com/browse/" + r["browseId"]
    return out


def investigate(kind, name, year):
    medium = "film" if kind == "movie" else "tv"
    if kind == "movie":
        found = collect._tmdb_get("search/movie", query=name, year=year).get("results", [])
        date_key, title_key = "release_date", "title"
    else:
        found = collect._tmdb_get("search/tv", query=name, first_air_date_year=year).get("results", [])
        date_key, title_key = "first_air_date", "name"
    pick = next((x for x in found if (x.get(date_key) or "")[:4] == str(year)), found[0] if found else None)
    rep = {"medium": medium, "asked": name}
    if not pick:
        rep["status"] = "not found on TMDb"
        emit("MISSING-REPORT", rep)
        return
    tid = pick["id"]
    tname = (pick.get(title_key) or "").strip()
    tdate = pick.get(date_key) or ""
    if kind == "movie":
        crew = collect._tmdb_get(f"movie/{tid}/credits").get("crew", [])
        composers = [c["name"] for c in crew if c.get("job") == "Original Music Composer"]
        bar, checked = backfill.FILM_BAR, set(STATE.get("tmdbFilmChecked", []))
    else:
        crew = collect._tmdb_get(f"tv/{tid}/aggregate_credits").get("crew", [])
        composers = [c["name"] for c in crew
                     if any("composer" in (j.get("job") or "").lower() for j in c.get("jobs", []))]
        bar, checked = backfill.TV_BAR, set(STATE.get("tmdbTvChecked", []))
    rep.update({"tmdb_id": tid, "tmdb_title": tname,
                "original_title": pick.get("original_title") or pick.get("original_name"),
                "date": tdate, "vote_count": pick.get("vote_count"), "bar": bar,
                "above_bar": (pick.get("vote_count") or 0) >= bar,
                "composers": composers, "checked": tid in checked,
                "rows_now": [{"id": r["id"], "album": r.get("albumTitle")} for r in rows_for(medium, tid)]})
    query = collect._query(tname)
    rep["ytm_query"] = query
    results = collect.ytm_resolve(query)  # the exact call and default limit the backfill used
    yr = int(tdate[:4]) if tdate[:4].isdigit() else None
    traced = [trace(r, tname, yr, composers) for r in results]
    rep["candidates"] = traced
    mine = sorted(t["title"] for t in traced if t["verdict"].startswith("ACCEPTED"))
    real = sorted(c["title"] for c in collect._screen_candidates(results, tname, yr, composers))
    rep["mirror_check"] = "ok" if mine == real else {"trace": mine, "real": real}
    if kind == "movie":
        hit = collect.match_film(results, tname, yr, composers)
        winners = [hit] if hit else []
    else:
        winners = collect.tv_season_albums(results, tname, yr, composers)
    rep["winners"] = [{"title": w["title"], "season": w.get("season"),
                       "claimed_by": owner_of(w["url"], tid)} for w in winners]
    emit("MISSING-REPORT", rep)


def band(kind, lo, hi):
    return collect._tmdb_get(f"discover/{kind}", **{"vote_count.gte": lo, "vote_count.lte": hi}) \
        .get("total_results")


def sweep(kind, floor, checked_key):
    """Every discover page at the bar today, against the checked set."""
    checked = set(STATE.get(checked_key, []))
    first = collect._tmdb_get(f"discover/{kind}", page=1,
                              **{"vote_count.gte": floor, "sort_by": "vote_count.desc"})
    pages = min(int(first.get("total_pages", 1)), 500)
    missing = []
    for page in range(1, pages + 1):
        d = first if page == 1 else collect._tmdb_get(
            f"discover/{kind}", page=page, **{"vote_count.gte": floor, "sort_by": "vote_count.desc"})
        for x in d.get("results", []):
            if x["id"] not in checked:
                medium = "film" if kind == "movie" else "tv"
                missing.append({"page": page, "id": x["id"],
                                "title": x.get("title") or x.get("name"),
                                "votes": x.get("vote_count"),
                                "has_row": bool(rows_for(medium, x["id"]))})
        time.sleep(0.05)
    emit("SWEEP", {"kind": kind, "bar": floor, "total_results": first.get("total_results"),
                   "pages": pages, "checked_set": len(checked), "never_recorded": len(missing),
                   "never_recorded_with_row": sum(1 for m in missing if m["has_row"]),
                   "sample": missing[:40]})


def main():
    for name, year in FILMS:
        try:
            investigate("movie", name, year)
        except Exception as exc:
            emit("MISSING-REPORT", {"medium": "film", "asked": name, "error": repr(exc)})
    for name, year in SHOWS:
        try:
            investigate("tv", name, year)
        except Exception as exc:
            emit("MISSING-REPORT", {"medium": "tv", "asked": name, "error": repr(exc)})
    emit("VOTE-BAND", {
        "films_300_999": band("movie", 300, 999),
        "films_300_499": band("movie", 300, 499),
        "films_500_999": band("movie", 500, 999),
        "shows_100_499": band("tv", 100, 499),
        "shows_100_249": band("tv", 100, 249),
        "shows_250_499": band("tv", 250, 499),
    })
    sweep("movie", backfill.FILM_BAR, "tmdbFilmChecked")
    sweep("tv", backfill.TV_BAR, "tmdbTvChecked")
    print("investigation complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
