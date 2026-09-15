"""Mood tagging, driven with a fake model: the vocabulary is enforced,
malformed replies are retried once then skipped, the caps hold, a rerun
never retags, and a missing key skips the step without failing."""
import json

import moods

VOCAB = moods.load_vocab()
TERMS = [m for m, _ in VOCAB]


def reply(entries):
    return json.dumps({"tracks": [{"n": n, "moods": ms} for n, ms in entries]})


class FakeModel:
    """call(client, system, prompt) -> (text, in, out), scripted per album title."""
    def __init__(self, scripts):
        self.scripts = dict(scripts)   # album title substring -> list of replies, consumed in order
        self.calls = []

    def __call__(self, client, system, prompt):
        self.calls.append(prompt)
        for key, replies in self.scripts.items():
            if key in prompt:
                text = replies.pop(0) if len(replies) > 1 else replies[0]
                return text, 600, 40
        return reply([]), 600, 5


def _row(rid, title, n, **extra):
    r = {"id": rid, "title": title, "albumTitle": title, "game": title.replace(" Soundtrack", ""), "medium": "game",
         "date": "2026-09-01", "tracksN": n,
         "sources": [{"name": "igdb", "type": "catalog", "url": "https://x/" + rid, "seenAt": "2026-09-10T10:00:00Z"}]}
    r.update(extra)
    return r


def _setup(tmp_path, rows, tracks):
    tracks_dir = tmp_path / "tracks"
    tracks_dir.mkdir()
    for rid, tt in tracks.items():
        (tracks_dir / f"{rid}.json").write_text(json.dumps(tt), encoding="utf-8")
    data_path = tmp_path / "releases.json"
    data_path.write_text(json.dumps({"updatedAt": "x", "releases": rows}), encoding="utf-8")
    return data_path, tracks_dir, tmp_path / "moods-state.json"


# ---------------------------------------------------------------- vocabulary

def test_vocabulary_is_the_sixteen_confirmed_terms():
    assert TERMS == ["wonder", "transcendent", "nostalgic", "tender", "peaceful", "joyful", "powerful", "tense",
                     "sad", "heroic", "eerie", "driving", "playful", "mournful", "romantic", "mysterious"]
    assert all(g for _, g in VOCAB)
    system = moods.system_prompt(VOCAB)
    assert all(f"- {m}:" in system for m in TERMS) and "JSON only" in system


def test_parse_rejects_off_list_tags_and_bad_shapes():
    assert moods.parse_reply(reply([(1, ["tense", "driving"]), (2, [])]), 2, TERMS) == {1: ["tense", "driving"], 2: []}
    assert moods.parse_reply(reply([(1, ["Tense", " EERIE "])]), 1, TERMS) == {1: ["tense", "eerie"]}  # case and space fold
    assert moods.parse_reply(reply([(1, ["tense", "tense"])]), 1, TERMS) == {1: ["tense"]}  # dupes collapse
    assert moods.parse_reply(reply([(1, ["tense", "driving", "eerie", "sad"])]), 1, TERMS) == {1: ["tense", "driving", "eerie"]}
    assert moods.parse_reply(reply([(1, ["spooky"])]), 1, TERMS) is None       # free text
    assert moods.parse_reply(reply([(3, ["tense"])]), 2, TERMS) is None          # no such track
    assert moods.parse_reply(reply([(1, "tense")]), 1, TERMS) is None            # not a list
    assert moods.parse_reply("not json", 1, TERMS) is None
    assert moods.parse_reply(json.dumps({"tracks": "x"}), 1, TERMS) is None
    assert moods.parse_reply(json.dumps([{"n": 1, "moods": []}]), 1, TERMS) is None


def test_album_prompt_names_the_work_and_numbers_the_tracks():
    r = _row("hades", "Hades Soundtrack", 2, composers=["Darren Korb"], genres=["Role-playing (RPG)"])
    p = moods.album_prompt(r, [{"title": "No Escape"}, {"title": "The Painted World"}])
    assert "Work: Hades (video game, 2026)" in p and "Composers: Darren Korb" in p and "Genres: Role-playing (RPG)" in p
    assert p.endswith("Tracks:\n1. No Escape\n2. The Painted World")


