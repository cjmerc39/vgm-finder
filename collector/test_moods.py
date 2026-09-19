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


def test_schema_pins_the_vocabulary_and_rejections_say_why():
    assert moods.SCHEMA["properties"]["tracks"]["items"]["properties"]["moods"]["items"]["enum"] == TERMS
    assert moods.parse_reply_why(reply([(1, ["spooky"])]), 1, TERMS) == (None, "track 1: 'spooky' is outside the vocabulary")
    assert moods.parse_reply_why("nope", 1, TERMS) == (None, "not JSON")
    assert moods.parse_reply_why(reply([(4, ["tense"])]), 2, TERMS) == (None, "track 4 not asked about")
    assert moods.parse_reply_why(reply([(1, ["tense"])]), 1, TERMS) == ({1: ["tense"]}, "")
    r, tracks = _row("x", "Twice Bad Soundtrack", 1), [{"title": "A"}]
    res = moods.tag_album(None, r, tracks, VOCAB, call=FakeModel({"Twice Bad": [reply([(1, ["spooky"])]), "garbage"]}))
    assert res["why"] == "not JSON" and res["reply"] == "garbage"


def test_album_prompt_names_the_work_and_numbers_the_tracks():
    r = _row("hades", "Hades Soundtrack", 2, composers=["Darren Korb"], genres=["Role-playing (RPG)"])
    p = moods.album_prompt(r, [{"title": "No Escape"}, {"title": "The Painted World"}])
    assert "Work: Hades (video game, 2026)" in p and "Composers: Darren Korb" in p and "Genres: Role-playing (RPG)" in p
    assert p.endswith("Tracks:\n1. No Escape\n2. The Painted World")


def test_album_prompt_drops_a_title_s_own_track_number():
    # Pikmin's selection is tracks 1, 2, 4, 5 and 8 of a longer album
    r = _row("pikmin", "Pikmin Soundtrack", 3)
    tracks = [{"title": "1 - S.S. Drake (Ballad/Waltz)"}, {"title": "4 - Pikmin Discovery Theme"},
              {"title": "8 - Mission Mode (Reggae)"}, {"title": "1999 (Remix)"}, {"title": "2. Ending"}]
    p = moods.album_prompt(r, tracks)
    assert p.endswith("Tracks:\n1. S.S. Drake (Ballad/Waltz)\n2. Pikmin Discovery Theme\n3. Mission Mode (Reggae)"
                      "\n4. 1999 (Remix)\n5. Ending")
    assert tracks[2]["title"] == "8 - Mission Mode (Reggae)"  # the stored title is left alone


# ----------------------------------------------------------------- tag_album

def test_tag_album_writes_track_moods_and_the_albums_top_moods_commonest_first():
    r = _row("hades", "Hades Soundtrack", 3)
    tracks = [{"title": "A"}, {"title": "B"}, {"title": "C"}]
    fake = FakeModel({"Hades": [reply([(1, ["driving", "tense"]), (2, ["tense"]), (3, [])])]})
    res = moods.tag_album(None, r, tracks, VOCAB, call=fake)
    assert res == {"ok": True, "in": 600, "out": 40, "tries": 1, "calls": 1}
    assert tracks[0]["moods"] == ["driving", "tense"] and tracks[1]["moods"] == ["tense"] and "moods" not in tracks[2]
    assert r["moods"] == ["tense", "driving"]  # tense on two tracks outranks driving on one
    assert r["moodsN"] == [2, 1]


def test_album_moods_keep_the_top_three_by_track_count():
    tracks = [{"title": "A", "moods": ["eerie", "tense", "sad"]},
              {"title": "B", "moods": ["eerie", "tense"]},
              {"title": "C", "moods": ["eerie", "mysterious"]},
              {"title": "D", "moods": ["sad", "peaceful"]},
              {"title": "E", "moods": ["joyful"]}]
    assert moods.album_moods(tracks, TERMS) == (["eerie", "tense", "sad"], [3, 2, 2])


