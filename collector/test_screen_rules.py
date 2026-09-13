"""Screen matcher rules (MATCHER-FIX-SPEC Phase 1).

fixtures/ytm-screen-rules.json is a verbatim capture of live YouTube Music
search results taken 2026-09-13, one entry per query. Composer aliases
stand in for TMDb's also_known_as, which the Phase 1 probe checks live.
"""
import json
from pathlib import Path

import collect
from test_collect import SEEN, screen_resolve, src

RULES = json.loads((Path(__file__).parent / "fixtures" / "ytm-screen-rules.json")
                   .read_text(encoding="utf-8"))


def rules_resolve(query, limit=8):
    return RULES.get(query, [])


def film(name, year, composers, original=None, aliases=None, tid=None):
    return {"medium": "film", "id": tid or name, "name": name, "original": original,
            "years": [year], "composers": composers, "aliases": aliases or []}


def show(name, years, composers, original=None, aliases=None):
    return {"medium": "tv", "id": name, "name": name, "original": original,
            "years": years, "composers": composers, "aliases": aliases or []}


def judged(info, album_fn=None, resolve=rules_resolve):
    return collect.screen_classify(collect.screen_search(resolve, info), info, album_fn)


def best(info, album_fn=None, reserved=()):
    cands = [c for c in judged(info, album_fn) if c["accepted"]]
    winners, _ = collect.resolve_screen(collect.screen_slots(info, cands), reserved=reserved)
    return winners


def winner(info, album_fn=None):
    return best(info, album_fn).get(("film", info["id"]))


def verdict(info, album_prefix, album_fn=None):
    for c in judged(info, album_fn):
        if c["title"].startswith(album_prefix):
            return c
    raise AssertionError(f"{album_prefix!r} not among the results")


# ---------------- rule 1: exact title with wording ----------------

def test_rule1_exact_title_with_wording_keeps_its_era_guard():
    info = film("Rogue One: A Star Wars Story", 2016, ["Michael Giacchino"])
    real = verdict(info, "Rogue One: A Star Wars Story (Original Motion Picture Soundtrack)")
    assert real["accepted"] and real["rule"].startswith("1")
    # a 2022 re-recording normalizes to the exact title and carries wording,
    # but has no credited composer and sits six years out
    remake = verdict(info, "Music from Rogue One: A Star Wars Story")
    assert not remake["accepted"] and remake["verdict"].startswith("rule 1")
    assert winner(info)["title"] == "Rogue One: A Star Wars Story (Original Motion Picture Soundtrack)"


def test_blade_runner_keeps_its_album_when_a_suffix_leaves_a_fragment():
    w = winner(film("Blade Runner", 1982, ["Vangelis"]))
    assert w["title"] == "Blade Runner (Music From The Original Soundtrack)" and w["rule"].startswith("1")


# ---------------- rule 2: exact title with no wording ----------------

def test_rule2_bare_exact_titles_recover_with_the_composer():
    jp = winner(film("Jurassic Park", 1993, ["John Williams"]))
    assert jp["title"] == "Jurassic Park" and jp["rule"].startswith("2") and not jp["weak"]
    b2 = winner(film("Back to the Future Part II", 1989, ["Alan Silvestri"]))
    assert b2["title"] == "Back To The Future Part II" and b2["rule"].startswith("2") and not b2["weak"]


def test_rule2_without_a_composer_needs_plays_and_is_weak():
    # the 1985 songs album: a bare exact title credited to Various Artists
    only = [r for r in RULES["Back to the Future soundtrack"] if r["title"] == "Back to the Future"]
    loud = lambda bid: {"tracks": [{"title": "The Power of Love", "views": "90M plays"}]}
    quiet = lambda bid: {"tracks": [{"title": "Track", "views": "900 plays"}]}
    w = collect.match_film(only, "Back to the Future", 1985, [], album_fn=loud)
    assert w and w["weak"] and w["klass"] == "weak"
    assert collect.match_film(only, "Back to the Future", 1985, [], album_fn=quiet) is None
    assert collect.match_film(only, "Back to the Future", 1985, []) is None  # plays unknown: no row
    assert collect.match_film(only, "Back to the Future", 1995, [], album_fn=loud) is None  # era


def test_rule2_composer_path_keeps_the_era_window():
    # The Last of Us game album (2013) is a bare exact title by the show's own
    # composer; the show's seasons aired 2023 and 2025
    info = show("The Last of Us", [2023, 2025], ["Gustavo Santaolalla", "David Fleming"])
    game = next(c for c in collect.screen_classify(screen_resolve("The Last of Us soundtrack"), info)
                if c["title"] == "The Last of Us")
    assert not game["accepted"] and "outside the window" in game["verdict"]


# ---------------- rule 3: franchise prefix or suffix ----------------

def test_rule3_franchise_prefix_with_composer_and_era():
    empire = winner(film("The Empire Strikes Back", 1980, ["John Williams"]))
    assert empire["title"] == "Star Wars: The Empire Strikes Back (Original Motion Picture Soundtrack)"
    assert empire["rule"].startswith("3")
    jedi = film("Return of the Jedi", 1983, ["John Williams"])
    assert winner(jedi)["title"] == "Star Wars: Return of the Jedi (Original Motion Picture Soundtrack)"
    assert winner(film("Return of the Jedi", 1983, [])) is None  # the prefix needs the composer