# ----------------------------------------------------------------- tag_album

def test_tag_album_writes_track_moods_and_the_union_commonest_first():
    r = _row("hades", "Hades Soundtrack", 3)
    tracks = [{"title": "A"}, {"title": "B"}, {"title": "C"}]
    fake = FakeModel({"Hades": [reply([(1, ["driving", "tense"]), (2, ["tense"]), (3, [])])]})
    res = moods.tag_album(None, r, tracks, VOCAB, call=fake)
    assert res == {"ok": True, "in": 600, "out": 40, "tries": 1, "calls": 1}
    assert tracks[0]["moods"] == ["driving", "tense"] and tracks[1]["moods"] == ["tense"] and "moods" not in tracks[2]
    assert r["moods"] == ["tense", "driving"]  # tense on two tracks outranks driving on one


def test_tag_album_retries_a_bad_reply_once_then_gives_up():
    r = _row("hades", "Hades Soundtrack", 1)
    tracks = [{"title": "A"}]
    fake = FakeModel({"Hades": ["garbage", reply([(1, ["heroic"])])]})
    res = moods.tag_album(None, r, tracks, VOCAB, call=fake)
    assert res["ok"] and res["tries"] == 2 and res["in"] == 1200 and tracks[0]["moods"] == ["heroic"]
    r2, tracks2 = _row("x", "Twice Bad Soundtrack", 1), [{"title": "A"}]
    fake = FakeModel({"Twice Bad": [reply([(1, ["spooky"])]), "still garbage"]})
    res = moods.tag_album(None, r2, tracks2, VOCAB, call=fake)
    assert res == {"ok": False, "in": 1200, "out": 80, "tries": 2, "calls": 2}
    assert "moods" not in r2 and "moods" not in tracks2[0]  # untouched, picked up next run


def test_long_albums_go_in_even_chunks_with_the_albums_own_numbers():
    assert [(s, len(p)) for s, p in moods.chunks(list(range(657)))] == [(1, 94), (95, 94), (189, 94), (283, 94), (377, 94), (471, 94), (565, 93)]
    assert [(s, len(p)) for s, p in moods.chunks(list(range(100)))] == [(1, 100)]
    assert [(s, len(p)) for s, p in moods.chunks(list(range(101)))] == [(1, 51), (52, 50)]
    assert moods.chunks([]) == [(1, [])]
    r = _row("big", "Big Soundtrack", 3)
    p = moods.album_prompt(r, [{"title": "B"}, {"title": "C"}], start=2, total=3)
    assert "Tracks 2 to 3 of 3:\n2. B\n3. C" in p
    assert moods.parse_reply(reply([(2, ["tense"]), (3, [])]), range(2, 4), TERMS) == {2: ["tense"], 3: []}
    assert moods.parse_reply(reply([(1, ["tense"])]), range(2, 4), TERMS) is None  # a number outside the chunk


def test_a_chunked_album_is_tagged_whole_or_not_at_all(monkeypatch):
    monkeypatch.setattr(moods, "CHUNK_TRACKS", 2)
    r = _row("big", "Big Soundtrack", 5)
    tracks = [{"title": f"T{i}"} for i in range(1, 6)]
    seen = []
    def call(client, system, prompt):
        seen.append(next(line for line in prompt.splitlines() if line.startswith("Tracks ")))
        first = int(prompt.split("Tracks ")[1].split(" ")[0])
        return reply([(n, ["driving"] if n % 2 else []) for n in range(first, first + 2 if first < 5 else first + 1)]), 500, 30
    res = moods.tag_album(None, r, tracks, VOCAB, call=call)
    assert res == {"ok": True, "in": 1500, "out": 90, "tries": 1, "calls": 3}
    assert [t.get("moods") for t in tracks] == [["driving"], None, ["driving"], None, ["driving"]] and r["moods"] == ["driving"]
    assert seen == ["Tracks 1 to 2 of 5:", "Tracks 3 to 4 of 5:", "Tracks 5 to 5 of 5:"]
    # the second chunk fails twice: nothing is written, the album waits for another run
    r2, tracks2 = _row("big2", "Big Two Soundtrack", 5), [{"title": f"T{i}"} for i in range(1, 6)]
    def bad_middle(client, system, prompt):
        first = int(prompt.split("Tracks ")[1].split(" ")[0])
        if first == 3:
            return "garbage", 500, 5
        return reply([(n, ["sad"]) for n in range(first, min(first + 2, 6))]), 500, 30
    res = moods.tag_album(None, r2, tracks2, VOCAB, call=bad_middle)
    assert res["ok"] is False and res["calls"] == 3 and "moods" not in r2 and not any("moods" in t for t in tracks2)


