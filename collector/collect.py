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
    query = (f"fields name, slug, first_release_date, hypes, game_type, cover.image_id, platforms, "
             f"genres.name, involved_companies.company.name, involved_companies.developer; "
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


def ytm_resolve(query, limit=5):
    global _YT
    if _YT is None:
        from ytmusicapi import YTMusic  # lazy: only the resolver path needs it
        _YT = YTMusic()
    return _YT.search(query, filter="albums", limit=limit)


def ytm_album(browse_id):
    global _YT
    if _YT is None:
        from ytmusicapi import YTMusic
        _YT = YTMusic()
    return _YT.get_album(browse_id)


def ytm_playlist(playlist_id):
    global _YT
    if _YT is None:
        from ytmusicapi import YTMusic
        _YT = YTMusic()
    return _YT.get_playlist(playlist_id, limit=None)


TRACKS_CAP = 25


def _itunes_album_matches(collection_name, want_norm):
    """Track names are the goal, so any artist is fine (even covers), but the
    album must be this game's music: exact name, or the game's name inside a
    music-flavored title ("Pokémon Diamond & Pokémon Pearl: Super Music
    Collection" for the game "Pokémon Diamond Version")."""
    cand = _numfold(normalize_title(collection_name or ""))
    wants = {_numfold(want_norm)}
    if want_norm.endswith(" version"):
        wants.add(_numfold(want_norm[: -len(" version")].strip()))
    for w in wants:
        if not w or len(w) < 6:
            continue
        if cand == w:
            return True
        if w in cand and ("music" in cand or "soundtrack" in cand or "ost" in cand):
            return True
    return False


def deezer_tracks(query):
    resp = requests.get("https://api.deezer.com/search/album", timeout=30,
                        params={"q": query}, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    want = normalize_title(query)
    for album in resp.json().get("data", [])[:5]:
        if not _itunes_album_matches(album.get("title"), want):
            continue
        tr = requests.get(f"https://api.deezer.com/album/{album['id']}/tracks", timeout=30,
                          params={"limit": 100}, headers={"User-Agent": USER_AGENT})
        tr.raise_for_status()
        tracks = [{"title": t["title"], "plays": None}
                  for t in tr.json().get("data", []) if t.get("title")]
        if tracks:
            return tracks
    return None


def musicbrainz_tracks(query):
    """MusicBrainz catalogs the Japanese CD releases of console-era albums
    that no streaming service carries. Polite: ~1 request/second."""
    def mb(path, **params):
        time.sleep(1.1)
        resp = requests.get(f"https://musicbrainz.org/ws/2/{path}", timeout=30,
                            params={**params, "fmt": "json"},
                            headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
        return resp.json()

    want = normalize_title(query)
    groups = mb("release-group", query=query, limit=5).get("release-groups", [])
    for rg in groups:
        if not _itunes_album_matches(rg.get("title"), want):
            continue
        releases = mb("release", **{"release-group": rg["id"], "limit": 1}).get("releases", [])
        if not releases:
            continue
        detail = mb(f"release/{releases[0]['id']}", inc="recordings")
        tracks = [{"title": t["title"], "plays": None}
                  for m in detail.get("media", []) for t in m.get("tracks", [])
                  if t.get("title")]
        if tracks:
            return tracks
    return None


def catalog_tracks(query):
    """Tracklist fallbacks in coverage order: Apple, Deezer, MusicBrainz."""
    for fn in (itunes_tracks, deezer_tracks, musicbrainz_tracks):
        try:
            got = fn(query)
        except Exception:
            continue
        if got:
            return got
    return None


def itunes_tracks(query):
    """Full tracklist from Apple's free search API — the fallback for albums
    YTM doesn't carry (Nintendo, the Pokémon Super Music Collections)."""
    resp = requests.get("https://itunes.apple.com/search", timeout=30,
                        params={"term": query, "entity": "album", "limit": 5},
                        headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    want = normalize_title(query)
    for album in resp.json().get("results", []):
        if not _itunes_album_matches(album.get("collectionName"), want):
            continue
        lk = requests.get("https://itunes.apple.com/lookup", timeout=30,
                          params={"id": album.get("collectionId"), "entity": "song"},
                          headers={"User-Agent": USER_AGENT})
        lk.raise_for_status()
        songs = [x for x in lk.json().get("results", []) if x.get("wrapperType") == "track"]
        songs.sort(key=lambda x: ((x.get("discNumber") or 1), (x.get("trackNumber") or 0)))
        tracks = [{"title": x["trackName"], "plays": None} for x in songs if x.get("trackName")]
        if tracks:
            return tracks
    return None


def _plays_num(text):
    m = re.match(r"([\d.,]+)\s*([KMB])?", str(text or "").strip(), re.IGNORECASE)
    if not m:
        return None
    try:
        n = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return n * {"K": 1e3, "M": 1e6, "B": 1e9}.get((m.group(2) or "").upper(), 1)


def ytm_tracks_from(album):
    out = []
    for t in (album or {}).get("tracks", []):
        if not t.get("title"):
            continue
        vid = t.get("videoId") or None
        vtype = t.get("videoType") or ""
        if vid and vtype and not vtype.endswith("ATV"):
            vid = None  # video edition: linking it opens Video mode, not the song
        out.append({"title": t["title"], "plays": t.get("views") or None, "videoId": vid})
    return out


def _patch_audio_ids(tracks, playlist):
    """Album pages link video editions (OMV) for some tracks — Volume Alpha
    carries 13 — and those ids get dropped. The album's audio playlist lists
    the audio id at every position, so nulls are patched from there."""
    pl = [t for t in (playlist or {}).get("tracks", []) if t.get("title")]
    if not pl:
        return
    by_title = {}
    for t in pl:
        by_title.setdefault(normalize_title(t["title"]), t.get("videoId"))
    aligned = len(pl) == len(tracks)
    for i, t in enumerate(tracks):
        if t["videoId"]:
            continue
        vid = (pl[i].get("videoId") if aligned else None) \
            or by_title.get(normalize_title(t["title"]))
        if vid:
            t["videoId"] = vid


def fill_tracks(releases, album_fn, itunes_fn, cap=TRACKS_CAP, playlist_fn=ytm_playlist):
    """Full tracklists, capped per run: YTM albums carry plays + per-track
    videoIds; game-named rows without a YTM album fall back to Apple's
    catalog. [] is a completed check, and legacy topTracks is retired."""
    looked = 0
    for r in releases:
        if "tracks" in r:
            continue
        if looked >= cap:
            break
        url = r.get("ytmAlbumUrl") or ""
        if "/browse/" in url:
            looked += 1
            try:
                album = album_fn(url.rsplit("/", 1)[1])
            except Exception:
                continue  # transient: retry on a later run
            r["tracks"] = ytm_tracks_from(album)
            plid = (album or {}).get("audioPlaylistId")
            if plid:
                r["ytmPlaylistId"] = plid  # &list= makes track links open the song, not the video
                if playlist_fn and any(not t["videoId"] for t in r["tracks"]):
                    try:
                        _patch_audio_ids(r["tracks"], playlist_fn(plid))
                    except Exception:
                        pass  # patch is best-effort: links fall back to search
        elif r.get("game"):
            looked += 1
            try:
                got = itunes_fn(_query(r["game"]))
            except Exception:
                continue
            r["tracks"] = got or []
        else:
            continue  # headline rows with no game name: nothing to look up
        r.pop("topTracks", None)
    return looked


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


# editorial headlines carry the album name wrapped in news prose; these cuts
# recover a display label ("Atomic Owl vinyl reissue is now available from
# Ghost Mutt Records" -> "Atomic Owl"). Display-only: identity and dedupe
# always use the raw title.
_LEAD_CUTS = (" announces ", " reveals ", " to reissue ", " ready with preorders for ",
              " ready with ")
_TRAIL_CUTS = (" is now ", " is already ", " is out", " is finally", " has arrived",
               " have arrived", " finally hits", " hits ", " arrives", " debuts",
               " lands ", " drops ", " up for preorder", " now up for",
               " is now available", " available now", " out now", " via ",
               " on vinyl", " to vinyl", " teases ", " vinyl reissue", " 3lp", " 2lp")
_LEAD_ARTICLES = re.compile(r"^(?:the|a|an)\s+", re.IGNORECASE)


def headline_album(title):
    t = " ".join(title.split())
    low = t.lower()
    for cut in _LEAD_CUTS:
        i = low.find(cut)
        if i != -1:
            t = t[i + len(cut):]
            low = t.lower()
            break
    best = len(t)
    for cut in _TRAIL_CUTS:
        i = low.find(cut)
        if 0 < i < best:
            best = i
    t = t[:best].strip(" ,;:–—-")
    if " : " in t:  # spaced colon = editorial lead-in; "Title: Subtitle" albums use ": "
        head, _, tail = t.partition(" : ")
        if _SOUNDTRACKY.search(tail) and not _SOUNDTRACKY.search(head):
            t = tail.strip()
    t = _LEAD_ARTICLES.sub("", t).strip()
    return t if len(t) >= 4 and t.lower() != title.strip().lower() else None


def _headline_items(raw, keep):
    items = _feed(raw, keep)
    for it in items:
        alt = headline_album(it["title"])
        if alt:
            it["albumTitle"] = alt
    return items


def parse_nowplaying(raw, resolve=None):
    return _headline_items(raw, {"OST", "Vinyl"})


def parse_blipblop(raw, resolve=None):
    return _headline_items(raw, {"Confirmed Release"})


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


# "«Game» Original/Official/etc Soundtrack" -> the game's display name
_GAME_SUFFIX = re.compile(
    r"\s*[-–—:]?\s*\(?\s*(?:(?:original|official|digital|complete|deluxe|additional|bonus)\s+)*"
    r"(?:(?:game|video\s*game)\s+)?(?:soundtrack|sound\s*track|ost|score)\s*\)?\s*$",
    re.IGNORECASE)


def _steam_game(title):
    game = _GAME_SUFFIX.sub("", title).strip(" -–—:")
    return game if game and game != title.strip() else None


def _steam_art(row_html):
    # swap the search capsule filename for the full-size header on the same CDN path
    m = re.search(r'<img[^>]*\ssrc="([^"]+)"', row_html)
    return re.sub(r"/[^/?]+(\?.*)?$", "/header.jpg", m.group(1)) if m else None


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
        items.append({"title": title, "url": m.group(1).split("?")[0], "date": date,
                      "game": _steam_game(title), "art": _steam_art(m.group(0))})
    if not items:
        raise RuntimeError("steam rows parsed to zero items")
    return items


def _query(title):
    return title if "soundtrack" in title.lower() else f"{title} soundtrack"


_SOUNDTRACKY = re.compile(r"\b(soundtrack|ost|score|original sound|music (from|of))\b", re.IGNORECASE)

_ROMAN_TOKENS = {"ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8,
                 "ix": 9, "x": 10, "xi": 11, "xii": 12, "xiii": 13, "xiv": 14,
                 "xv": 15, "xvi": 16}  # not "i": too often the English word


def _numfold(norm):
    """Assassin's Creed II and Assassin's Creed 2 are the same name, and so
    are PERSONA5 and Persona 5: letter-digit boundaries split, romans fold."""
    norm = re.sub(r"(?<=[a-z])(?=[0-9])", " ", norm)
    norm = re.sub(r"(?<=[0-9])(?=[a-z])", " ", norm)
    return " ".join(str(_ROMAN_TOKENS[t]) if t in _ROMAN_TOKENS else t for t in norm.split())


# serial tribute acts: real artist names that are never the game's composer
_COVERS_ARTISTS = {"london music works", "city of prague philharmonic orchestra",
                   "vitamin string quartet", "geek music", "l'orchestra cinematique",
                   "rmaster", "video game players", "8-bit arcade", "piano tribute players",
                   "the marcus hedges trend orchestra", "magnus deus", "sheet music boss"}

# publisher wording that marks an album as the official release
_OFFICIAL_WORDING = re.compile(
    r"\bsoundtracks?\b|\boriginal\s+(game\s+)?(music|score|sound)|\bthe score\b",
    re.IGNORECASE)


def _hit_from(r):
    n = normalize_title(r.get("title", ""))
    title = r.get("title", "")
    artists = [a["name"] for a in r.get("artists", []) if a.get("name")]
    if any(a.lower() in _COVERS_ARTISTS for a in artists):
        return None
    # movie-tie-in games share names with movie soundtracks (Shrek 2), and
    # the era guard can't tell them apart — a movie/film/stage album only
    # counts when the title itself says it's for the game (The LEGO Movie
    # Videogame). "Theatrical" caught a stage production wearing a game's
    # name (Synapse).
    if re.search(r"\b(motion picture|movie|film|theatrical|broadway|musical)\b",
                 title, re.IGNORECASE) \
            and not re.search(r"\b(video ?game|game)\b", title, re.IGNORECASE):
        return None
    composers = [a for a in artists
                 if a.lower() != "various artists" and normalize_title(a) != n]
    if not composers:
        if not any(a.lower() == "various artists" for a in artists):
            # the only credit is the album's own name. Publishers do run the
            # artist page under the game's name ("Horizon Forbidden West"),
            # so official soundtrack wording on a distinctive multi-word name
            # vouches for it; single-word self-credits ("Lifted" by Lifted)
            # collide with band namespaces and stay too ambiguous
            if len(n.split()) < 2 or not _OFFICIAL_WORDING.search(title) \
                    or _GAAS_BLACKLIST.search(title):
                return None
        # "Various Artists" is licensed-compilation convention (Hi-Fi Rush,
        # sports titles, "The Music of GTA V") — but fan tributes hide behind
        # it too ("Music from The Legend of Zelda"), so a VA-only credit must
        # carry official wording and dodge the tribute vocabulary
        elif not _OFFICIAL_WORDING.search(title) or _GAAS_BLACKLIST.search(title):
            return None
    thumbs = sorted((t for t in r.get("thumbnails", []) if t.get("url")),
                    key=lambda t: t.get("width") or 0)
    return {"title": r["title"], "composers": composers,
            "art": thumbs[-1]["url"] if thumbs else None,
            "url": "https://music.youtube.com/browse/" + r["browseId"]}


def _match_album(results, want_norm, year=None):
    """Strict: the album title must normalize to exactly the wanted name, must
    say it's a soundtrack, and must have a credited artist besides the game.
    With a year anchor, the album must sit within 2 years of it — franchises
    reuse titles (Tomb Raider 1996 vs 2013), and the reboot's album must not
    attach to the original game."""
    for r in results or []:
        if r.get("resultType") != "album" or not r.get("browseId"):
            continue
        if _numfold(normalize_title(r.get("title", ""))) != _numfold(want_norm):
            continue
        if not _SOUNDTRACKY.search(r.get("title", "")):
            continue
        if year is not None and _numeral_tail(want_norm) is None:
            # bare franchise names (Tomb Raider, DOOM) can belong to several
            # eras, so the album year must sit near the game. Numbered names
            # are unambiguous — publishers upload classics decades late
            # (the whole Civilization discography arrived in 2025).
            try:
                if r.get("year") and abs(int(r["year"]) - year) > 2:
                    continue
            except (TypeError, ValueError):
                pass  # unparseable year: don't punish the album for bad metadata
        hit = _hit_from(r)
        if hit:
            return hit
    return None


# bookkeeping words an album title may add without changing which music it is
_TOKENS_OK = {"the", "a", "an", "and", "of", "vol", "volume", "original", "official",
              "video", "videogame", "game", "soundtrack", "ost", "score", "music",
              "from", "complete", "deluxe", "edition", "remastered", "remaster",
              "inspired", "by", "alpha", "beta"}  # seed-vouched; alpha/beta are volume names (Minecraft)


def _match_album_tokens(results, game_name, year=None):
    """Seed-vouched relaxation: the album's content words must equal the
    game's content words — "Sly Cooper Vol. I: The Thievius Raccoonus
    (Original Videogame Soundtrack)" passes for Sly Cooper and the Thievius
    Raccoonus, while "Spyro Remixed" or "Pac-Man Fever" introduce foreign
    words and stay rejected."""
    def content(norm):
        folded = re.sub(r"\b(vol|volume)\s+\d+\b", " ", _numfold(norm))  # volume numbers aren't identity
        return {t for t in folded.split()
                if t not in _TOKENS_OK and t != "i"}  # game numerals stay: HM 2 is not HM
    wants = [content(normalize_title(game_name))]
    if ":" in game_name:  # subtitles drop off album titles constantly
        head = content(normalize_title(game_name.split(":", 1)[0]))
        if head and head not in wants:
            wants.append(head)
    if not wants[0]:
        return None
    bare_name = _numeral_tail(normalize_title(game_name)) is None
    best = best_key = None
    for r in results or []:
        if r.get("resultType") != "album" or not r.get("browseId"):
            continue
        if not _SOUNDTRACKY.search(r.get("title", "")):
            continue
        cand = content(normalize_title(r.get("title", "")))
        if cand not in wants:
            continue
        if year is not None and bare_name:
            # same era rule as the strict tier: bare franchise names span
            # reboots (Tomb Raider 1996/2013), so a dated album must sit
            # near the game
            try:
                if r.get("year") and abs(int(r["year"]) - year) > 2:
                    continue
            except (TypeError, ValueError):
                pass
        hit = _hit_from(r)
        if not hit:
            continue
        # volume numbers are bookkeeping for matching, but not for choosing:
        # prefer the un-volumed album, then the lowest volume, over whatever
        # search happened to rank first (Sims 4 once drew Vol. 2)
        m = re.search(r"\b(?:vol|volume)\.?\s*(\d+)", r.get("title", ""), re.IGNORECASE)
        key = (1, int(m.group(1))) if m else (0, 0)
        if best is None or key < best_key:
            best, best_key = hit, key
    return best


def _match_album_contains(results, game_name, year=None):
    """Seed-vouched containment: the album title carries the full game name
    plus soundtrack wording ("Portal 2: Songs to Test By (Original Game
    Soundtrack)"), with the live-service blacklist applied."""
    want = {t for t in _numfold(normalize_title(game_name)).split()
            if t not in _TOKENS_OK and t != "i"}
    if not want:
        return None
    bare_name = _numeral_tail(normalize_title(game_name)) is None
    for r in results or []:
        if r.get("resultType") != "album" or not r.get("browseId"):
            continue
        title = r.get("title", "")
        if _GAAS_BLACKLIST.search(title) or not _SOUNDTRACKY.search(title):
            continue
        cand = {t for t in _numfold(normalize_title(title)).split()
                if t not in _TOKENS_OK and t != "i"}
        if not want.issubset(cand):
            continue
        if year is not None and bare_name:
            try:
                if r.get("year") and abs(int(r["year"]) - year) > 2:
                    continue
            except (TypeError, ValueError):
                pass
        hit = _hit_from(r)
        if hit:
            return hit
    return None


def _match_album_purename(results, want_norm, year):
    """Some official albums carry no soundtrack wording at all — Jesper Kyd's
    "Hitman: Blood Money" is just the game's name. Accept the exact name when
    a real composer is credited AND the album year sits on the game's era;
    the year anchor is mandatory, because a same-name band album with no year
    proximity is exactly the ZeroSpace/Kidneythieves trap."""
    if year is None:
        return None
    for r in results or []:
        if r.get("resultType") != "album" or not r.get("browseId"):
            continue
        if _numfold(normalize_title(r.get("title", ""))) != _numfold(want_norm):
            continue
        if _GAAS_BLACKLIST.search(r.get("title", "")):
            continue
        try:
            if not r.get("year") or abs(int(r["year"]) - year) > 2:
                continue
        except (TypeError, ValueError):
            continue
        hit = _hit_from(r)
        if hit and hit["composers"]:  # named composer only: VA or self-credit stays out
            return hit
    return None


def _match_album_within(results, hay_norm):
    """Containment: an editorial headline carries the album's name inside it
    ("Atomic Owl vinyl reissue is now available…" ⊇ "Atomic Owl (OST)").
    Multi-word names only — single words match far too much."""
    for r in results or []:
        if r.get("resultType") != "album" or not r.get("browseId"):
            continue
        if not _SOUNDTRACKY.search(r.get("title", "")):
            continue
        n = normalize_title(r.get("title", ""))
        if len(n) < 6 or " " not in n or _numfold(n) not in _numfold(hay_norm):
            continue
        hit = _hit_from(r)
        if hit:
            return hit
    return None


def company_of(game):
    companies = game.get("involved_companies") or []
    devs = [c for c in companies if c.get("developer")] or companies
    name = ((devs[0].get("company") or {}).get("name") or "").strip() if devs else ""
    return name or None


# IGDB platform ids that are NOT consoles; anything else (PlayStation, Xbox,
# Nintendo, handhelds, and any future id) counts as a console release
_NONCONSOLE_PLATFORMS = {3, 6, 13, 14, 34, 39, 82, 163}  # Linux, PC, DOS, Mac, Android, iOS, web, SteamVR


def is_console(game):
    platforms = game.get("platforms") or []
    if not platforms:
        return None  # unknown, not "PC-only"
    return any(p not in _NONCONSOLE_PLATFORMS for p in platforms)


def genres_of(game):
    names = [(g.get("name") or "").strip() for g in game.get("genres") or []]
    return [n for n in names if n][:3] or None


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
        when = datetime.fromtimestamp(stamp, tz=timezone.utc)
        try:
            hit = _match_album(resolve(_query(name)), normalize_title(name), year=when.year)
        except Exception:
            errors += 1
            continue
        if not hit:
            continue  # released game, but no confidently-matching album on YTM
        cover = (g.get("cover") or {}).get("image_id")
        items.append({
            "title": f"{name} Soundtrack", "albumTitle": hit["title"],
            "game": name, "composers": hit["composers"],
            "company": company_of(g), "console": is_console(g), "genres": genres_of(g),
            "url": f"https://www.igdb.com/games/{g.get('slug') or g.get('id')}",
            "date": when.strftime("%Y-%m-%d"),
            "ytmAlbumUrl": hit["url"],
            "art": hit["art"] or (f"https://images.igdb.com/igdb/image/upload/t_cover_big/{cover}.jpg" if cover else None)})
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
    "original video game soundtrack",
    "original videogame soundtrack",
    "music from the video game",
    "original game soundtrack",
    "video game soundtrack",
    "videogame soundtrack",
    "music from the game",
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
    parts = [title]
    if game and _numfold(normalize_title(game)) not in _numfold(normalize_title(title)):
        parts.append(game)  # only when the title doesn't already name the game
    if not any(_SOUNDTRACKY.search(p) for p in parts):
        parts.append("soundtrack")
    q = " ".join(p for p in parts if p)
    return "https://music.youtube.com/search?q=" + quote_plus(re.sub(r"\s+", " ", q).strip())


_ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7,
          "viii": 8, "ix": 9, "x": 10, "xi": 11, "xii": 12, "xiii": 13,
          "xiv": 14, "xv": 15, "xvi": 16}


def _numeral_tail(norm):
    tail = norm.rsplit(" ", 1)[-1] if " " in norm else ""
    if tail.isdigit() and len(tail) <= 2:
        return int(tail)
    return _ROMAN.get(tail)


def _fuzzy_find(norm, releases, norms):
    best, best_ratio = None, 0.0
    tail = _numeral_tail(norm)
    for r in releases:
        other = norms[id(r)]
        if _numeral_tail(other) != tail:
            continue  # Mass Effect 2 and 3 are near-identical strings and different albums
        m = SequenceMatcher(None, norm, other)
        if m.real_quick_ratio() < FUZZY_THRESHOLD or m.quick_ratio() < FUZZY_THRESHOLD:
            continue
        ratio = m.ratio()
        if ratio > best_ratio:
            best, best_ratio = r, ratio
    return best if best_ratio >= FUZZY_THRESHOLD else None


def _far_apart(a, b):
    try:
        return abs(int(str(a)[:4]) - int(str(b)[:4])) > 3
    except (TypeError, ValueError):
        return False


def merge(releases, items, source, seen_at):
    """Fold one source's items in. Append-only: existing entries only ever gain
    a source, an earlier date, or a fill for a still-null enrichment field;
    id and title never change."""
    by_id = {r["id"]: r for r in releases}
    norms = {id(r): normalize_title(r["title"]) for r in releases}
    by_numfold = {}
    for r in releases:
        by_numfold.setdefault(_numfold(norms[id(r)]), r)
    added = merged = 0
    for it in items:
        if not it["title"] or not it["url"]:
            continue
        slug = slugify(it["title"])
        norm = normalize_title(it["title"])
        # numeral variants (II vs 2) are the same name exactly — never left to fuzzy odds
        target = by_id.get(slug) or by_numfold.get(_numfold(norm)) or _fuzzy_find(norm, releases, norms)
        if target is not None and it["date"] and target.get("date") and _far_apart(it["date"], target["date"]):
            # same name, different era: Tomb Raider 1996 is not Tomb Raider 2013.
            # The newcomer gets a year-suffixed id; reruns find it there again.
            slug = f"{slug}-{it['date'][:4]}"
            target = by_id.get(slug)
            if target is not None and target.get("date") and _far_apart(it["date"], target["date"]):
                target = None
        src = {"name": source["name"], "type": source["type"],
               "url": it["url"], "seenAt": seen_at}
        if target is not None:
            if not any(s["url"] == it["url"] for s in target["sources"]):
                target["sources"].append(src)
                merged += 1
            if it["date"] and (not target["date"] or it["date"] < target["date"]):
                target["date"] = it["date"]
            if not target.get("albumTitle") and it.get("albumTitle"):
                target["albumTitle"] = it["albumTitle"]
            if not target.get("company") and it.get("company"):
                target["company"] = it["company"]
            if target.get("console") is None and it.get("console") is not None:
                target["console"] = it["console"]
            if not target.get("genres") and it.get("genres"):
                target["genres"] = list(it["genres"])
            if not target.get("game") and it.get("game"):
                target["game"] = it["game"]
            if not target.get("composers") and it.get("composers"):
                target["composers"] = list(it["composers"])
            if not target.get("ytmAlbumUrl") and it.get("ytmAlbumUrl"):
                target["ytmAlbumUrl"] = it["ytmAlbumUrl"]
                target.pop("tracks", None)  # a real album arrived: refresh the tracklist with plays
                target.pop("ytmPlaylistId", None)
            if not target.get("art") and it.get("art"):
                target["art"] = it["art"]
        else:
            entry = {"id": slug, "title": it["title"], "game": it.get("game"),
                     "composers": list(it.get("composers") or []),
                     "date": it["date"], "sources": [src],
                     "ytmSearchUrl": ytm_search_url(it["title"], it.get("game")),
                     "ytmAlbumUrl": it.get("ytmAlbumUrl"), "art": it.get("art"), "notable": True}
            if it.get("albumTitle"):
                entry["albumTitle"] = it["albumTitle"]
            if it.get("company"):
                entry["company"] = it["company"]
            if it.get("console") is not None:
                entry["console"] = it["console"]
            if it.get("genres"):
                entry["genres"] = list(it["genres"])
            releases.append(entry)
            by_id[slug] = entry
            norms[id(entry)] = normalize_title(entry["title"])
            by_numfold.setdefault(_numfold(norms[id(entry)]), entry)
            added += 1
    return added, merged


def resolve_albums(releases, resolve, now, cap=RESOLVE_CAP):
    """Fill ytmAlbumUrl for recent rows that lack one, with the same strict
    matcher. Bounded per run; unresolved rows retry until they age out."""
    cutoff = (now - timedelta(days=RESOLVE_WINDOW_DAYS)).strftime("%Y-%m-%d")
    claimed = {u for u in (x.get("ytmAlbumUrl") for x in releases) if u}
    looked = filled = 0
    for r in releases:
        if not r.get("date") or r["date"] < cutoff:
            continue
        if r.get("ytmAlbumUrl") and r.get("art"):
            continue
        if looked >= cap:
            break
        looked += 1
        norm = normalize_title(r["title"])
        year = None
        try:
            year = int(r["date"][:4])
        except (TypeError, ValueError):
            pass
        try:
            results = resolve(_query(r["title"]))
        except Exception:
            continue
        hit = _match_album(results, norm, year=year) or _match_album_within(results, norm)
        if not hit:
            continue
        if not r.get("ytmAlbumUrl"):
            if hit["url"] in claimed:
                continue  # one album, one row: never let a second row wear it
            claimed.add(hit["url"])
            r["ytmAlbumUrl"] = hit["url"]
            r.pop("tracks", None)  # refresh with the album's own tracklist
            r.pop("ytmPlaylistId", None)
            filled += 1
        if normalize_title(hit["title"]) != norm:
            r["albumTitle"] = hit["title"]  # YTM's canonical name overrides any headline-derived label
        if not r.get("art") and hit["art"]:
            r["art"] = hit["art"]
        if not r.get("composers") and hit["composers"]:
            r["composers"] = hit["composers"]
    return looked, filled


# tribute wording that disqualifies an album from a live-service scan
_GAAS_BLACKLIST = re.compile(
    r"\b(covers?|tribute|remix(es)?|medley|lullab|lo-?fi|8-?bit|chill"
    r"|movie|motion picture|film|bonus songs|roblox)\b", re.IGNORECASE)


def gaas_names(path=None):
    try:
        d = json.loads(Path(path or ROOT / "collector" / "seeds.json").read_text(encoding="utf-8"))
        return [s for s in d.get("multiAlbum", []) if isinstance(s, str) and s]
    except (OSError, ValueError):
        return []


def gaas_albums(releases, resolve, seen_at, names=None):
    """Live-service games release album after album: one row per qualifying
    album, so each season's soundtrack stands alone and reruns pick up new
    ones automatically."""
    names = gaas_names() if names is None else names
    # an album already worn by some other row (a plain game row, usually a
    # spin-off like Rocket League Sideswipe) must not spawn a twin album row
    claimed = {}
    for x in releases:
        if x.get("ytmAlbumUrl"):
            claimed[x["ytmAlbumUrl"]] = x["id"]
    added = merged = 0
    for name in names:
        try:
            results = resolve(_query(name), limit=25)
        except TypeError:
            results = resolve(_query(name))
        except Exception:
            continue
        want = {t for t in _numfold(normalize_title(name)).split()
                if t not in _TOKENS_OK and t != "i"}
        items = []
        for r in results or []:
            if r.get("resultType") != "album" or not r.get("browseId"):
                continue
            title = r.get("title", "")
            if _GAAS_BLACKLIST.search(title):
                continue
            cand = {t for t in _numfold(normalize_title(title)).split()
                    if t not in _TOKENS_OK and t != "i"}
            if not want or not want.issubset(cand):
                continue  # the album must name the game
            if not _SOUNDTRACKY.search(title) and cand != want:
                continue  # soundtrack wording, or a pure-name album (Minecraft - Volume Alpha)
            hit = _hit_from(r)
            if not hit:
                continue
            if not hit["composers"] and not re.search(r"original .*soundtrack", title, re.IGNORECASE):
                continue  # VA with vague naming: fan-compilation territory
            owner = claimed.get(hit["url"])
            if owner and owner != slugify(hit["title"]):
                continue  # another row already wears this album
            year = str(r.get("year") or "")
            items.append({"title": hit["title"], "game": name, "composers": hit["composers"],
                          "url": hit["url"], "date": f"{year}-01-01" if year.isdigit() else None,
                          "ytmAlbumUrl": hit["url"], "art": hit["art"]})
        a, m = merge(releases, items, {"name": "ytm", "type": "catalog"}, seen_at)
        added += a
        merged += m
    return added, merged


def load_data(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("releases"), list):
            return data
    except (OSError, ValueError):
        pass
    return {"updatedAt": None, "releases": []}


def run(fetch_fn=fetch_any, resolve_fn=ytm_resolve, album_fn=ytm_album,
        itunes_fn=catalog_tracks, data_path=DATA_PATH, now=None):
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
    ga, gm = gaas_albums(releases, resolve_fn, seen_at)
    print(f"live-service albums: {ga} new, {gm} merged")
    fetched = fill_tracks(releases, album_fn, itunes_fn, cap=TRACKS_CAP)
    print(f"tracklists: {fetched} looked up")

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