def test_rule3_still_needs_soundtrack_wording():
    # a 1983 re-recording compilation contains the title and credits the
    # composer, but never says soundtrack: only rule 2 waives wording, and
    # only for exact titles
    c = verdict(film("Return of the Jedi", 1983, ["John Williams"]),
                "The Star Wars Trilogy (Return of the Jedi")
    assert not c["accepted"] and "wording" in c["verdict"]


def test_wording_only_extras_name_the_title_itself():
    def rel(name, album):
        return collect._relation(collect.normalize_screen(album, "film").split(),
                                 collect._screen_wants(film(name, 2000, [])))
    for name, album in [
            ("Alien: Covenant", "Alien: Covenant (Original Soundtrack Album)"),
            ("Psycho", "Psycho (The Complete Original Motion Picture Score)"),
            ("One Flew Over the Cuckoo's Nest", "One Flew Over The Cuckoo's Nest (Original Motion "
             "Picture Soundtrack / 50th Anniversary / Remastered 2025)"),
            ("The Good, the Bad and the Ugly",
             "The Good, The Bad and The Ugly (Original Motion Picture Soundtrack) (Remastered Edition)"),
            ("My Neighbor Totoro", "My Neighbor Totoro Soundtrack Collection"),
            ("Halloween", "Halloween Motion Picture Soundtrack"),
            ("Hotel Transylvania", "Hotel Transylvania: Score from the Motion Pictures")]:
        assert rel(name, album) == ("exact", 0, []), album
    for name, album in [
            ("Frozen", "Frozen 2 (Original Motion Picture Soundtrack / Deluxe Edition)"),
            ("Ant-Man", "Ant-Man and The Wasp (Original Motion Picture Soundtrack)"),
            ("Star Trek", "Star Trek: The Motion Picture (Original Soundtrack)"),
            ("The Hangover", "The Hangover Trilogy (Original Score)"),
            ("Die Hard", "Die Hard 2: Die Harder (Original Motion Picture Soundtrack)"),
            ("Blade Runner", "Blade Runner 2049 (Original Motion Picture Soundtrack)")]:
        assert rel(name, album)[0] == "extended", album


def test_more_wording_articles_and_own_years():
    def rel(name, album, years=()):
        return collect._relation(collect.normalize_screen(album, "film").split(),
                                 collect._screen_wants(film(name, 2000, [])), years)
    for name, album in [
            ("Pitch Black", "Pitch Black (Original Score from the Motion Picture)"),
            ("Cashback", "Cashback (Original Soundtrack Recording)"),
            ("Videodrome", "Videodrome (The Complete Restored Score)"),
            ("Jacob's Ladder", "Jacob's Ladder (Music from the Motion Picture) [35th Anniversary Edition]"),
            ("Crash", "Crash (The Complete Original Score Remastered) [Collector's Edition Vol. 4]")]:
        assert rel(name, album) == ("exact", 0, []), album
    assert rel("King Kong", "King Kong (Original 1933 Motion Picture Soundtrack)", [1933]) == ("exact", 0, [])
    for name, album, years in [
            ("King Kong", "King Kong (Original 1933 Motion Picture Soundtrack)", [2005]),
            ("Invasion", "The Invasion (Original Soundtrack)", ()),
            ("Hustlers", "The Hustlers Soundtrack", ()),
            ("Nowhere", "Nowhere Special (Original Motion Picture Soundtrack)", ()),
            ("Friday", "Friday the 13th (Original Motion Picture Soundtrack)", ())]:
        assert rel(name, album, years)[0] == "extended", album
    assert (collect.normalize_screen("The Terminal List (Music from the Original Series on Prime Video)", "tv")
            == "the terminal list")


def test_an_album_that_names_the_other_medium_belongs_to_it():
    mash = {"resultType": "album", "browseId": "m", "year": "1970", "thumbnails": [],
            "title": "M*A*S*H (Original Motion Picture Soundtrack)", "artists": [{"name": "Johnny Mandel"}]}
    c = collect.screen_classify([mash], show("M*A*S*H", [1972, 1973], ["Johnny Mandel"]))[0]
    assert not c["accepted"] and c["verdict"] == "medium: 'Motion Picture' names a film"
    assert collect.screen_classify([mash], film("M*A*S*H", 1970, ["Johnny Mandel"]))[0]["accepted"]
    sun = dict(mash, title="Midnight Sun (Original Soundtrack from the TV Series)", year="2016")
    c = collect.screen_classify([sun], film("Midnight Sun", 2018, ["Nate Walcott"]))[0]
    assert c["verdict"] == "medium: 'Series' names a series"
    snicket = dict(mash, year="2004",
                   title="Lemony Snicket's A Series of Unfortunate Events (Music from the Motion Picture)")
    c = collect.screen_classify([snicket], film("A Series of Unfortunate Events", 2004, ["Thomas Newman"]))[0]
    assert not c["verdict"].startswith("medium")