def test_untagged_deals_the_mediums_in_turn_newest_first():
    rows = [_row("g1", "G1 Soundtrack", 1, date="2020-01-01"), _row("g2", "G2 Soundtrack", 1, date="2024-01-01"),
            _row("f1", "F1 Soundtrack", 1, medium="film", date="2023-01-01"), _row("f2", "F2 Soundtrack", 1, medium="film", date="2021-01-01"),
            _row("t1", "T1 Soundtrack", 1, medium="tv", date="2022-01-01")]
    import tempfile, pathlib
    with tempfile.TemporaryDirectory() as d:
        for r in rows:
            (pathlib.Path(d) / f"{r['id']}.json").write_text("[]", encoding="utf-8")
        assert [r["id"] for r in moods.untagged(rows, d)] == ["g2", "f1", "t1", "g1", "f2"]


def test_an_album_the_model_leaves_bare_still_counts_as_tagged():
    r = _row("bare", "Bare Soundtrack", 2)
    tracks = [{"title": "A"}, {"title": "B"}]
    fake = FakeModel({"Bare": [reply([(1, []), (2, [])])]})
    assert moods.tag_album(None, r, tracks, VOCAB, call=fake)["ok"]
    assert r["moods"] == [] and not any("moods" in t for t in tracks)


# ----------------------------------------------------------------------- run

def test_daily_run_tags_new_albums_only_under_the_cap_and_never_retags(tmp_path):
    rows = [_row("new-a", "New A Soundtrack", 1), _row("new-b", "New B Soundtrack", 1),
            _row("old", "Old Soundtrack", 1, date="2015-01-01",
                 sources=[{"name": "igdb", "type": "catalog", "url": "https://x/old", "seenAt": "2026-01-01T10:00:00Z"}]),
            _row("done", "Done Soundtrack", 1, moods=["tense"]),
            _row("bare", "Bare Soundtrack", 0)]
    tracks = {rid: [{"title": "T"}] for rid in ("new-a", "new-b", "old", "done")}
    data_path, tracks_dir, state_path = _setup(tmp_path, rows, tracks)
    fake = FakeModel({"New A": [reply([(1, ["joyful"])])], "New B": [reply([(1, ["sad"])])], "Old": [reply([(1, ["eerie"])])]})
    from datetime import datetime, timezone
    now = datetime(2026, 9, 14, tzinfo=timezone.utc)
    out = moods.run("daily", cap=1, data_path=data_path, tracks_dir=tracks_dir, state_path=state_path,
                    client=object(), vocab=VOCAB, now=now, log=lambda s: None, call=fake)
    assert out["tagged"] == 1 and out["remaining"] == 1 and len(fake.calls) == 1 and "New" in fake.calls[0]
    saved = {r["id"]: r for r in json.loads(data_path.read_text(encoding="utf-8"))["releases"]}
    tagged_new = [rid for rid in ("new-a", "new-b") if "moods" in saved[rid]]
    assert len(tagged_new) == 1 and "moods" not in saved["old"]  # the cap held; the old row is the backfill's
    assert json.loads((tracks_dir / f"{tagged_new[0]}.json").read_text(encoding="utf-8"))[0]["moods"] in (["joyful"], ["sad"])
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["tagged"] == 1 and state["inputTokens"] == 600 and state["runs"][0]["kind"] == "daily" and state["cost"] > 0
    out = moods.run("daily", cap=10, data_path=data_path, tracks_dir=tracks_dir, state_path=state_path,
                    client=object(), vocab=VOCAB, now=now, log=lambda s: None, call=fake)
    assert out["tagged"] == 1 and out["remaining"] == 0 and len(fake.calls) == 2  # only the other new album; nothing retagged
    out = moods.run("daily", cap=10, data_path=data_path, tracks_dir=tracks_dir, state_path=state_path,
                    client=object(), vocab=VOCAB, now=now, log=lambda s: None, call=fake)
    assert out["tagged"] == 0 and len(fake.calls) == 2
    assert json.loads(state_path.read_text(encoding="utf-8"))["tagged"] == 2