def test_album_moods_break_a_count_tie_by_plays_then_the_vocabulary():
    tracks = [{"title": "A", "plays": "2K plays", "moods": ["sad"]},
              {"title": "B", "plays": "1.5M plays", "moods": ["mysterious"]},
              {"title": "C", "plays": "900 plays", "moods": ["tense", "sad"]},
              {"title": "D", "plays": None, "moods": ["wonder"]},
              {"title": "E", "moods": ["powerful"]}]
    # sad has two tracks; mysterious beats tense on plays; wonder and
    # powerful tie at nothing and fall to the vocabulary's order past three
    assert moods.album_moods(tracks, TERMS) == (["sad", "mysterious", "tense"], [2, 1, 1])
    bare = [{"title": "A", "moods": ["powerful"]}, {"title": "B", "moods": ["wonder"]}]
    assert moods.album_moods(bare, TERMS) == (["wonder", "powerful"], [1, 1])  # wonder comes first in the list


def test_derive_reranks_tagged_rows_from_their_tracks_without_the_api(tmp_path):
    rows = [_row("a", "A Soundtrack", 3, moods=["tense", "eerie", "sad", "wonder"]),  # the old union
            _row("b", "B Soundtrack", 1),                                              # untagged: left alone
            _row("c", "C Soundtrack", 1, moods=["joyful"], moodsN=[1])]               # already right
    data_path, tracks_dir, _ = _setup(tmp_path, rows, {
        "a": [{"title": "1", "moods": ["eerie", "tense"]}, {"title": "2", "moods": ["eerie"]},
              {"title": "3", "moods": ["sad", "wonder"], "plays": "10K plays"}],
        "b": [{"title": "1"}],
        "c": [{"title": "1", "moods": ["joyful"]}]})
    logs = []
    assert moods.derive(data_path, tracks_dir, log=logs.append) == 1
    out = {r["id"]: r for r in json.loads(data_path.read_text(encoding="utf-8"))["releases"]}
    # tense loses its place on plays; sad and wonder tie on both, so the vocabulary puts wonder first
    assert out["a"]["moods"] == ["eerie", "wonder", "sad"] and out["a"]["moodsN"] == [2, 1, 1]
    assert "moods" not in out["b"] and out["c"]["moodsN"] == [1]
    assert logs == ["moods derive: 2 tagged rows read, 1 changed"]


def test_tag_album_retries_a_bad_reply_once_then_gives_up():
    r = _row("hades", "Hades Soundtrack", 1)
    tracks = [{"title": "A"}]
    fake = FakeModel({"Hades": ["garbage", reply([(1, ["heroic"])])]})
    res = moods.tag_album(None, r, tracks, VOCAB, call=fake)
    assert res["ok"] and res["tries"] == 2 and res["in"] == 1200 and tracks[0]["moods"] == ["heroic"]
    r2, tracks2 = _row("x", "Twice Bad Soundtrack", 1), [{"title": "A"}]
    fake = FakeModel({"Twice Bad": [reply([(1, ["spooky"])]), "still garbage"]})
    res = moods.tag_album(None, r2, tracks2, VOCAB, call=fake)
    assert res == {"ok": False, "in": 1200, "out": 80, "tries": 2, "calls": 2, "why": "not JSON", "reply": "still garbage"}
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
    assert res["ok"] is False and res["calls"] == 3 and res["why"] == "not JSON"
    assert "moods" not in r2 and not any("moods" in t for t in tracks2)


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
    assert r["moods"] == [] and r["moodsN"] == [] and not any("moods" in t for t in tracks)


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


# ------------------------------------------------ vocabulary v2, sample, batch
from pathlib import Path
from types import SimpleNamespace

V2 = moods.load_vocab(Path(moods.__file__).resolve().parent / "moods-v2.json")
V2_PATH = Path(moods.__file__).resolve().parent / "moods-v2.json"