def test_episode_ranges_fold_away_on_tv_titles():
    assert collect.normalize_screen("Andor: Season 2 - Vol. 1 (Episodes 1-3) (Original Score)", "tv") == "andor"
    album = {"resultType": "album", "browseId": "a4", "year": "2025", "thumbnails": [],
             "title": "Andor: Season 2 - Vol. 4 (Episodes 10-12) (Original Score)",
             "artists": [{"name": "Brandon Roberts"}]}
    c = collect.screen_classify([album], show("Andor", [2022, 2025], []))[0]
    assert c["accepted"] and c["rule"] == "1 exact title" and (c["season"], c["volume"]) == (2, 4)


def test_walk3_blocklist_game_wording_and_spin_offs():
    def album(title, artist, year, bid="x"):
        return {"resultType": "album", "browseId": bid, "year": year, "thumbnails": [],
                "title": title, "artists": [{"name": artist}]}
    kick = collect.screen_classify([album("Music from Kick-Ass", "Ultimate Heroes", "2010")],
                                   film("Kick-Ass", 2010, ["Henry Jackman"]))[0]
    assert kick["verdict"] == "tribute artist 'Ultimate Heroes'"
    for artist in ("Union Of Sound", "Songs in Cinema", "Album", "Vita"):
        c = collect.screen_classify([album("Gossip Girl (Original Soundtrack)", artist, "2008")],
                                    show("Gossip Girl", [2007, 2008], []))[0]
        assert c["verdict"].startswith("tribute artist"), artist
    silence = collect.screen_classify([album("Silence (Original Game Soundtrack)", "Tilo Alpermann", "2016")],
                                      film("Silence", 2016, []))[0]
    assert silence["verdict"] == "medium: 'Original Game Soundtrack' names a video game"
    superman = dict(album("Superman Returns (Original Soundtrack)", "Colin O'Malley", "2006"),
                    artists=[{"name": "Colin O'Malley"}, {"name": "EA Games Soundtrack"}])
    assert collect.screen_classify([superman], film("Superman Returns", 2006, ["John Ottman"]))[0]["verdict"] \
        .startswith("medium:")
    squid = collect.screen_classify([album("Squid Game Soundtrack", "jung jaeil", "2021")],
                                    show("Squid Game", [2021], ["Jung Jae-il"]))[0]
    assert squid["accepted"]
    spin = collect.screen_classify([album("Outlander: Blood of my Blood (Season 1 Original Series Soundtrack)",
                                          "Bear McCreary", "2025")], show("Outlander", [2014, 2025], ["Bear McCreary"]))[0]
    assert spin["verdict"].startswith("spin-off:")
    final = collect.screen_classify(
        [album("Star Wars: The Bad Batch - The Final Season: Vol. 1 (Episodes 1-8) (Original Soundtrack)",
               "Kevin Kiner", "2024")], show("Star Wars: The Bad Batch", [2021, 2024], ["Kevin Kiner"]))[0]
    assert final["accepted"]
    # words after the name with no colon or dash are never a subtitle
    ep = collect.screen_classify([album("Chainsaw Man Original Soundtrack EP Vol.1 (Episode 1-3)", "Kensuke Ushio", "2022")],
                                 show("Chainsaw Man", [2022], ["Kensuke Ushio"]))[0]
    assert ep["accepted"]
    # a subtitle carrying a season marker is the show's own
    cobra = collect.screen_classify(
        [album('Cobra Kai: Season 4, Vol. 1 "All Valley Tournament 51" (Soundtrack from the Netflix Original Series)',
               "Leo Birenberg & Zach Robinson", "2021")], show("Cobra Kai", [2018, 2021], ["Leo Birenberg", "Zach Robinson"]))[0]
    assert cobra["accepted"]
    clear = collect.screen_classify([album("CARDCAPTOR SAKURA -CLEAR CARD- ORIGINAL SOUNDTRACK", "Takayuki Negishi", "2018")],
                                    show("Cardcaptor Sakura", [1998, 2000, 2018], ["Takayuki Negishi"]))[0]
    assert clear["verdict"] == "spin-off: the subtitle 'clear card' names another show"
    # a subtitle after the album's own wording names the album, not a show
    world = collect.screen_classify([album("ONE PIECE ORIGINAL SOUNDTRACK -NEW WORLD-", "Kohei Tanaka", "2016")],
                                    show("One Piece", [1999, 2016], ["Kohei Tanaka"]))[0]
    assert world["accepted"]


def test_weak_guard_turns_away_a_bare_title_by_another_act():
    fetched = []
    album = {"resultType": "album", "browseId": "kimmel", "year": "2005", "thumbnails": [],
             "title": "Jimmy Kimmel Live!", "artists": [{"name": "Simple Plan"}]}
    loud = lambda b: fetched.append(b) or {"tracks": [{"title": "t", "views": "5M plays"}]}
    c = collect.screen_classify([album], show("Jimmy Kimmel Live", [2003, 2026], []), loud)[0]
    assert not c["accepted"] and c["verdict"].startswith("weak guard") and fetched == []  # no plays read
    va = dict(album, artists=[{"name": "Various Artists"}])
    assert collect.screen_classify([va], show("Jimmy Kimmel Live", [2003, 2026], []), loud)[0]["weak"]


