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
import unicodedata
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
    if url == IGDB_URL:
        return igdb_fetch()
    if url == "tmdb:film":
        return tmdb_film_fetch()
    if url == "tmdb:tv":
        return tmdb_tv_fetch()
    return fetch_feed(url)


_YT = None


def _ytm():
    global _YT
    if _YT is None:
        from ytmusicapi import YTMusic  # lazy: only the resolver path needs it
        _YT = YTMusic()
    return _YT


def _ytm_call(fn):
    """YTM rate-limits bursts by serving non-JSON, which ytmusicapi raises as
    JSONDecodeError; one bounded backoff usually clears it. Anything that
    survives the retries propagates — callers already treat errors as
    transient and try again next run."""
    import json as _json
    for wait in (15, 45):
        try:
            return fn()
        except _json.JSONDecodeError:
            time.sleep(wait)
    return fn()


def ytm_resolve(query, limit=5):
    return _ytm_call(lambda: _ytm().search(query, filter="albums", limit=limit))


def ytm_album(browse_id):
    return _ytm_call(lambda: _ytm().get_album(browse_id))


def ytm_playlist(playlist_id):
    return _ytm_call(lambda: _ytm().get_playlist(playlist_id, limit=None))


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


def _plays_total(tracks):
    total, seen = 0.0, False
    for t in tracks:
        n = _plays_num(t.get("plays"))
        if n is not None:
            total, seen = total + n, True
    return int(total) if seen else None