def test_v2_is_the_twenty_checked_moods_and_a_new_vocabulary_retags_the_old():
    terms = [m for m, _ in V2]
    assert len(terms) == 20 and moods.vocab_version(V2_PATH) == 2 and moods.vocab_version() == 1
    assert {"suspenseful", "ominous", "intense", "epic", "dreamy", "hopeful", "laid-back"} <= set(terms)
    assert not {"tense", "mournful", "powerful"} & set(terms)
    rows = [_row("old", "Old Soundtrack", 2, moods=["tense"]), _row("new", "New Soundtrack", 2, moods=["epic"], moodsV=2),
            _row("none", "None Soundtrack", 2)]
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        for r in rows:
            (Path(d) / f"{r['id']}.json").write_text("[]", encoding="utf-8")
        assert [r["id"] for r in moods.untagged(rows, d, version=1)] == ["none"]
        assert sorted(r["id"] for r in moods.untagged(rows, d, version=2)) == ["none", "old"]


def test_tagging_with_v2_stamps_the_version_and_uses_its_enum():
    r = _row("zelda", "Zelda Soundtrack", 2)
    tracks = [{"title": "A"}, {"title": "B"}]
    seen = []

    def fake(client, system, prompt):
        seen.append(system)
        return reply([(1, ["epic", "heroic"]), (2, ["dreamy"])]), 500, 30
    assert moods.tag_album(None, r, tracks, V2, call=fake, version=2)["ok"]
    assert r["moods"] == ["epic", "heroic", "dreamy"] and r["moodsV"] == 2 and "- dreamy:" in seen[0]  # one track each: list order
    assert moods.parse_reply(reply([(1, ["tense"])]), 1, [m for m, _ in V2]) is None  # the old word is off the list


def test_the_sample_writes_a_review_file_and_leaves_the_catalog_alone(tmp_path):
    rows = [_row(f"g{i}", f"Game {i} Soundtrack", 4, playsTotal=1000 - i, moods=["tense"]) for i in range(3)]
    rows += [dict(_row("f1", "Film One Soundtrack", 4, playsTotal=50, moods=["sad"]), medium="film")]
    tracks = {r["id"]: [{"title": f"T{k}", "moods": ["tense"]} for k in range(4)] for r in rows}
    data_path, tracks_dir, state_path = _setup(tmp_path, rows, tracks)
    before = data_path.read_text(encoding="utf-8"), {p.name: p.read_text(encoding="utf-8") for p in tracks_dir.iterdir()}
    fake = FakeModel({"Soundtrack": [reply([(1, ["suspenseful"]), (2, ["ominous"]), (3, ["intense"]), (4, ["epic"])])]})
    out = tmp_path / "sample.json"
    entries = moods.run_sample(per_medium=2, vocab_path=V2_PATH, data_path=data_path, tracks_dir=tracks_dir,
                               out_path=out, state_path=state_path, client=object(), workers=1, log=lambda *_: None, call=fake)
    assert [e["id"] for e in entries] == ["g0", "g1", "f1"]  # the most played of each medium
    review = json.loads(out.read_text(encoding="utf-8"))
    assert review["vocabVersion"] == 2 and review["albums"][0]["old"] == ["tense"]
    assert review["albums"][0]["new"] == ["suspenseful", "ominous", "intense"]
    assert review["albums"][0]["tracks"][0] == {"title": "T0", "old": ["tense"], "new": ["suspenseful"]}
    assert (data_path.read_text(encoding="utf-8"), {p.name: p.read_text(encoding="utf-8") for p in tracks_dir.iterdir()}) == before
    assert json.loads(state_path.read_text(encoding="utf-8"))["runs"][-1]["kind"] == "sample"