def test_daily_and_backfill_apply_screen_overrides():
    info = {"medium": "tv", "id": "62425", "name": "Dark Matter", "original": None, "years": [2015, 2017],
            "composers": ["Benjamin Pinkerton"], "aliases": [], "seasons": {"1": "2015-06-12"}}
    results = [{"resultType": "album", "browseId": "dm", "year": "2016", "thumbnails": [],
                "title": "Dark Matter (Original Series Soundtrack)", "artists": [{"name": "Benjamin Pinkerton"}]}]
    assert collect.screen_title_slots(info, results, None, collect.screen_override_sets({}))
    excluded = collect.screen_override_sets({"exclude": [{"medium": "tv", "tmdb": 62425, "album": "dm"}]})
    assert collect.screen_title_slots(info, results, None, excluded) == {}
    pins = collect.screen_override_sets({"tv": [{"tmdb": 62425, "season": None, "album": "dm"}]})
    assert collect.screen_title_slots(info, results, None, pins)[("tv", "62425", None, None)][0]["pinned"]
    other = dict(info, id="196322", years=[2024, 2026])
    assert collect.screen_title_slots(other, results, None, pins) == {}  # pinned to another title


def test_walk4_signoff_rules():
    def album(title, artist, year, bid="x"):
        return {"resultType": "album", "browseId": bid, "year": year, "thumbnails": [],
                "title": title, "artists": [{"name": artist}]}
    # an album naming a season the show lacks belongs to a namesake
    who = album("Doctor Who Series 10 (Original Television Soundtrack)", "Murray Gold", "2017")
    new_who = dict(show("Doctor Who", [2024, 2025], ["Murray Gold"]), seasons={"1": "2024-05-10", "2": "2025-04-12"})
    old_who = dict(show("Doctor Who", [2005, 2017], ["Murray Gold"]), seasons={str(n): f"{2004 + n}-04-01" for n in range(1, 14)})
    assert collect.screen_classify([who], new_who)[0]["verdict"] == "season: the show has no season 10 and began in 2024"
    assert collect.screen_classify([who], old_who)[0]["accepted"]
    assert collect.screen_classify([who], show("Doctor Who", [2024], ["Murray Gold"]))[0]["accepted"]  # no seasons known
    # TMDb lists a second season late: an album released after the show began is kept
    frieren = dict(show("Frieren: Beyond Journey's End", [2023, 2026], ["Evan Call"]), seasons={"1": "2023-09-29"})
    s2 = album("Frieren: Beyond Journey's End: Season 2 (Original Soundtrack)", "Evan Call", "2026")
    assert collect.screen_classify([s2], frieren)[0]["accepted"]
    # "Music for the Motion Picture" is wording, and unwraps from the front
    assert collect.normalize_screen("Music for the Motion Picture Victoria", "film") == "victoria"
    frahm = album("Music for the Motion Picture Victoria", "Nils Frahm", "2015")
    c = collect.screen_classify([frahm], film("Victoria", 2015, ["Nils Frahm"]))[0]
    assert c["accepted"] and c["rule"] == "1 exact title" and c["credited"]
    # the plays floor: an uncredited album by an unrelated act needs plays
    gringo = album("Gringo (Original Motion Picture Soundtrack)", "Antonio Mainenti", "2018", bid="g")
    info = film("Gringo", 2018, ["Christophe Beck"])
    quiet = lambda b: {"tracks": [{"title": "t", "views": "37 plays"}]}
    loud = lambda b: {"tracks": [{"title": "t", "views": "5K plays"}]}
    c = collect.screen_classify([gringo], info, quiet)[0]
    assert not c["accepted"] and c["verdict"].startswith("plays floor: 37 plays")
    assert collect.screen_classify([gringo], info, loud)[0]["accepted"]
    assert collect.screen_classify([gringo], info)[0]["accepted"]  # no album page to read: kept
    assert collect.screen_classify([gringo], info, lambda b: {"tracks": []})[0]["accepted"]  # no counts: kept
    asked = []
    va = dict(gringo, artists=[{"name": "Various Artists"}])
    assert collect.screen_classify([va], info, lambda b: asked.append(b) or quiet(b))[0]["accepted"] and asked == []
    real = dict(gringo, artists=[{"name": "Christophe Beck"}])
    assert collect.screen_classify([real], info, quiet)[0]["accepted"]  # the credited composer needs no plays


def test_composer_accents_fold_on_latin_names_only():
    assert collect._credited(["Roque Banos"], ["Roque Baños"])
    assert collect._credited(["Jóhann Jóhannsson"], ["Johann Johannsson"])
    assert collect._credited(["川井憲次"], ["川井 憲次"])
    assert not collect._credited(["Roque Banos"], ["Alberto Iglesias"])