def write_tracklist(r, tracks, tracks_dir):
    """The split convention in one place: the list lives in
    data/tracks/<id>.json, the row carries tracksN (0 marks a completed
    empty check, no file) and playsTotal when any track has plays."""
    r["tracksN"] = len(tracks)
    total = _plays_total(tracks)
    if total is not None:
        r["playsTotal"] = total
    else:
        r.pop("playsTotal", None)
    path = Path(tracks_dir) / f"{r['id']}.json"
    if tracks:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(tracks, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    elif path.exists():
        path.unlink()  # a reset check must not leave a stale list behind
    return r


def fill_tracks(releases, album_fn, itunes_fn, cap=TRACKS_CAP, playlist_fn=ytm_playlist,
                tracks_dir=None):
    """Full tracklists, capped per run: YTM albums carry plays + per-track
    videoIds; game-named rows without a YTM album fall back to Apple's
    catalog. Lists land in per-release files via write_tracklist; tracksN
    is the completed-check marker, and legacy topTracks is retired."""
    tracks_dir = Path(tracks_dir) if tracks_dir else DATA_PATH.parent / "tracks"
    looked = 0
    for r in releases:
        if "tracksN" in r or "tracks" in r:
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
            tracks = ytm_tracks_from(album)
            plid = (album or {}).get("audioPlaylistId")
            if plid:
                r["ytmPlaylistId"] = plid  # &list= makes track links open the song, not the video
                if playlist_fn and any(not t["videoId"] for t in tracks):
                    try:
                        _patch_audio_ids(tracks, playlist_fn(plid))
                    except Exception:
                        pass  # patch is best-effort: links fall back to search
            write_tracklist(r, tracks, tracks_dir)
        elif r.get("game"):
            looked += 1
            try:
                got = itunes_fn(_query(r["game"]))
            except Exception:
                continue
            write_tracklist(r, got or [], tracks_dir)
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
    if ":" in game_name:
        # subtitles drop off album titles ("Hotline Miami 2 (Official
        # Soundtrack)" for Wrong Number) — but only a NUMBERED head names one
        # game. A bare franchise head is media-brand territory: "Naruto
        # Shippuden: Ultimate Ninja 4" must not wear the anime's TV score,
        # which is the same era and has no owner row to claim it first.
        head_norm = normalize_title(game_name.split(":", 1)[0])
        head = content(head_norm)
        if head and head not in wants and _numeral_tail(head_norm) is not None:
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


# ---------------- film and TV (FILM-TV-SPEC Phase B, MATCHER-FIX-SPEC) ----------------
# The screen matcher is its own lane, separate from the game rules. Every
# YouTube Music album is judged against a TMDb title, then resolve_screen
# hands albums out across all the titles in a batch at once, one album to
# one row. Rules, numbered as in MATCHER-FIX-SPEC.md:
#   1 exact title with soundtrack wording: composer credited, or the album
#     year within the window. The year guard stays because without it a
#     re-recording ("Music from Rogue One: A Star Wars Story", 2022) passes.
#   2 exact title with no wording at all: composer credited, or enough
#     plays, and in both cases the year within the window (the window keeps
#     The Last of Us show off the 2013 game album). Only the plays path sets
#     weakMatch.
#   3 the title inside a longer album name (franchise prefix or suffix):
#     soundtrack wording, composer credited, year within the window.
#   4 a TMDb title longer than the album only by an episode marker: the
#     same conditions as 3.
#   5 ranking: credited first, then exact over extended, then fewer extra
#     words, then the closer year.
#   6 an album goes to the title that matches it best, exact claims before
#     tolerant ones, whatever order the titles arrive in.
#   7 Pt and Vol read as Part and Volume before the sequel guard.
#   8 a second search on TMDb's original title, soundtrack wording in
#     Chinese and Japanese, and composer names in any script.
# For TV the year window is measured against every season's air year, so a
# later season is never an era miss.

TMDB_FILM_WINDOW_DAYS = 14
TMDB_FILM_VOTES = 5
TMDB_TV_WINDOW_DAYS = 60   # season scores trail the premiere by weeks
TMDB_TV_VOTES = 10
TMDB_PAGES = 2             # discover pages per daily run, 20 titles each
SCREEN_YEAR_WINDOW = 2
WEAK_PLAYS_MIN = 100_000   # rule 2 without a composer: total plays on the album

# suffix remnants left after normalize_title has eaten its own suffixes
# ("Original Motion Picture Soundtrack" loses only the trailing word), plus
# edition and series wording, catalogued from live YTM album titles
_SCREEN_TAILS = (
    "music from the original motion picture",
    "soundtrack from the motion picture",
    "music from the motion picture",
    "original motion picture score",
    "original motion picture",
    "music from the original",
    "original score from the television series",
    "original television series",
    "original television",
    "music from the original tv series",
    "music from the original series",
    "music from the tv series",
    "soundtrack from the tv series",
    "music from the hbo original series",
    "music from the hbo series",
    "hbo original series",
    "soundtrack from the hbo original series",
    "music from the limited event series",
    "limited event series",
    "soundtrack from the netflix original series",
    "a netflix original series",
    "netflix original series",
    "soundtrack from the animated series",
    "music from the series",
    "music from the netflix original series",
    "the complete recordings",
    "expanded edition",
    "deluxe edition",
    "deluxe version",
    "special edition",
    "collector s anniversary edition",
    "anniversary edition",
    "remastered",
    "the album",
    "u s version",
    "music from the",        # "(Music From The Original Soundtrack)" after its suffix drops
    "soundtrack from the",
    "score from the",
    "music from",
    "soundtrack from",
    "score from",
    "selections from the",   # "(Selections from the Original Motion Picture Soundtrack)"
    "highlights from the",
    "excerpts from the",
    "the",                   # "(The Original Soundtrack)" leaves its article stranded
)
_SCREEN_HEADS = ("soundtrack from the ", "soundtrack from ", "music from the ", "music from ")

# streaming-era series wording, network agnostic: "(Original Max Series
# Soundtrack)", "(Adult Swim Original Series Soundtrack)", "(Soundtrack
# from the Apple Original Film)". Network words are a closed list, so a
# title word is never mistaken for one.
_NET = (r"(?:netflix|hbo|max|apple|tv|amazon|prime|video|disney|hulu|paramount|peacock"
        r"|adult|swim|starz|showtime|fx|amc|bbc|itv|sky|crunchyroll|cartoon|network"
        r"|nickelodeon|nbc|abc|cbs|fox|syfy|cw|mgm|epix|channel\s+4)")
_FORM = r"(?:(?:tv|television|limited|animated|anime|event)\s+)?(?:series|film|movie|documentary|special)"
_NETWORK_TAIL = re.compile(
    rf"\s+(?:(?:a|an|the)\s+)?(?:{_NET}\s+){{0,3}}original\s+(?:{_NET}\s+){{0,3}}{_FORM}"
    r"(?:\s+(?:soundtrack|score|ost))?$")
_FROM_TAIL = re.compile(
    rf"\s+(?:original\s+)?(?:soundtrack|music|score)\s+from\s+(?:(?:a|an|the)\s+)?(?:{_NET}\s+){{0,3}}"
    rf"(?:original\s+)?(?:{_NET}\s+){{0,3}}{_FORM}$")
# "(Music from the Original Series on Prime Video)"
_ON_NETWORK_TAIL = re.compile(
    rf"\s+(?:original\s+)?(?:music|soundtrack|score)\s+from\s+(?:the\s+)?(?:original\s+)?{_FORM}"
    rf"\s+on\s+(?:{_NET}\s+){{0,2}}{_NET}$")
_EDITION_TAIL = re.compile(
    r"\s+(?:\d+\s+(?:st|nd|rd|th)\s+anniversary(?:\s+edition)?|\d{4}\s+(?:mix|remaster|remastered))$")
# "(Expanded Motion Picture Soundtrack)" and kin. A qualifier is required, so
# "Star Trek: The Motion Picture" keeps the words that are its name.
_PICTURE_TAIL = re.compile(
    r"\s+(?:(?:expanded|extended|complete|deluxe|remastered)\s+(?:original\s+)?|original\s+)"
    r"motion\s+picture(?:\s+(?:soundtrack|score|ost))?$")
# rule 8: soundtrack wording in Chinese and Japanese album titles
_CJK_TAIL = re.compile(
    r"\s*(?:電影|电影|映画|影視|影视|劇場版|剧场版|動畫|动画|劇集|剧集)?\s*"
    r"(?:原聲帶|原聲大碟|原聲專輯|原声带|原声大碟|原声专辑|原聲|原声"
    r"|オリジナル\s*サウンドトラック|サウンドトラック)$")

_SEASON_MARK = re.compile(r"\b(?:season|series|book)\s+(\d+)\b")  # Infinity Train counts Books
_VOL_MARK = re.compile(r"\b(?:vol|volume)\s+(\d+)\b")   # Stranger Things counts seasons in volumes
_CHAPTER_MARK = re.compile(r"\bchapters?\s+\d+(\s+\d+)?\b")  # episode markers, never a season
_EPISODE_MARK = re.compile(r"\bepisode\s+(?:\d+|i)\b")  # "Episode I - The Phantom Menace"
_WORD_NUMS = {w: i for i, w in enumerate(
    "one two three four five six seven eight nine ten eleven twelve".split(), 1)}
_NUMBERED = re.compile(r"\b(season|series|book|volume|vol|part|pt|chapter)\s+("
                       + "|".join(_WORD_NUMS) + r")\b")
_ABBREV = re.compile(r"\b(pt|vol)\b(?=\s+(?:\d|i\b))")  # rule 7
_SEQUEL_TAIL = re.compile(r"^(?:(?:part|volume|chapter)\s+)?\d")
_FIRST_VOLUME = re.compile(r"^volume\s+1$")
_FIRST_VOLUME_TAIL = re.compile(r"\s+volume\s+1$")


def _is_sequel_tail(tail):
    """A numeral right after the title marks a sequel (Jaws 2, Part II,
    Chapter 2), except a bare Vol. 1, which only ever opens the title's
    own soundtrack (The Housemaid, Vol. 1)."""
    text = " ".join(tail)
    return bool(_SEQUEL_TAIL.match(text)) and not _FIRST_VOLUME.match(text)

# an album title must say it is a soundtrack, in any of these scripts;
# only rule 2 lets an exact title through without it
_SCREEN_WORDING = re.compile(r"\b(?:soundtrack|score|music from|ost)\b|原聲|原声|サウンドトラック",
                             re.IGNORECASE)
_SCREEN_REJECT = re.compile(
    r"\b(inspired|tribute|karaoke|remix(es|ed)?|covers?|lullab|8.?bit|lo.?fi"
    r"|music box|relaxing|piano (covers?|versions?|tributes?|renditions?)"
    r"|orchestral adaptation|the best of|reimagined|anniversary celebration"
    r"|video ?game|videogame)\b", re.IGNORECASE)

# serial screen-knockoff acts seen in discovery and the missing-titles
# investigation, same doctrine as _COVERS_ARTISTS
_SCREEN_TRIBUTE = {"the soundtrack studio stars", "the london film score orchestra",
                   "the original movies orchestra", "movie sounds unlimited",
                   "the hollywood symphony orchestra",
                   "the hollywood symphony orchestra and voices",
                   "the hollywood symphony orchetsra",
                   "the roy hamilton orchestra", "relaxing piano crew",
                   "the o'neill brothers group", "john beal", "pink spirit",
                   "rewindmusic", "the remix station", "chill bros studios",
                   "tv hits", "jerrik dizlop", "tmc movie tunez", "tv theme band",
                   "the city of prague philharmonic orchestra", "movie magic instrumental",
                   "hollywood soundstage orchestra", "music legends", "the big movie orchestra",
                   "the virtua philharmonic orchestra & singers"}


def _screen_base(text):
    """normalize_title with numerals folded and numbered markers made
    uniform, so "Pt. Three", "Pt 3" and "Part III" all read "part 3"."""
    t = _numfold(normalize_title(text or ""))
    t = _NUMBERED.sub(lambda m: f"{m.group(1)} {_WORD_NUMS[m.group(2)]}", t)
    return _ABBREV.sub(lambda m: "part" if m.group(1) == "pt" else "volume", t)


def normalize_screen(title, medium=None):
    """The comparable form of an album title. For TV, season, volume and
    chapter markers fold away (films keep them: Vol. 2 is another film);
    motion-picture, series and edition tails drop, Chinese and Japanese
    soundtrack words drop, and a leading "Soundtrack From" unwraps.
    "Westworld: Season 1 (Music from the HBO Series)" comes out "westworld"."""
    base = _screen_base(title)
    t = base
    first_volume = _FIRST_VOLUME_TAIL if medium == "film" else None
    if medium != "film":
        t = _SEASON_MARK.sub(" ", t)
        t = _VOL_MARK.sub(" ", t)
        t = _CHAPTER_MARK.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip()
    stripped = True
    while stripped:
        stripped = False
        t2 = _screen_base(t)  # an edition tail can hide a plain suffix behind it
        if t2 and t2 != t:
            t, stripped = t2, True
        for tail in _SCREEN_TAILS:  # curated wording first, the general patterns after
            if t.endswith(" " + tail):
                t = t[: -len(tail)].strip()
                stripped = True
        for rx in (_ON_NETWORK_TAIL, _FROM_TAIL, _NETWORK_TAIL, _EDITION_TAIL, _PICTURE_TAIL, _CJK_TAIL,
                   first_volume):
            if rx is None:
                continue
            t2 = rx.sub("", t).strip()
            if t2 and t2 != t:
                t, stripped = t2, True
    for head in _SCREEN_HEADS:
        if t.startswith(head) and len(t) > len(head) + 3:
            t = t[len(head):]
            break
    return t or base


def _season_of(title):
    """The season an album belongs to, or None for miniseries and
    per-episode releases. Explicit seasons outrank volume counting."""
    norm = _screen_base(title)
    m = _SEASON_MARK.search(norm)
    if m:
        return int(m.group(1))
    m = _VOL_MARK.search(norm)
    return int(m.group(1)) if m else None


def _screen_wants(info):
    """The token lists a title answers to: its TMDb title and its original
    title, each also without an episode marker (rule 4). Each entry is
    (tokens, from_episode_strip, words_dropped)."""
    seen, out = set(), []
    for name in (info.get("name"), info.get("original")):
        if not name:
            continue
        full = _screen_base(name)
        if info.get("medium") == "film":
            full = _FIRST_VOLUME_TAIL.sub("", full).strip() or full  # same fold as the album side
        short = re.sub(r"\s+", " ", _EPISODE_MARK.sub(" ", full)).strip()
        for form, ep in ((full, False), (short, True)):
            if form and form not in seen:
                seen.add(form)
                out.append((form.split(), ep, len(full.split()) - len(form.split())))
    return out


# words that only say an album is a soundtrack, or which edition it is. An
# album whose words beyond the title are all of these names the title
# itself: "Alien: Covenant (Original Soundtrack Album)". Numerals count only
# as an ordinal not right after "the" (Friday the 13th keeps its number), a
# remaster date, a collector's edition number, or one of the title's own
# years (King Kong's "Original 1933 Motion Picture Soundtrack"), so a sequel
# number never qualifies. "Motion picture" never counts right after "the"
# unless a soundtrack word sits beside it, so "Star Trek: The Motion
# Picture" still names another film than Star Trek. Special, film, movie
# and series stay out: Nowhere Special is not Nowhere, The Simpsons Movie
# is not The Simpsons.
_WORDING_WORDS = frozenset(
    "original soundtrack soundtracks score music from the album ost complete expanded extended "
    "deluxe collector collectors edition version remastered remaster restored recording "
    "anniversary collection official selections highlights excerpts".split())
_WORDING_PHRASES = re.compile(
    r"\b(?:(?<!the )\d+ (?:st|nd|rd|th)|remaster(?:ed)? \d{4}|\d{4} (?:remaster(?:ed)?|mix)"
    r"|collector s (?:anniversary )?edition(?: volume \d+)?|special edition"
    r"|(?:score|music|soundtrack|songs) from the motion pictures?"
    r"|motion pictures? (?:soundtrack|score|ost)|(?<!the )motion pictures?)\b")


def _only_wording(tokens, years=()):
    dates = {str(y) for y in years}
    rest = _WORDING_PHRASES.sub(" ", " ".join(t for t in tokens if t not in dates)).split()
    return bool(tokens) and all(t in _WORDING_WORDS for t in rest)


_REL_RANK = {"exact": 0, "episode": 1, "extended": 1}


def _relation(tokens, wants, years=()):
    """How an album's tokens relate to a title: ("exact", 0, []),
    ("episode", extra, tail) for rule 4, ("extended", extra, tail) for
    rule 3, or None when the album names a different work."""
    best = None
    for w, ep, dropped in wants:
        n = len(w)
        rel = None
        if tokens == w:
            rel = ("episode", dropped, []) if ep else ("exact", 0, [])
        else:
            for i in range(len(tokens) - n + 1):
                if tokens[i:i + n] == w:
                    head = tokens[:i]
                    # an article right before the title changes the name: The Invasion
                    if (not ep and not (head and head[-1] == "the") and not _only_wording(w)
                            and _only_wording(head + tokens[i + n:], years)):
                        rel = ("exact", 0, [])
                    else:
                        rel = ("episode" if ep else "extended", len(tokens) - n + dropped, tokens[i + n:])
                    break
        if rel and (best is None or (_REL_RANK[rel[0]], rel[1]) < (_REL_RANK[best[0]], best[1])):
            best = rel
    return best


def _has_cjk(text):
    return any(ord(ch) > 0x2E80 for ch in text)


def _name_in(short, long):
    if not short or not long:
        return False
    return len(short) >= (2 if _has_cjk(short) else 4) and short in long


def _name_forms(name):
    """A normalized name, plus the same name without spaces when it is
    written in Chinese or Japanese: TMDb spells 川井 憲次 with a space and
    YouTube Music credits 川井憲次 without one. Latin names are never joined,
    and lose their accents: TMDb credits Roque Baños, YouTube Music Roque Banos."""
    n = normalize_title(name)
    if n and not _has_cjk(n):
        n = "".join(ch for ch in unicodedata.normalize("NFKD", n) if not unicodedata.combining(ch))
    return [n, n.replace(" ", "")] if (n and " " in n and _has_cjk(n)) else ([n] if n else [])


def _credited(artists, names):
    """Whether a TMDb-credited composer, under any of their names, appears
    among the album's artists."""
    keys = [k for n in names if n for k in _name_forms(n)]
    for a in artists:
        forms = _name_forms(a)
        if any(_name_in(k, f) or _name_in(f, k) for k in keys for f in forms):
            return True
    return False


def _album_plays(album_fn, browse_id):
    try:
        return _plays_total(ytm_tracks_from(album_fn(browse_id))) or 0
    except Exception:
        return None


# an album that names the other medium is that medium's album: "M*A*S*H
# (Original Motion Picture Soundtrack)" is the film's, "Midnight Sun
# (Original Soundtrack from the TV Series)" the show's. A title whose own
# name carries the word (A Series of Unfortunate Events) is exempt.
_OTHER_MEDIUM = {
    "tv": re.compile(r"\bmotion pictures?\b|\bmovies?\b|\bfilms?\b|劇場版|映画", re.IGNORECASE),
    "film": re.compile(r"\bseries\b|\bseasons?\b", re.IGNORECASE),
}


def _year_of(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def screen_classify(results, info, album_fn=None):
    """Every album result judged against one title. Each entry carries a
    verdict: the rule that accepted it, or the first rule that turned it
    away. Accepted entries also carry what ranking and resolution need.
    info: medium, name, original, years, composers, aliases."""
    wants = _screen_wants(info)
    names = list(info.get("composers") or []) + list(info.get("aliases") or [])
    years = [y for y in info.get("years") or [] if y]
    medium = info.get("medium")
    out, seen = [], set()
    for rank, r in enumerate(results or []):
        title = r.get("title", "")
        artists = [a["name"] for a in r.get("artists", []) or [] if a.get("name")]
        e = {"title": title, "year": r.get("year"), "artists": artists, "rank": rank,
             "accepted": False}
        bid = r.get("browseId")
        if r.get("resultType") != "album" or not bid:
            out.append(dict(e, verdict="not an album result"))
            continue
        if bid in seen:
            continue
        seen.add(bid)
        e["url"] = "https://music.youtube.com/browse/" + bid
        m = _SCREEN_REJECT.search(title)
        if m:
            out.append(dict(e, verdict=f"reject vocabulary '{m.group(0)}'"))
            continue
        bad = next((a for a in artists if a.lower() in _COVERS_ARTISTS
                    or a.lower() in _SCREEN_TRIBUTE), None)
        if bad:
            out.append(dict(e, verdict=f"tribute artist '{bad}'"))
            continue
        other = _OTHER_MEDIUM.get(medium)
        hit = other.search(title) if other else None
        if hit and not other.search(" ".join(n for n in (info.get("name"), info.get("original")) if n)):
            out.append(dict(e, verdict=f"medium: '{hit.group(0)}' names a {'film' if medium == 'tv' else 'series'}"))
            continue
        tokens = normalize_screen(title, medium).split()
        e["normalized"] = " ".join(tokens)
        rel = _relation(tokens, wants, years)
        if rel is None:
            out.append(dict(e, verdict="title: the album names a different work"))
            continue
        kind, extra, tail = rel
        if kind != "exact" and tail and _is_sequel_tail(tail):
            out.append(dict(e, verdict=f"sequel guard (tail '{' '.join(tail)}')"))
            continue
        credited = _credited(artists, names)
        yr = _year_of(r.get("year"))
        if yr is None and album_fn and years:
            # a search result sometimes arrives without its year (The Wolf of
            # Wall Street on the Actions runner); the album page carries it
            try:
                yr = _year_of((album_fn(bid) or {}).get("year"))
            except Exception:
                yr = None
            if yr is not None:
                e.update(year=str(yr), yearFrom="album")
        gap = min(abs(yr - y) for y in years) if (yr is not None and years) else None
        near = gap is not None and gap <= SCREEN_YEAR_WINDOW
        wording = bool(_SCREEN_WORDING.search(title))
        e.update(credited=credited, gap=gap, extra=extra, worded=wording)
        era = "is outside the window" if gap is not None else "is unknown"
        klass, weak, ok, why = "exact", False, False, ""
        if kind == "exact" and wording:
            rule, ok = "1 exact title", credited or near
            why = f"rule 1: no credited composer and the album year {era}"
        elif kind == "exact":
            if credited:
                rule, ok = "2 bare title, composer credited", near
                why = f"rule 2: composer credited but the album year {era}"
            elif not near:
                rule, why = "2 bare title", f"rule 2: no wording, no credited composer, and the album year {era}"
            else:
                plays = _album_plays(album_fn, bid) if album_fn else None
                e["plays"] = plays
                rule, klass, weak = "2 bare title by plays (weak)", "weak", True
                ok = plays is not None and plays >= WEAK_PLAYS_MIN
                why = (f"rule 2: no wording or credited composer, plays "
                       f"{plays if plays is not None else 'unknown'} below {WEAK_PLAYS_MIN}")
        else:
            klass = "extended"
            rule = "4 episode marker" if kind == "episode" else "3 franchise prefix or suffix"
            ok = wording and credited and near
            missing = [need for need, have in (
                ("soundtrack wording", wording), ("the credited composer", credited),
                ("the album year within the window" if gap is not None else "a known album year", near))
                if not have]
            why = f"rule {rule[0]}: needs " + ", ".join(missing)
        if not ok:
            out.append(dict(e, verdict=why))
            continue
        people = [a for a in artists if a.lower() != "various artists"
                  and normalize_title(a) != normalize_title(info.get("name") or "")]
        thumbs = sorted((t for t in r.get("thumbnails", []) or [] if t.get("url")),
                        key=lambda t: t.get("width") or 0)
        out.append(dict(e, accepted=True, verdict="ACCEPTED by rule " + rule, rule=rule,
                        klass=klass, weak=weak,
                        url="https://music.youtube.com/browse/" + bid,
                        art=thumbs[-1]["url"] if thumbs else None,
                        season=_season_of(title) if medium != "film" else None,
                        composers=list(info.get("composers") or []) or people,
                        overlap=credited, dist=gap if gap is not None else 999))
    return out


def screen_matches(results, info, album_fn=None):
    return [c for c in screen_classify(results, info, album_fn) if c["accepted"]]


_COMPILATION_WORDING = re.compile(
    r"\bmusic from (?:and inspired by )?the (?:original )?(?:motion picture|film|movie)\b"
    r"|\bsongs? from\b", re.IGNORECASE)


def is_songs_album(c):
    """A licensed-song compilation rather than a score: no credited
    composer, and the album is credited only to Various Artists or its
    title uses compilation wording ("Music From The Motion Picture").
    A credited composer's album never counts, whatever its wording
    (Inception), and neither does one credited to the show itself
    (Infinity Train). Flag only: scores-only filtering can come later."""
    if c.get("credited"):
        return False
    artists = [a.lower() for a in c.get("artists") or []]
    various_only = bool(artists) and all(a == "various artists" for a in artists)
    return various_only or bool(_COMPILATION_WORDING.search(c.get("title") or ""))


def claimed_albums(releases):
    """Albums rows currently wear. A retired row keeps its album for the
    listener's history but no longer holds it against the row it belongs to."""
    return {r["ytmAlbumUrl"] for r in releases if r.get("ytmAlbumUrl") and not r.get("retired")}


_CLASS_RANK = {"exact": 0, "extended": 1, "weak": 2}


def _rank_key(c):
    """Rule 5, a title choosing among its albums: credited first, then exact
    over extended, fewer extra words, closer year. A dead heat goes to the
    album that says it is a soundtrack before search order decides, so
    Fellowship keeps its soundtrack album over the Complete Recordings."""
    return (not c["credited"], _CLASS_RANK[c["klass"]], c["extra"],
            c["gap"] if c["gap"] is not None else 99, not c.get("worded"), c["rank"])


def _claim_key(c, slot):
    """Rule 6, an album choosing among the titles that want it: an exact
    claim beats a tolerant one before anything else is compared."""
    return (_CLASS_RANK[c["klass"]], not c["credited"], c["extra"],
            c["gap"] if c["gap"] is not None else 99, not c.get("worded"), str(slot))


def resolve_screen(slots, reserved=()):
    """Hand albums out across every title in a batch at once. slots maps a
    row target, ("film", id) or ("tv", id, season), to its accepted
    candidates. Each title takes its best album by rule 5; an album wanted
    by several goes to the best claim by rule 6, and the displaced title
    moves on to its next choice. Albums in reserved are never handed out.
    The outcome does not depend on the order titles arrive in. Returns
    (winner by slot, conflicts as (album url, winning slot, losing slot))."""
    reserved = set(reserved or ())
    prefs = {k: sorted((c for c in cands if c["url"] not in reserved), key=_rank_key)
             for k, cands in slots.items()}
    nxt = dict.fromkeys(prefs, 0)
    holder, conflicts = {}, []
    queue = sorted(prefs, key=str)
    while queue:
        k = queue.pop(0)
        while nxt[k] < len(prefs[k]):
            c = prefs[k][nxt[k]]
            nxt[k] += 1
            held = holder.get(c["url"])
            if held is None:
                holder[c["url"]] = (k, c)
                break
            hk, hc = held
            if _claim_key(c, k) < _claim_key(hc, hk):
                holder[c["url"]] = (k, c)
                conflicts.append((c["url"], k, hk))
                queue.append(hk)
                break
            conflicts.append((c["url"], hk, k))
    return {k: c for k, c in holder.values()}, conflicts


def screen_slots(info, cands):
    """Row targets for one title: a film is one slot, a show one per season."""
    if info["medium"] == "film":
        return {("film", info["id"]): cands}
    out = {}
    for c in cands:
        out.setdefault(("tv", info["id"], c["season"]), []).append(c)
    return out


def screen_search(resolve, info):
    """Rule 8: the title's search, plus one on TMDb's original title when
    it reads differently. Results merge in order with repeats dropped."""
    queries = [_query(info["name"])]
    orig = info.get("original")
    if orig and _screen_base(orig) != _screen_base(info["name"]):
        queries.append(_query(orig))
    merged, seen = [], set()
    for q in queries:
        for r in resolve(q) or []:
            key = r.get("browseId") or id(r)
            if key not in seen:
                seen.add(key)
                merged.append(r)
    return merged


def match_film(results, name, year, composers, aliases=None, original=None, album_fn=None):
    """One film, one album, for callers holding search results already."""
    info = {"medium": "film", "id": "match", "name": name, "original": original,
            "years": [year] if year else [], "composers": list(composers or []),
            "aliases": list(aliases or [])}
    winners, _ = resolve_screen(screen_slots(info, screen_matches(results, info, album_fn)))
    return winners.get(("film", "match"))


def tv_season_albums(results, show, year, composers, season_years=None, aliases=None,
                     original=None, album_fn=None):
    """One album per season slot, season-less albums sharing one slot."""
    info = {"medium": "tv", "id": "match", "name": show, "original": original,
            "years": sorted({y for y in [year, *(season_years or [])] if y}),
            "composers": list(composers or []), "aliases": list(aliases or [])}
    winners, _ = resolve_screen(screen_slots(info, screen_matches(results, info, album_fn)))
    return [winners[k] for k in sorted(winners, key=lambda k: (k[2] is None, k[2] or 0))]


TMDB_IMG = "https://image.tmdb.org/t/p/w500"


def _tmdb_get(path, **params):
    key = os.environ.get("TMDB_API_KEY", "")
    if not key:
        raise RuntimeError("TMDB_API_KEY not set")
    headers = {"User-Agent": USER_AGENT}
    if key.startswith("eyJ"):
        headers["Authorization"] = f"Bearer {key}"
    else:
        params["api_key"] = key
    resp = requests.get(f"https://api.themoviedb.org/3/{path}", params=params,
                        headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()


_TMDB_GMAP = {}
_PERSON_AKA = {}


def _tmdb_genre_map(kind):
    if kind not in _TMDB_GMAP:
        _TMDB_GMAP[kind] = {g["id"]: g["name"]
                            for g in _tmdb_get(f"genre/{kind}/list").get("genres", [])}
    return _TMDB_GMAP[kind]


def _aliases(people):
    """Rule 8: every other name TMDb knows a composer by, any script."""
    names = []
    for p in people:
        pid = p.get("id")
        if pid is None:
            continue
        if pid not in _PERSON_AKA:
            try:
                _PERSON_AKA[pid] = [n for n in _tmdb_get(f"person/{pid}").get("also_known_as") or [] if n]
            except Exception:
                _PERSON_AKA[pid] = []  # aliases only widen a match; a miss costs nothing
        names.extend(_PERSON_AKA[pid])
    return names


def tmdb_credits(kind, tid):
    """Composer names and aliases: Original Music Composer for films,
    aggregate_credits for TV (18/20 in discovery vs 15/20 for plain credits)."""
    if kind == "movie":
        crew = _tmdb_get(f"movie/{tid}/credits").get("crew", [])
        people = [c for c in crew if c.get("job") == "Original Music Composer"]
    else:
        crew = _tmdb_get(f"tv/{tid}/aggregate_credits").get("crew", [])
        people = [c for c in crew if any("composer" in (j.get("job") or "").lower()
                                         for j in c.get("jobs", []))]
    return [c["name"] for c in people], _aliases(people)


def tmdb_seasons(tid):
    detail = _tmdb_get(f"tv/{tid}")
    return {str(x["season_number"]): x.get("air_date")
            for x in detail.get("seasons", []) if x.get("season_number")}


def _tmdb_bundle(kind, results, **extra):
    """Discover results plus everything the parser needs without network."""
    composers, aliases, seasons = {}, {}, {}
    for x in results:
        key = str(x["id"])
        composers[key], aliases[key] = tmdb_credits(kind, x["id"])
        if kind == "tv":
            seasons[key] = tmdb_seasons(x["id"])
    out = {"results": results, "genres": _tmdb_genre_map(kind),
           "composers": composers, "aliases": aliases}
    if kind == "tv":
        out["seasons"] = seasons
    out.update(extra)
    return json.dumps(out).encode()


def tmdb_film_catalog(page, floor):
    """One backfill page of films by vote count, bundled like the daily."""
    d = _tmdb_get("discover/movie", page=page,
                  **{"vote_count.gte": floor, "sort_by": "vote_count.desc"})
    return _tmdb_bundle("movie", d.get("results", []), total_pages=d.get("total_pages", 1))


def tmdb_tv_catalog(page, floor):
    """One backfill page of shows by vote count."""
    d = _tmdb_get("discover/tv", page=page,
                  **{"vote_count.gte": floor, "sort_by": "vote_count.desc"})
    return _tmdb_bundle("tv", d.get("results", []), total_pages=d.get("total_pages", 1))


def tmdb_film_fetch(now=None):
    """Recent films above the vote floor, bundled for the parser."""
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(days=TMDB_FILM_WINDOW_DAYS)).strftime("%Y-%m-%d")
    results = []
    for page in range(1, TMDB_PAGES + 1):
        d = _tmdb_get("discover/movie", page=page, **{
            "primary_release_date.gte": since,
            "primary_release_date.lte": now.strftime("%Y-%m-%d"),
            "vote_count.gte": TMDB_FILM_VOTES, "sort_by": "vote_count.desc"})
        results.extend(d.get("results", []))
        if page >= d.get("total_pages", 1):
            break
    return _tmdb_bundle("movie", results)


def tmdb_tv_fetch(now=None):
    """Recent shows above the vote floor, bundled for the parser."""
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(days=TMDB_TV_WINDOW_DAYS)).strftime("%Y-%m-%d")
    results = []
    for page in range(1, TMDB_PAGES + 1):
        d = _tmdb_get("discover/tv", page=page, **{
            "first_air_date.gte": since, "first_air_date.lte": now.strftime("%Y-%m-%d"),
            "vote_count.gte": TMDB_TV_VOTES, "sort_by": "vote_count.desc"})
        results.extend(d.get("results", []))
        if page >= d.get("total_pages", 1):
            break
    return _tmdb_bundle("tv", results)


def _tmdb_genres(entry, gmap):
    names = [gmap.get(str(g)) or gmap.get(g) for g in entry.get("genre_ids") or []]
    return [n for n in names if n][:3] or None


def film_info(entry, data):
    mid = str(entry.get("id"))
    date = entry.get("release_date") or entry.get("primary_release_date") or ""
    return {"medium": "film", "id": mid, "name": (entry.get("title") or "").strip(),
            "original": (entry.get("original_title") or "").strip() or None, "date": date,
            "years": [int(date[:4])] if date[:4].isdigit() else [],
            "composers": list(data.get("composers", {}).get(mid, [])),
            "aliases": list(data.get("aliases", {}).get(mid, []))}


def tv_info(entry, data):
    sid = str(entry.get("id"))
    aired = entry.get("first_air_date") or ""
    seasons = data.get("seasons", {}).get(sid, {})
    return {"medium": "tv", "id": sid, "name": (entry.get("name") or "").strip(),
            "original": (entry.get("original_name") or "").strip() or None, "date": aired,
            "years": sorted({int(d[:4]) for d in [aired, *seasons.values()] if d and d[:4].isdigit()}),
            "seasons": seasons,
            "composers": list(data.get("composers", {}).get(sid, [])),
            "aliases": list(data.get("aliases", {}).get(sid, []))}


def screen_items(winners, titles):
    """Merge items for resolved slots, in title order then season order.
    titles: [(info, discover entry, genre map)]."""
    by_title = {}
    for k in winners:
        by_title.setdefault((k[0], k[1]), []).append(k)
    items = []
    for info, entry, gmap in titles:
        medium = info["medium"]
        keys = sorted(by_title.get((medium, info["id"]), []),
                      key=lambda k: (k[-1] is None, k[-1] or 0) if medium == "tv" else 0)
        for k in keys:
            hit = winners[k]
            n = k[2] if medium == "tv" else None
            name = info["name"]
            poster = entry.get("poster_path")
            item = {"title": f"{name} Season {n} Soundtrack" if n else f"{name} Soundtrack",
                    "albumTitle": hit["title"], "medium": medium,
                    "game": name, "composers": hit["composers"],
                    "genres": _tmdb_genres(entry, gmap),
                    "url": f"https://www.themoviedb.org/{'movie' if medium == 'film' else 'tv'}/{info['id']}",
                    "date": (info.get("seasons", {}).get(str(n)) if n else None) or info["date"],
                    "ytmAlbumUrl": hit["url"],
                    "art": hit["art"] or (f"{TMDB_IMG}{poster}" if poster else None)}
            if hit.get("weak"):
                item["weakMatch"] = True
            items.append(item)
    return items


def _screen_batch(raw, resolve, medium, album_fn):
    """Search, judge, and resolve every title in a bundle together."""
    data = json.loads(raw)
    gmap = data.get("genres", {})
    slots, titles, errors = {}, [], 0
    for entry in data.get("results", []):
        info = film_info(entry, data) if medium == "film" else tv_info(entry, data)
        if not info["name"] or not info["date"]:
            continue
        try:
            cands = screen_matches(screen_search(resolve, info), info, album_fn)
        except Exception:
            errors += 1
            continue
        slots.update(screen_slots(info, cands))
        titles.append((info, entry, gmap))
    winners, _ = resolve_screen(slots)
    items = screen_items(winners, titles)
    if errors and not items:
        raise RuntimeError(f"all {errors} album lookups failed")
    return items


def parse_tmdb_film(raw, resolve, album_fn=None):
    return _screen_batch(raw, resolve, "film", album_fn)


def parse_tmdb_tv(raw, resolve, album_fn=None):
    return _screen_batch(raw, resolve, "tv", album_fn)

SOURCES = [
    # nowplaying.cool dropped 2026-07-30 at CJ's request: headline rows with
    # no art or game anchor read as noise next to catalog rows (the parser
    # stays for the tests and in case the verdict ever reverses)
    {"name": "blipblop", "type": "editorial",
     "url": "https://blipblop.net/feed/", "parse": parse_blipblop},
    {"name": "vgmo", "type": "editorial",
     "url": "https://www.vgmonline.net/feed/", "parse": parse_vgmo},
    {"name": "steam", "type": "catalog",
     "url": "https://store.steampowered.com/search/results/"
            "?query&start=0&count=25&category1=990&sort_by=Released_DESC&infinite=1&l=english&cc=US",
     "parse": parse_steam},
    {"name": "igdb", "type": "catalog", "url": IGDB_URL, "parse": parse_igdb},
    # film and TV: TMDb plays the role IGDB plays; a missing TMDB_API_KEY
    # warns and skips these two while everything else still runs
    {"name": "tmdb-film", "type": "catalog", "url": "tmdb:film", "parse": parse_tmdb_film,
     "albums": True},
    {"name": "tmdb-tv", "type": "catalog", "url": "tmdb:tv", "parse": parse_tmdb_tv,
     "albums": True},
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


def _medium(r):
    return r.get("medium") or "game"


def _fuzzy_find(norm, releases, norms, med="game"):
    best, best_ratio = None, 0.0
    tail = _numeral_tail(norm)
    for r in releases:
        if _medium(r) != med or r.get("retired"):
            continue  # mediums never fuzzy-merge, and retired rows never merge at all
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


_TMDB_TITLE = re.compile(r"themoviedb\.org/(movie|tv)/(\d+)")


def _tmdb_other(row, url):
    """Whether a row belongs to a different TMDb title than this url."""
    m = _TMDB_TITLE.search(url or "")
    ids = {x.groups() for s in row.get("sources", []) for x in [_TMDB_TITLE.search(s.get("url") or "")] if x}
    return bool(m and ids) and m.groups() not in ids


def merge(releases, items, source, seen_at):
    """Fold one source's items in. Append-only: existing entries only ever gain
    a source, an earlier date, or a fill for a still-null enrichment field;
    id and title never change. Mediums never mix: a film and a game sharing a
    name are different releases by definition, so medium is part of the
    dedupe key and non-game slugs carry a medium prefix."""
    by_id = {r["id"]: r for r in releases}
    norms = {id(r): normalize_title(r["title"]) for r in releases}
    by_numfold = {}
    for r in releases:
        if not r.get("retired"):  # a retired row is history, never a merge target
            by_numfold.setdefault((_medium(r), _numfold(norms[id(r)])), r)
    added = merged = 0
    for it in items:
        if not it["title"] or not it["url"]:
            continue
        med = it.get("medium") or "game"
        slug = slugify(it["title"]) if med == "game" else f"{med}-{slugify(it['title'])}"
        norm = normalize_title(it["title"])
        target = by_id.get(slug)
        if target is not None and (_medium(target) != med or target.get("retired")):
            target = None  # another medium's row, or a retired one: never merge
        # numeral variants (II vs 2) are the same name exactly — never left to fuzzy odds
        target = target or by_numfold.get((med, _numfold(norm))) or _fuzzy_find(norm, releases, norms, med)
        if target is not None and _tmdb_other(target, it["url"]):
            # one name, two TMDb titles (21 and 22 Jump Street, Pinocchio 2019
            # and 2022): never one row. The newcomer takes its own id,
            # year-suffixed when the plain one is worn
            target = None
            if slug in by_id:
                slug = f"{slug}-{it['date'][:4]}" if it.get("date") else slug
                target = by_id.get(slug)
                if target is not None and (_medium(target) != med or target.get("retired")
                                           or _tmdb_other(target, it["url"])):
                    target = None
        if target is not None and it["date"] and target.get("date") and _far_apart(it["date"], target["date"]):
            # same name, different era: Tomb Raider 1996 is not Tomb Raider 2013.
            # The newcomer gets a year-suffixed id; reruns find it there again.
            slug = f"{slug}-{it['date'][:4]}"
            target = by_id.get(slug)
            if target is not None and (_medium(target) != med or target.get("retired")):
                target = None
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
                if it.get("weakMatch"):
                    target["weakMatch"] = True
                if it.get("songsAlbum"):
                    target["songsAlbum"] = True
                target.pop("tracks", None)  # a real album arrived: refresh the tracklist with plays
                target.pop("tracksN", None)
                target.pop("playsTotal", None)
                target.pop("ytmPlaylistId", None)
            if not target.get("art") and it.get("art"):
                target["art"] = it["art"]
        else:
            if slug in by_id:
                # the id is worn by a row this item must not merge with (a
                # cross-medium name collision): year-suffix like the era rule,
                # and skip rather than ever duplicate an id
                alt = f"{slug}-{it['date'][:4]}" if it.get("date") else None
                if not alt or alt in by_id:
                    continue
                slug = alt
            entry = {"id": slug, "title": it["title"], "medium": med, "game": it.get("game"),
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
            if it.get("weakMatch"):
                entry["weakMatch"] = True  # rule 2 by plays alone: auditable later
            if it.get("songsAlbum"):
                entry["songsAlbum"] = True  # licensed songs, not a score
            releases.append(entry)
            by_id[slug] = entry
            norms[id(entry)] = normalize_title(entry["title"])
            by_numfold.setdefault((med, _numfold(norms[id(entry)])), entry)
            added += 1
    return added, merged


def resolve_albums(releases, resolve, now, cap=RESOLVE_CAP):
    """Fill ytmAlbumUrl for recent rows that lack one, with the same strict
    matcher. Bounded per run; unresolved rows retry until they age out."""
    cutoff = (now - timedelta(days=RESOLVE_WINDOW_DAYS)).strftime("%Y-%m-%d")
    claimed = claimed_albums(releases)
    looked = filled = 0
    for r in releases:
        if _medium(r) != "game":
            continue  # film and tv rows are born with an album or not at all
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
            r.pop("tracksN", None)
            r.pop("playsTotal", None)
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
        if x.get("ytmAlbumUrl") and not x.get("retired"):
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


def drop_claimed_newcomers(releases, preexisting_ids):
    """One album, one row, across mediums: a row born this run wearing an
    album an earlier row already wears is dropped before it is ever
    written. This is what keeps a film or TV row from stealing its
    namesake game's album (The Last of Us, The Witcher). A retired row
    holds no claim. Returns (dropped row id, owner row id) pairs, so every
    drop is logged by name."""
    owner = {}
    kept, dropped = [], []
    for r in releases:
        url = None if r.get("retired") else r.get("ytmAlbumUrl")
        if url and url in owner and r["id"] not in preexisting_ids:
            dropped.append((r["id"], owner[url]))
            continue
        if url:
            owner.setdefault(url, r["id"])
        kept.append(r)
    releases[:] = kept
    return dropped


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
    preexisting = {r["id"] for r in releases}

    ok = 0
    for source in SOURCES:
        try:
            extra = {"album_fn": album_fn} if source.get("albums") else {}  # rule 2 reads plays
            items = source["parse"](fetch_fn(source["url"]), resolve_fn, **extra)
            added, merged = merge(releases, items, source, seen_at)
            print(f"{source['name']}: {len(items)} items -> {added} new, {merged} merged")
            ok += 1
        except Exception as exc:  # one bad source must not kill the others
            print(f"::warning::{source['name']} failed: {exc}")
    if ok == 0:
        print("::error::every source failed")
        return 1
    dropped = drop_claimed_newcomers(releases, preexisting)
    if dropped:
        print(f"claimed-album guard: {len(dropped)} newcomer rows dropped: "
              + "; ".join(f"{d} (album worn by {o})" for d, o in dropped))

    looked, filled = resolve_albums(releases, resolve_fn, now)
    print(f"album resolver: {looked} lookups, {filled} filled")
    ga, gm = gaas_albums(releases, resolve_fn, seen_at)
    print(f"live-service albums: {ga} new, {gm} merged")
    fetched = fill_tracks(releases, album_fn, itunes_fn, cap=TRACKS_CAP,
                          tracks_dir=Path(data_path).parent / "tracks")
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