def test_backfill_walks_the_untagged_set_and_reports_complete(tmp_path):
    rows = [_row("a", "A Soundtrack", 1), _row("b", "B Soundtrack", 1, date="2015-01-01"), _row("c", "C Soundtrack", 1, moods=[])]
    data_path, tracks_dir, state_path = _setup(tmp_path, rows, {rid: [{"title": "T"}] for rid in "abc"})
    fake = FakeModel({"A Sound": [reply([(1, ["wonder"])])], "B Sound": ["nope", "still nope"]})
    logs = []
    out = moods.run("backfill", cap=5, data_path=data_path, tracks_dir=tracks_dir, state_path=state_path,
                    client=object(), vocab=VOCAB, log=logs.append, call=fake)
    assert out["tagged"] == 1 and out["skipped"] == 1 and out["remaining"] == 1 and logs[-1].startswith("moods in progress")
    fake.scripts["B Sound"] = [reply([(1, ["peaceful"])])]
    out = moods.run("backfill", cap=5, data_path=data_path, tracks_dir=tracks_dir, state_path=state_path,
                    client=object(), vocab=VOCAB, log=logs.append, call=fake)
    assert out["tagged"] == 1 and out["remaining"] == 0 and logs[-1] == "moods complete"
    saved = {r["id"]: r for r in json.loads(data_path.read_text(encoding="utf-8"))["releases"]}
    assert saved["a"]["moods"] == ["wonder"] and saved["b"]["moods"] == ["peaceful"] and saved["c"]["moods"] == []
    # --retag reaches albums that already carry moods
    fake.scripts.update({"A Sound": [reply([(1, ["sad"])])], "C Sound": [reply([(1, ["eerie"])])]})
    out = moods.run("backfill", cap=5, retag=True, data_path=data_path, tracks_dir=tracks_dir, state_path=state_path,
                    client=object(), vocab=VOCAB, log=logs.append, call=fake)
    assert out["tagged"] == 3
    saved = {r["id"]: r for r in json.loads(data_path.read_text(encoding="utf-8"))["releases"]}
    assert saved["a"]["moods"] == ["sad"] and saved["c"]["moods"] == ["eerie"]


def test_a_missing_key_skips_tagging_without_failing(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    rows = [_row("a", "A Soundtrack", 1)]
    data_path, tracks_dir, state_path = _setup(tmp_path, rows, {"a": [{"title": "T"}]})
    logs = []
    assert moods.run("daily", data_path=data_path, tracks_dir=tracks_dir, state_path=state_path, log=logs.append) is None
    assert logs == ["moods: ANTHROPIC_API_KEY not set, tagging skipped"]
    assert "moods" not in json.loads(data_path.read_text(encoding="utf-8"))["releases"][0] and not state_path.exists()


def test_a_transport_failure_leaves_the_row_for_next_time(tmp_path):
    rows = [_row("a", "A Soundtrack", 1)]
    data_path, tracks_dir, state_path = _setup(tmp_path, rows, {"a": [{"title": "T"}]})
    def boom(client, system, prompt):
        raise RuntimeError("503")
    out = moods.run("daily", data_path=data_path, tracks_dir=tracks_dir, state_path=state_path,
                    client=object(), vocab=VOCAB, log=lambda s: None, call=boom)
    assert out["failed"] == 1 and out["tagged"] == 0 and out["remaining"] == 1
    assert "moods" not in json.loads(data_path.read_text(encoding="utf-8"))["releases"][0]


def test_cost_matches_haiku_pricing():
    assert abs(moods.cost(1_000_000, 0) - 1.00) < 1e-9 and abs(moods.cost(0, 1_000_000) - 5.00) < 1e-9