def test_verdicts_name_the_condition_that_failed():
    info = film("Jurassic Park", 1993, ["John Williams"])
    far = {"resultType": "album", "browseId": "lw", "year": "1997", "thumbnails": [],
           "title": "The Lost World: Jurassic Park (Original Motion Picture Score)",
           "artists": [{"name": "John Williams"}]}
    assert collect.screen_classify([far], info)[0]["verdict"] == "rule 3: needs the album year within the window"
    assert collect.screen_classify([dict(far, year=None)], info)[0]["verdict"] == "rule 3: needs a known album year"
    c = collect.screen_classify([dict(far, year=None, artists=[{"name": "Somebody"}])], info)[0]
    assert c["verdict"] == "rule 3: needs the credited composer, a known album year"


def test_a_result_without_its_year_reads_it_from_the_album_page():
    info = film("Rogue One: A Star Wars Story", 2016, ["Michael Giacchino"])
    bare = {"resultType": "album", "browseId": "ro", "year": None, "thumbnails": [],
            "title": "Rogue One: A Star Wars Story (Original Motion Picture Soundtrack)",
            "artists": [{"name": "Various Artists"}]}
    c = collect.screen_classify([bare], info)[0]
    assert c["verdict"] == "rule 1: no credited composer and the album year is unknown"
    asked = []
    c = collect.screen_classify([bare], info, lambda b: asked.append(b) or {"year": "2016"})[0]
    assert c["accepted"] and c["gap"] == 0 and c["yearFrom"] == "album" and asked == ["ro"]
    c = collect.screen_classify([bare], info, lambda b: {"year": None})[0]
    assert not c["accepted"] and "is unknown" in c["verdict"]
    c = collect.screen_classify([dict(bare, year="2016")], info, lambda b: asked.append(b))[0]
    assert c["accepted"] and "yearFrom" not in c and asked == ["ro"]  # a dated result costs no call


def test_rule3_era_keeps_the_lost_world_off_jurassic_park():
    c = verdict(film("Jurassic Park", 1993, ["John Williams"]), "The Lost World: Jurassic Park")
    assert not c["accepted"] and c["verdict"].startswith("rule 3")


# ---------------- rule 4: episode markers ----------------

def test_rule4_episode_markers_on_the_tmdb_title():
    for name, year, album in [
            ("Star Wars: Episode I - The Phantom Menace", 1999,
             "Star Wars: The Phantom Menace (Original Motion Picture Soundtrack)"),
            ("Star Wars: Episode II - Attack of the Clones", 2002,
             "Star Wars: Attack of the Clones (Original Motion Picture Soundtrack)"),
            ("Star Wars: Episode III - Revenge of the Sith", 2005,
             "Star Wars: Revenge of the Sith (Original Motion Picture Soundtrack)")]:
        w = winner(film(name, year, ["John Williams"]))
        assert w and w["title"] == album and w["rule"].startswith("4"), name
    # Episode III's search surfaces I and II too: they name other works
    c = verdict(film("Star Wars: Episode III - Revenge of the Sith", 2005, ["John Williams"]),
                "Star Wars: The Phantom Menace")
    assert not c["accepted"] and c["verdict"].startswith("title")


def test_rule4_strips_episode_markers_only():
    # a general subset rule would read the first Dune album as Part Two's
    info = film("Dune: Part Two", 2024, ["Hans Zimmer"])
    first = next(c for c in collect.screen_classify(screen_resolve("Dune: Part Two soundtrack"), info)
                 if c["title"] == "Dune (Original Motion Picture Soundtrack)")
    assert not first["accepted"] and first["verdict"].startswith("title")


# ---------------- rule 5: ranking ----------------

def test_rule5_exact_beats_extended_whatever_the_years():
    info = film("Back to the Future", 1985, ["Alan Silvestri"])
    assert winner(info)["title"] == \
        "Back To The Future (Original Motion Picture Soundtrack / Expanded Edition)"
    pt3 = verdict(info, "Back To The Future, Pt. 3")
    assert not pt3["accepted"] and "sequel guard" in pt3["verdict"]


def test_rule5_credited_first_then_fewer_extra_words():
    noct = show("Castlevania: Nocturne", [2023, 2025], ["Trevor Morris", "Trey Toy"])
    ws = best(noct)
    # an exact but uncredited upload loses to the credited series album
    assert verdict(noct, "Castlevania Nocturne (Original Soundtrack)")["accepted"]
    assert ws[("tv", noct["id"], None, None)]["title"] == "Castlevania Nocturne (Original Series Soundtrack)"
    assert ws[("tv", noct["id"], 2, None)]["title"] == "Castlevania Nocturne Season 2 (Original Series Soundtrack)"
    # Empire: the real soundtrack adds two words ("star wars"), the Symphonic
    # Suite three ("symphonic suite from"), so the real soundtrack ranks first
    suite = verdict(film("The Empire Strikes Back", 1980, ["John Williams"]),
                    "The Empire Strikes Back (Symphonic Suite")
    assert suite["accepted"] and suite["extra"] == 3
    real = verdict(film("The Empire Strikes Back", 1980, ["John Williams"]),
                   "Star Wars: The Empire Strikes Back")
    assert real["accepted"] and real["extra"] < suite["extra"]


# ---------------- rule 6: resolution across titles ----------------