class FakeBatches:
    """messages.batches: create, retrieve (processing then ended), results."""
    def __init__(self, outcomes):
        self.outcomes, self.created, self.polls = outcomes, None, 0

    def create(self, requests):
        self.created = requests
        return SimpleNamespace(id="msgbatch_1")

    def retrieve(self, bid):
        self.polls += 1
        return SimpleNamespace(processing_status="ended" if self.polls > 1 else "in_progress")

    def results(self, bid):
        for req in self.created:
            kind, text = self.outcomes(req)
            msg = SimpleNamespace(content=[SimpleNamespace(type="text", text=text)],
                                  usage=SimpleNamespace(input_tokens=1000, output_tokens=200))
            yield SimpleNamespace(custom_id=req["custom_id"], result=SimpleNamespace(type=kind, message=msg))


def test_the_batch_retags_every_album_whose_chunks_all_came_back(tmp_path, monkeypatch):
    monkeypatch.setattr(moods, "CHUNK_TRACKS", 2)
    rows = [_row("whole", "Whole Soundtrack", 3, moods=["tense"]), _row("split", "Split Soundtrack", 4, moods=["sad"]),
            _row("bad", "Bad Soundtrack", 2, moods=["joyful"]), _row("done", "Done Soundtrack", 1, moods=["epic"], moodsV=2)]
    tracks = {"whole": [{"title": "W1"}, {"title": "W2"}, {"title": "W3"}], "split": [{"title": f"S{i}"} for i in range(4)],
              "bad": [{"title": "B1", "moods": ["joyful"]}, {"title": "B2"}], "done": [{"title": "D1"}]}
    data_path, tracks_dir, state_path = _setup(tmp_path, rows, tracks)

    def outcomes(req):
        prompt = req["params"]["messages"][0]["content"]
        nums = [int(x.split(".")[0]) for x in prompt.splitlines() if x[:1].isdigit() and ". " in x]
        if "Bad" in prompt:
            return "succeeded", reply([(1, ["tense"])])            # an old word: the album keeps its moods
        if "Split" in prompt and 3 in nums:
            return "errored", ""                                   # one chunk lost: the whole album waits
        return "succeeded", reply([(n, ["dreamy"]) for n in nums])
    fake = FakeBatches(outcomes)
    client = SimpleNamespace(messages=SimpleNamespace(batches=fake))
    batch_path = tmp_path / "batch.json"
    rec = moods.batch_submit(vocab_path=V2_PATH, data_path=data_path, tracks_dir=tracks_dir, batch_path=batch_path,
                             client=client, log=lambda *_: None)
    assert rec["albums"] == 3 and rec["requests"] == 5 and all(len(r["custom_id"]) < 64 for r in fake.created)
    assert fake.created[0]["params"]["output_config"]["format"]["schema"]["properties"]["tracks"]["items"]["properties"]["moods"]["items"]["enum"][0] == "suspenseful"
    assert moods.batch_submit(vocab_path=V2_PATH, data_path=data_path, tracks_dir=tracks_dir, batch_path=batch_path,
                              client=client, log=lambda *_: None) is None  # one batch at a time
    logs = []
    summary = moods.batch_collect(data_path=data_path, tracks_dir=tracks_dir, batch_path=batch_path, state_path=state_path,
                                  client=client, poll=0, log=logs.append, sleep=lambda s: None)
    out = {r["id"]: r for r in json.loads(data_path.read_text(encoding="utf-8"))["releases"]}
    assert out["whole"]["moods"] == ["dreamy"] and out["whole"]["moodsV"] == 2
    assert out["split"]["moods"] == ["sad"] and "moodsV" not in out["split"]
    assert out["bad"]["moods"] == ["joyful"] and "moodsV" not in out["bad"]
    assert json.loads((tracks_dir / "whole.json").read_text(encoding="utf-8"))[2]["moods"] == ["dreamy"]
    assert summary["tagged"] == 1 and summary["failed"] == 1 and summary["skipped"] == 1
    assert abs(summary["cost"] - moods.cost(4000, 800) * 0.5) < 1e-9     # four replies came back, billed at half price
    assert json.loads(batch_path.read_text(encoding="utf-8"))["applied"] is True
    assert "2 not yet on v2" in logs[0]
