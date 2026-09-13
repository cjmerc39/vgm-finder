"""MATCHER-FIX-SPEC bars proposal: how many films and shows sit at each
candidate vote bar, and where the named test shows fall. Read-only: prints
PROBE lines to the log and touches no data. Dispatched through
probe-bars.yml."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import collect  # noqa: E402

FILM_FLOORS = (1000, 750, 500, 400, 300, 200)
TV_FLOORS = (500, 400, 300, 200, 150, 100, 50)
NAMED = ("Infinity Train", "Scavengers Reign", "Common Side Effects")


def emit(kind, **data):
    print("PROBE " + json.dumps(dict(kind=kind, **data), ensure_ascii=False))


def main():
    for kind, floors in (("movie", FILM_FLOORS), ("tv", TV_FLOORS)):
        for floor in floors:
            d = collect._tmdb_get(f"discover/{kind}", page=1, **{"vote_count.gte": floor, "sort_by": "vote_count.desc"})
            emit("floor", kind=kind, votes_floor=floor, total_results=d.get("total_results"))
    for name in NAMED:
        d = collect._tmdb_get("search/tv", query=name)
        for x in (d.get("results") or [])[:3]:
            emit("named", query=name, id=x.get("id"), name=x.get("name"), first_air_date=x.get("first_air_date"),
                 vote_count=x.get("vote_count"))


if __name__ == "__main__":
    main()