def _slots(info, results=None):
    cands = collect.screen_matches(results if results is not None
                                   else collect.screen_search(rules_resolve, info), info)
    return collect.screen_slots(info, cands)


def test_rule6_each_album_lands_with_its_own_title_in_any_order():
    jp = film("Jurassic Park", 1993, ["John Williams"], tid="329")
    lw = film("The Lost World: Jurassic Park", 1997, ["John Williams"], tid="330")
    both = {**_slots(jp), **_slots(lw)}
    for slots in (both, dict(reversed(list(both.items())))):
        w, _ = collect.resolve_screen(slots)
        assert w[("film", "329")]["title"] == "Jurassic Park"
        assert w[("film", "330")]["title"] == "The Lost World: Jurassic Park (Original Motion Picture Score)"


def test_rule6_exact_claim_wins_a_contested_album():
    # force the contest: the Lost World album moved inside Jurassic Park's
    # era, and Jurassic Park's own albums gone, so both titles want it
    lost = next(r for r in RULES["Jurassic Park soundtrack"] if r["title"].startswith("The Lost World"))
    moved = dict(lost, year="1994")
    jp = film("Jurassic Park", 1993, ["John Williams"], tid="329")
    lw = film("The Lost World: Jurassic Park", 1997, ["John Williams"], tid="330")
    jp_slots, lw_slots = _slots(jp, [moved]), _slots(lw, [moved])
    assert jp_slots[("film", "329")][0]["klass"] == "extended"
    assert lw_slots[("film", "330")][0]["klass"] == "exact"
    for slots in ({**jp_slots, **lw_slots}, {**lw_slots, **jp_slots}):
        w, conflicts = collect.resolve_screen(slots)
        assert w[("film", "330")]["title"] == moved["title"]
        assert ("film", "329") not in w and conflicts


def test_reserved_albums_are_never_handed_out():
    # the Castlevania game row owns the 2019 compilation; the 2017 series has
    # no album of its own, and Nocturne's are past its last season or uncredited
    cv = show("Castlevania", [2017, 2018, 2019, 2020, 2021], ["Trevor Morris"])
    assert not verdict(cv, "Castlevania Nocturne Season 2")["accepted"]
    assert not verdict(cv, "Castlevania Nocturne (Original Series Soundtrack)")["accepted"]
    game = next(r for r in RULES["Castlevania soundtrack"] if r["title"] == "Castlevania Original Soundtrack")
    assert best(cv, reserved={"https://music.youtube.com/browse/" + game["browseId"]}) == {}


# ---------------- rule 7: abbreviations ----------------

def test_rule7_abbreviations_read_as_parts_and_volumes():
    assert collect._screen_base("Back To The Future, Pt. 3") == "back to the future part 3"
    assert collect._screen_base("Back to the Future Part III") == "back to the future part 3"
    assert collect._screen_base("Dune: Part Two") == "dune part 2"
    assert collect._screen_base("Kill Bill: Vol. 2") == "kill bill volume 2"
    # films fold a trailing first volume (their own soundtrack) and keep any later one
    assert collect.normalize_screen("Kill Bill Vol. 1 (Original Soundtrack)", "film") == "kill bill"
    assert collect.normalize_screen("Kill Bill Vol. 2 (Original Soundtrack)", "film") == "kill bill volume 2"
    b3 = winner(film("Back to the Future Part III", 1990, ["Alan Silvestri"]))
    assert b3["title"] == "Back To The Future, Pt. 3 (Original Motion Picture Score)"
    assert b3["rule"].startswith("1")


def test_sequel_guard_in_every_spelling_except_a_first_volume():
    for tail in (["2"], ["part", "3"], ["volume", "2"], ["chapter", "2"], ["2049"]):
        assert collect._is_sequel_tail(tail), tail
    assert not collect._is_sequel_tail(["volume", "1"])  # the title's own soundtrack, volume one
    assert not collect._is_sequel_tail(["a", "new", "hope"])
    # John Wick has worn Chapter 2's album since the old matcher folded
    # chapter markers for films too; the guard now reads it as the sequel
    info = film("John Wick", 2014, ["Tyler Bates", "Joel J. Richard"])
    album = {"resultType": "album", "browseId": "MPREb_jw2", "year": "2017",
             "title": "John Wick: Chapter 2 (Original Motion Picture Soundtrack)",
             "artists": [{"name": "Tyler Bates"}, {"name": "Joel J. Richard"}], "thumbnails": []}
    c = collect.screen_classify([album], info)[0]
    assert not c["accepted"] and "sequel guard" in c["verdict"]


def _album(title, artist, year, bid):
    return {"resultType": "album", "browseId": bid, "year": str(year), "title": title,
            "artists": [{"name": artist}], "thumbnails": []}


