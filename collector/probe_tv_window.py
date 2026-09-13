"""MATCHER-FIX-SPEC Phase 3, item 1: what TMDb supports for finding recent
seasons, before building anything. Read-only: prints PROBE lines to the log
and touches no data. Dispatched by hand through probe-tv-window.yml.

The daily TV leg asks discover/tv for first_air_date inside a 60-day window,
so a new season of an older show never appears. This compares that with
discover/tv's air_date window, then reads each extra show's details to tell
a season that premiered inside the window from a show that only aired
episodes of an older season inside it."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect  # noqa: E402

WINDOW_DAYS = collect.TMDB_TV_WINDOW_DAYS
PAGES = 10


def emit(kind, **data):
    print("PROBE " + json.dumps(dict(kind=kind, **data), ensure_ascii=False))


def discover(params, pages=PAGES):
    results, total = [], None
    for page in range(1, pages + 1):
        d = collect._tmdb_get("discover/tv", page=page, **params)
        total = d.get("total_results")
        results.extend(d.get("results") or [])
        if page >= int(d.get("total_pages") or 1):
            break
    return results, total


def main():
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%d")
    today = now.strftime("%Y-%m-%d")
    for floor in (collect.TMDB_TV_VOTES, 50, 200):
        base = {"vote_count.gte": floor, "sort_by": "vote_count.desc"}
        premiere, p_total = discover(dict(base, **{"first_air_date.gte": since, "first_air_date.lte": today}))
        aired, a_total = discover(dict(base, **{"air_date.gte": since, "air_date.lte": today}))
        p_ids = {x["id"] for x in premiere}
        extra = [x for x in aired if x["id"] not in p_ids]
        emit("window", votes_floor=floor, since=since, until=today,
             first_air_date_total=p_total, air_date_total=a_total,
             air_date_only_in_first_pages=len(extra), pages_read=PAGES)
        if floor != collect.TMDB_TV_VOTES:
            continue
        season_premiere, episodes_only, examples = 0, 0, []
        for x in extra[:60]:
            d = collect._tmdb_get(f"tv/{x['id']}")
            seasons = [s for s in d.get("seasons") or [] if s.get("season_number")]
            in_window = [s for s in seasons if s.get("air_date") and since <= s["air_date"] <= today]
            last_ep = (d.get("last_episode_to_air") or {}).get("air_date")
            if in_window:
                season_premiere += 1
                if len(examples) < 15:
                    examples.append({"name": d.get("name"), "first_air_date": d.get("first_air_date"),
                                     "season": in_window[-1]["season_number"], "season_air_date": in_window[-1]["air_date"],
                                     "votes": d.get("vote_count")})
            else:
                episodes_only += 1
                if episodes_only <= 5:
                    emit("episodes_only", name=d.get("name"), first_air_date=d.get("first_air_date"),
                         last_episode=last_ep, latest_season_air_date=max((s.get("air_date") or "" for s in seasons), default=None),
                         genres=[g.get("name") for g in d.get("genres") or []])
        emit("air_date_extra_split", read=min(60, len(extra)), season_premiered_in_window=season_premiere,
             episodes_only=episodes_only)
        for ex in examples:
            emit("older_show_new_season", **ex)
    for path in ("tv/on_the_air", "tv/airing_today"):
        d = collect._tmdb_get(path, page=1)
        emit("list_endpoint", path=path, total_results=d.get("total_results"),
             sample=[x.get("name") for x in (d.get("results") or [])[:5]])


if __name__ == "__main__":
    main()