def test_a_first_volume_stays_an_exact_film_match_and_later_volumes_stay_apart():
    # catalog rows that were exact before the fix and must stay exact
    hm = collect.screen_classify(
        [_album("The Housemaid, Vol. 1 (Original Motion Picture Soundtrack)", "Various Artists", 2025, "h1")],
        film("The Housemaid", 2025, ["Theodore Shapiro"]))[0]
    assert hm["accepted"] and hm["klass"] == "exact"
    rrr = collect.screen_classify([_album("Rrr Ost Vol-1", "M. M. Keeravani", 2022, "r1")],
                                  film("RRR", 2022, ["M. M. Keeravani"]))[0]
    assert rrr["accepted"] and rrr["klass"] == "exact"
    # Kill Bill: each volume meets its own album and never the other's
    v1 = _album("Kill Bill Vol. 1 (Original Soundtrack)", "Various Artists", 2003, "kb1")
    v2 = _album("Kill Bill Vol. 2 (Original Soundtrack)", "Various Artists", 2004, "kb2")
    kb1 = film("Kill Bill: Vol. 1", 2003, ["RZA"], tid="24")
    kb2 = film("Kill Bill: Vol. 2", 2004, ["RZA"], tid="393")
    slots = {**collect.screen_slots(kb1, collect.screen_matches([v1, v2], kb1)),
             **collect.screen_slots(kb2, collect.screen_matches([v1, v2], kb2))}
    w, _ = collect.resolve_screen(slots)
    assert w[("film", "24")]["title"].startswith("Kill Bill Vol. 1")
    assert w[("film", "393")]["title"].startswith("Kill Bill Vol. 2")


def test_article_expanded_and_selections_wording_found_by_the_first_rewalk_shard():
    assert collect.normalize_screen("Bohemian Rhapsody (The Original Soundtrack)", "film") == "bohemian rhapsody"
    assert collect.normalize_screen("Gang Related (The Soundtrack)", "film") == "gang related"
    assert collect.normalize_screen("Scarface (Expanded Motion Picture Soundtrack)", "film") == "scarface"
    assert collect.normalize_screen(
        "The Shining (Selections from the Original Motion Picture Soundtrack)", "film") == "the shining"
    # a title whose name is "The Motion Picture" keeps it
    assert collect.normalize_screen(
        "Star Trek: The Motion Picture (Original Motion Picture Soundtrack)", "film") == \
        "star trek the motion picture"


def test_from_the_wording_is_stripped_before_the_network_pattern():
    cases = {
        "The Jinx (Music from the Original TV Series) (Music from the Original TV Series)": "the jinx",
        "Severance (Music from the Apple Original Series)": "severance",
        "Mayday (Soundtrack from the Apple Original Film)": "mayday",
        "Sterling Point (Prime Original Series Score)": "sterling point",
        "Stranger Things, Vol. 1 (A Netflix Original Series Soundtrack)": "stranger things",
    }
    for title, want in cases.items():
        assert collect.normalize_screen(title, "tv") == want, title


# ---------------- rule 8: original titles and composer aliases ----------------

def test_rule8_second_search_on_the_original_title():
    ip3 = film("Ip Man 3", 2015, ["Kenji Kawai"], original="葉問3", aliases=["川井憲次"])
    asked = []
    collect.screen_search(lambda q, limit=8: asked.append(q) or RULES.get(q, []), ip3)
    assert asked == ["Ip Man 3 soundtrack", "葉問3 soundtrack"]
    blind = lambda q, limit=8: [] if q.startswith("Ip Man") else RULES.get(q, [])
    found = [c["title"] for c in judged(ip3, resolve=blind) if c["accepted"]]
    assert found == ["《葉問3》 電影原聲帶"]
    # same title in both forms: no second search
    asked.clear()
    collect.screen_search(lambda q, limit=8: asked.append(q) or [], film("Jaws", 1975, [], original="Jaws"))
    assert asked == ["Jaws soundtrack"]


def test_rule8_chinese_wording_and_composer_aliases():
    ip3 = winner(film("Ip Man 3", 2015, ["Kenji Kawai"], original="葉問3", aliases=["川井憲次"]))
    assert ip3["title"] == "《葉問3》 電影原聲帶" and ip3["rule"].startswith("1") and not ip3["weak"]
    ip4 = winner(film("Ip Man 4: The Finale", 2019, ["Kenji Kawai"], original="葉問4", aliases=["川井憲次"]))
    assert ip4["title"] == "《葉問4: 完結篇》電影原聲大碟" and ip4["rule"].startswith("3")
    # without the alias the composer never fires and Ip Man 3 is three years out
    assert winner(film("Ip Man 3", 2015, ["Kenji Kawai"], original="葉問3")) is None


def test_rule8_cjk_aliases_match_with_or_without_spaces():
    # found by the live probe: TMDb's also_known_as spells Kenji Kawai as
    # "川井 憲次", while YouTube Music credits the albums to "川井憲次"
    assert collect._credited(["川井憲次"], ["Kenji Kawai", "川井 憲次"])
    assert not collect._credited(["川井憲次"], ["Kenji Kawai", "Kawai Kenji"])
    assert not collect._credited(["Hanszimmerman"], ["Hans Zimmer"])  # Latin names never joined
    for name, year, original, album, rule in (
            ("Ip Man 3", 2015, "葉問3", "《葉問3》 電影原聲帶", "1"),
            ("Ip Man 4: The Finale", 2019, "葉問4", "《葉問4: 完結篇》電影原聲大碟", "3")):
        w = winner(film(name, year, ["Kenji Kawai"], original=original,
                        aliases=["川井 憲次", "かわい けんじ", "Kawai Kenji"]))
        assert w and w["title"] == album and w["rule"].startswith(rule) and not w["weak"], name


def test_rule5_a_worded_album_wins_a_dead_heat_over_a_bare_one():
    # Fellowship: the Complete Recordings came first in search and tied the
    # soundtrack album on every approved key; the album that says it is a
    # soundtrack takes the tie, so a correct catalog row is not churned
    complete = _album("The Lord of the Rings: The Fellowship of the Ring - the Complete Recordings",
                      "Howard Shore", 2001, "lotr-cr")
    ost = _album("The Lord of the Rings: The Fellowship of the Ring (Original Motion Picture Soundtrack)",
                 "Howard Shore", 2001, "lotr-ost")
    w = collect.match_film([complete, ost], "The Lord of the Rings: The Fellowship of the Ring", 2001,
                           ["Howard Shore"])
    assert w["title"].endswith("(Original Motion Picture Soundtrack)")
    assert collect.normalize_screen(
        "Doctor Who - Series 7 (Original Television Soundtrack) [Deluxe Version]") == "doctor who"


# ---------------- TV vocabulary ----------------

def test_tv_books_and_network_series_wording():
    it = show("Infinity Train", [2019, 2020, 2021], ["Morgan Z Whirledge"])
    assert best(it)[("tv", it["id"], 1, None)]["title"] == "Infinity Train: Book 1 (Original Soundtrack)"
    sr = show("Scavengers Reign", [2023], ["Nicolas Snyder"])
    assert best(sr)[("tv", sr["id"], None, None)]["rule"].startswith("1")
    cse = show("Common Side Effects", [2025], ["Nicolas Snyder"])
    assert best(cse)[("tv", cse["id"], None, None)]["title"] == \
        "Common Side Effects (Adult Swim Original Series Soundtrack)"
    assert collect.normalize_screen("Stranger Things 4 (Original Series Soundtrack)") == "stranger things 4"
    assert collect.normalize_screen("Breaking Bad: Original Score from the Television Series") == "breaking bad"


# ---------------- no regression: knockoffs stay out ----------------

def test_knockoffs_stay_rejected_under_the_new_rules():
    cases = [
        (film("Star Wars: Episode I - The Phantom Menace", 1999, ["John Williams"]),
         "Star Wars Episode 1 - The Phantom Menace"),
        (film("Star Wars: Episode II - Attack of the Clones", 2002, ["John Williams"]),
         "8 Bit Star wars Episode II and III"),
        (film("The Empire Strikes Back", 1980, ["John Williams"]),
         "Music from Star Wars: The Phantom Menace, Star Wars"),
        (film("The Empire Strikes Back", 1980, ["John Williams"]), "Music from the Star Wars Saga"),
        (film("Blade Runner", 1982, ["Vangelis"]), "Blade Runner: Music From The Motion Picture"),
        (film("Blade Runner", 1982, ["Vangelis"]), "Blade Runner 2049 (Original Motion Picture Soundtrack)"),
        (film("Jurassic Park", 1993, ["John Williams"]), "Jurassic Park III"),
        (film("Jurassic Park", 1993, ["John Williams"]), "Jurassic Park Operation Genesis"),
        (show("Castlevania: Nocturne", [2023, 2025], ["Trevor Morris", "Trey Toy"]),
         "Castlevania Vdo Game Music Dark Lofi"),
        (film("Back to the Future", 1985, ["Alan Silvestri"]), "Back to The Future SoundTrack Beats"),
    ]
    for info, prefix in cases:
        c = verdict(info, prefix)
        assert not c["accepted"], (info["name"], c["title"], c["verdict"])


def test_weak_match_is_set_only_by_rule2_plays_and_rides_into_the_row():
    bundle = {"results": [
        {"id": 105, "title": "Back to the Future", "original_title": "Back to the Future",
         "release_date": "1985-07-03", "genre_ids": [], "poster_path": None},
        {"id": 329, "title": "Jurassic Park", "original_title": "Jurassic Park",
         "release_date": "1993-06-11", "genre_ids": [], "poster_path": None}],
        "genres": {}, "composers": {"105": [], "329": ["John Williams"]}, "aliases": {}}
    only = {"Back to the Future soundtrack": [r for r in RULES["Back to the Future soundtrack"]
                                              if r["title"] == "Back to the Future"],
            "Jurassic Park soundtrack": RULES["Jurassic Park soundtrack"]}
    loud = lambda bid: {"tracks": [{"title": "T", "views": "5M plays"}]}
    items = collect.parse_tmdb_film(json.dumps(bundle).encode(), lambda q, limit=8: only.get(q, []),
                                    album_fn=loud)
    by = {it["game"]: it for it in items}
    assert by["Back to the Future"].get("weakMatch") is True
    assert "weakMatch" not in by["Jurassic Park"]
    releases = []
    collect.merge(releases, items, src("tmdb-film", "catalog"), SEEN)
    assert [r.get("weakMatch") for r in releases] == [True, None]
