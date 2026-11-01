#!/usr/bin/env python3
"""Builds shelf.json for Tigris's custom Top Shelf.

The feed is a JSON object keyed by Android TV app package; each value is a list of at most 12
{title, meta, image} cards, where image is an http(s) URL. Tigris shows a package's cards when
that app's tile is focused in the first row. Sources (config.json):

  {"tvmaze": "<service>"}   new and upcoming episodes on a streaming service, from TVmaze's
                            schedule; no account needed
  {"netflix_top10": "MY"}   a random handful of Netflix's official weekly Top 10 shows for a
                            country (top10.netflix.com) that TVmaze has pictures for; new Netflix
                            episodes (as "tvmaze") add to the choice when too few are left
  {"youtube": "recommended"} the signed-in YouTube home feed, through yt-dlp; only with
                            --youtube-cookies (a browser) or --youtube-cookie-file; "max_age_days"
                            keeps recent uploads only, "islamic" adds one video from the watch
                            history matching those words
  {"youtube_playlists": "@X"} the newest videos of a channel's most recently updated show
                            playlists, e.g. Viu Malaysia's dramas; through yt-dlp
  {"viu": "my"}             a random handful of the Top 10 on Viu's home page for that country
  {"rtmklik": {...}}        RTMKlik: its special live channels (Saluran Khas), chosen channel cards
                            (RTMKlik publishes no schedule) and, from the unifi TV guide, what's on
                            TV1/TV2 now
  {"unifi": [channels]}     what's on now (or next) on these unifi TV channels, from the same
                            public programme guide unifi TV's web player reads; live events first.
                            "images" says where each channel's programme pictures come from
                            (sports: TheSportsDB, anime: AniList, series: TVmaze, youtube: a
                            YouTube search); the channel logo stays the fallback

"never" in config.json lists words and phrases (horror, LGBTQ themes) that keep a card off the shelf
when they appear in its title, details, genres or description, wherever a source gives those.

The streaming apps (everything but unifi TV and RTMKlik) don't repeat their previous cards while
their source has others: each picks from more than it shows and puts last run's cards last.

The shelf is a full-width slideshow, so wide pictures are preferred everywhere. An app whose
source fails keeps the cards it had in the previous output. Standard library plus yt-dlp.
"""
import argparse
import datetime as dt
import json
import os
import pathlib
import random
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zoneinfo

ROOT = pathlib.Path(__file__).resolve().parent
TVMAZE = "https://api.tvmaze.com"
UA = "tigris-top-shelf (github.com/mankidal19/tigris-top-shelf)"
MAX_ITEMS = 5  # cards per app; config.json "max_cards" changes it (Tigris keeps at most 12)
MIN_WIDE = 3  # below this many shows with wide art, posters fill a TVmaze shelf up
NEVER = []  # normalised words and phrases from config.json "never"; see allowed()


def allowed(*texts):
    """False when any text (title, details, genres, description) holds a "never" word or phrase,
    matched as whole words: "gay" catches "Gay" and "gay-themed" but not "Gaya"."""
    words = f" {norm(' '.join(t for t in texts if t))} "
    hit = next((w for w in NEVER if f" {w} " in words), None)
    if hit:
        log(f"left out {texts[0]!r} ({hit!r})")
    return hit is None


def shown(card, before):
    """Whether [card] was on the previous shelf [before]: the same picture, which tells apart a
    show's episodes (Viu) and videos, and stays the same for a show between runs."""
    return any(card.get("image") == b.get("image") for b in before or [])


def rotate(pool, before):
    """MAX_ITEMS cards of [pool] for the streaming apps, those not on the previous shelf [before]
    first, so each run brings different ones while the pool lasts; the previous ones only fill up.
    The chosen keep the pool's order. Live TV (unifi TV, RTMKlik) doesn't rotate."""
    chosen = [c for c in pool if not shown(c, before)][:MAX_ITEMS]
    chosen += [c for c in pool if shown(c, before)][:MAX_ITEMS - len(chosen)]
    return [c for c in pool if any(c is x for x in chosen)]


def plain(html):
    return re.sub(r"<[^>]+>", " ", html or "")


def log(*args):
    print(*args, file=sys.stderr, flush=True)


def tvmaze(path):
    req = urllib.request.Request(TVMAZE + path, headers={"User-Agent": UA})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 2:  # TVmaze allows 20 calls per 10 s
                raise
            time.sleep(5)


# ---- TVmaze ---------------------------------------------------------------------------------

def tvmaze_schedule(days_back, days_ahead):
    """Every streaming episode in the window, as (day, show, episode)."""
    today = dt.date.today()
    out = []
    for offset in range(-days_back, days_ahead + 1):
        day = today + dt.timedelta(days=offset)
        for ep in tvmaze(f"/schedule/web?date={day}"):
            show = ep.get("_embedded", {}).get("show") or {}
            if show.get("id"):
                out.append((day, show, ep))
        time.sleep(0.6)
    return out


def service_of(show):
    return (show.get("webChannel") or show.get("network") or {}).get("name")


def show_image(show, episode):
    """(url, wide): background art, any other wide image, the episode still, then the poster."""
    try:
        images = tvmaze(f"/shows/{show['id']}/images")
    except Exception:
        images = []

    def wide(i):
        o = i.get("resolutions", {}).get("original") or {}
        w, h = o.get("width") or 0, o.get("height") or 0
        return o.get("url") if w >= 960 and h and 1.3 <= w / h <= 2.4 else None

    for i in sorted(images, key=lambda i: (i.get("type") != "background", not i.get("main"))):
        if wide(i):
            return wide(i), True
    still = (episode.get("image") or {}).get("original")
    if still:
        return still, True
    return (show.get("image") or {}).get("original"), False


def episode_meta(service, episode, count, day, today):
    parts = [service]
    if count > 1 and episode.get("season"):
        parts.append(f"S{episode['season']} · {count} episodes")  # a whole batch dropped at once
    elif episode.get("season") and episode.get("number"):
        parts.append(f"S{episode['season']} E{episode['number']}")
    if day == today:
        parts.append("New today")
    else:
        parts.append(f"{'Out' if day < today else 'Coming'} {day:%a} {day.day} {day:%b}")
    return " · ".join(parts)


def tvmaze_cards(service, schedule, limit=None):
    """One card per show, at most [limit] (MAX_ITEMS): today first, then the latest releases, then
    the soonest coming."""
    limit = limit or MAX_ITEMS
    today = dt.date.today()
    newest, drops = {}, {}
    for day, show, ep in schedule:
        if service_of(show) != service:
            continue
        drops[show["id"], day] = drops.get((show["id"], day), 0) + 1
        if show["id"] not in newest or day >= newest[show["id"]][0]:
            newest[show["id"]] = (day, show, ep)

    def order(entry):
        day = entry[0]
        return (0, 0) if day == today else ((1, (today - day).days) if day < today else (2, (day - today).days))

    wide, posters = [], []
    for day, show, ep in sorted(newest.values(), key=order):
        if not allowed(show["name"], " ".join(show.get("genres") or []), plain(show.get("summary")),
                       ep.get("name"), plain(ep.get("summary"))):
            continue
        image, is_wide = show_image(show, ep)
        time.sleep(0.6)
        if not image or not image.startswith("http"):
            continue
        card = {"title": show["name"][:120], "meta": episode_meta(service, ep, drops[show["id"], day], day, today)[:180],
                "image": image}
        (wide if is_wide else posters).append(card)
        if len(wide) == limit:
            break
    return (wide + (posters if len(wide) < MIN_WIDE else []))[:limit]


SCHEDULES = {}  # (days_back, days_ahead): tvmaze_schedule(), shared by the apps


def schedule(days_back, days_ahead):
    if (days_back, days_ahead) not in SCHEDULES:
        SCHEDULES[days_back, days_ahead] = tvmaze_schedule(days_back, days_ahead)
    return SCHEDULES[days_back, days_ahead]


def tvmaze_pool(service, cfg, before, cards=()):
    """[cards] and up to twice MAX_ITEMS of [service]'s other shows in the window, for rotate().
    While fewer than MAX_ITEMS of them weren't on the previous shelf [before], the shows released
    before the window ("older_days_back", 21 days ago) join after them."""
    back, ahead = cfg.get("days_back", 7), cfg.get("days_ahead", 7)
    pool = list(cards)
    for days in ((back, ahead), (cfg.get("older_days_back", 21), -back - 1)):
        if sum(not shown(c, before) for c in pool) >= MAX_ITEMS:
            break
        titles = {norm(c["title"]) for c in pool}
        pool += [c for c in tvmaze_cards(service, schedule(*days), 2 * MAX_ITEMS) if norm(c["title"]) not in titles]
    return pool


# ---- Netflix Top 10 -------------------------------------------------------------------------

NETFLIX_TOP10 = "https://www.netflix.com/tudum/top10/data/all-weeks-countries.tsv"
COUNTRIES = {"MY": "Malaysia", "SG": "Singapore", "ID": "Indonesia", "KR": "South Korea", "US": "the US"}


def netflix_top10(country):
    """This week's rows for [country] (ISO code); the file covers every country and week, so it
    is streamed and filtered rather than kept."""
    req = urllib.request.Request(NETFLIX_TOP10, headers={"User-Agent": UA})
    rows = []
    with urllib.request.urlopen(req, timeout=120) as r:
        header = r.readline().decode("utf-8").rstrip("\n").split("\t")
        for raw in r:
            line = raw.decode("utf-8").rstrip("\n").split("\t")
            if len(line) == len(header) and line[header.index("country_iso2")] == country:
                rows.append(dict(zip(header, line)))
    if not rows:
        raise RuntimeError(f"no Top 10 rows for {country}")
    week = max(r["week"] for r in rows)
    return [r for r in rows if r["week"] == week]


def netflix_top10_cards(country, label):
    """The country's Top 10 shows in a random order, for rotate(). Only shows TVmaze has wide art
    for take part (TVmaze has no films)."""
    pool = []
    for row in netflix_top10(country):
        if row["category"] != "TV":
            continue
        title = row["show_title"].strip()
        if not allowed(title, row.get("season_title")):
            continue
        image = programme_picture("series", title, None, None)
        if not image or not allowed(title, about("series", title)):
            continue
        new = row.get("cumulative_weeks_in_top_10") == "1"
        meta = " · ".join(p for p in ("Netflix", f"#{row['weekly_rank']} in TV", "New this week" if new else None) if p)
        pool.append({"title": title[:120], "meta": meta[:180], "image": image, "source": label})
    return random.sample(pool, len(pool))


# ---- YouTube --------------------------------------------------------------------------------

def thumbnail(video_id):
    """The widest picture YouTube has: hq720 (1280x720) for most, the 4:3 one for old videos."""
    for name in ("hq720", "maxresdefault", "hqdefault"):
        url = f"https://i.ytimg.com/vi/{video_id}/{name}.jpg"
        try:
            req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=10) as r:
                if r.status == 200:
                    return url
        except urllib.error.URLError:
            continue
    return None


def duration_text(seconds):
    if not seconds:
        return None
    minutes = round(seconds / 60)
    return f"{minutes} min" if minutes < 60 else f"{minutes // 60} h {minutes % 60} min"


TRAILER_WORDS = re.compile(r"\b(official|final|main|teaser|trailer|clip|opening|ending|pv|preview|full episode|"
                           r"episod penuh|episode|episod|ep|season|s\d+|\d+)\b", re.I)


def show_of(video_title):
    """The show a trailer or episode is from, for the genre lookups: "The Guy She Was Interested In
    Wasn't a Guy at All | Official Trailer | Crunchyroll" -> "The Guy She Was Interested In Wasn't a
    Guy at All". None when the title doesn't name one."""
    parts = [p.strip() for p in re.split(r"\s+[|｜]\s+", video_title) if p.strip()]
    if len(parts) < 2 and not TRAILER_WORDS.search(video_title):
        return None  # an ordinary video, not a show's trailer or episode
    name = re.sub(r"[\[(【][^\])】]*[\])】]", " ", parts[0] if parts else video_title)
    name = re.split(r"\s+[-–:]\s+(?=.*\b(?:trailer|teaser|episode|episod|ep|season)\b)", name, flags=re.I)[0]
    name = re.sub(r"[\s:–-]*\b(?:season|s)\s*\d+\s*$", "", " ".join(name.split()), flags=re.I).strip(" -:#")
    return name if len(norm(name)) >= 3 else None


YOUTUBE_COOKIE = ""  # a Cookie header from --youtube-cookie-file, for YouTube's own pages
HEALTH_FILE = ROOT / "health.json"  # whether YouTube worked on its last run; the workflow alerts on a change
youtube_note = ""  # what youtube.com said the last time the feed came back empty


def cookie_header(path):
    """The youtube.com cookies of a Netscape cookies.txt, as one Cookie header."""
    pairs = []
    for line in pathlib.Path(path).read_text().splitlines():
        fields = line.removeprefix("#HttpOnly_").split("\t")
        if len(fields) >= 7 and not line.startswith("# ") and fields[0].lstrip(".").endswith("youtube.com"):
            pairs.append(f"{fields[5]}={fields[6]}")
    return "; ".join(pairs)


def video_category(video_id):
    """YouTube's category for a video ("Music", "Gaming", "Sports", ...), from its watch page. Signed
    in where cookies were given: YouTube asks servers like GitHub's to prove they aren't bots."""
    headers = {"User-Agent": "Mozilla/5.0 (" + UA + ")", "Accept-Language": "en"}
    if YOUTUBE_COOKIE:
        headers["Cookie"] = YOUTUBE_COOKIE
    req = urllib.request.Request(f"https://www.youtube.com/watch?v={video_id}", headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        found = re.search(r'"category":("[^"]+")', r.read().decode("utf-8", "replace"))
    if not found:  # not remembered as a miss: the next run asks again
        raise RuntimeError("no category on the watch page")
    return json.loads(found.group(1))  # a JSON string: "Science \u0026 Technology"


def youtube_home_state():
    """What youtube.com itself says when the feed is empty: signed in or not, which account and
    channel, which country YouTube places the request in, and whether it is the empty "Try
    searching" page. For the log only."""
    if not YOUTUBE_COOKIE:
        return ""
    try:
        req = urllib.request.Request("https://www.youtube.com/", headers={
            "User-Agent": "Mozilla/5.0 (" + UA + ")", "Accept-Language": "en", "Cookie": YOUTUBE_COOKIE})
        with urllib.request.urlopen(req, timeout=30) as r:
            page = r.read().decode("utf-8", "replace")
    except Exception as e:
        return f" (home page: {e})"
    def field(name):
        found = re.search(r'"%s":("?[^,"}]*"?)' % name, page)
        return found.group(1).strip('"') if found else "?"
    return (f" (home page: logged_in={field('LOGGED_IN')}, channel={'yes' if field('DELEGATED_SESSION_ID') != '?' else 'no'},"
            f" gl={field('GL')}, empty_nudge={'Try searching to get started' in page})")


def video_of(entry):
    """The video id of a home feed entry; a Mix is a playlist "RD" + the id of the video it starts with."""
    raw = (entry or {}).get("id") or ""
    return raw[2:] if raw.startswith("RD") and len(raw) == 13 else raw


def on_shelf(video, before):
    return any(f"/vi/{video}/" in (b.get("image") or "") for b in before or [])


def youtube_cards(cookies, before=None, max_age_days=None, count=None):
    """[count] (MAX_ITEMS) videos of the signed-in YouTube home feed, one per category; [cookies] are
    yt-dlp's cookie options. With [max_age_days], only videos uploaded that recently (YouTube's own
    "3 days ago"), so Mixes and undated videos are left out. Videos that were on the previous shelf
    [before] only come in when too few others are left."""
    # YouTube now and then sends a signed-in home feed with nothing in it ("Try searching to get
    # started"); a second ask a little later usually has the recommendations.
    for attempt in range(2):
        entries = yt_dlp_json(":ytrec", cookies, "--playlist-end", "30",
                              "--extractor-args", "youtubetab:approximate_date").get("entries") or []
        if entries:
            break
        global youtube_note
        youtube_note = youtube_home_state()
        log("youtube: empty home feed" + ("; asking again" if attempt == 0 else "") + youtube_note)
        if attempt == 0:
            time.sleep(20)
    if not entries:
        raise RuntimeError("empty home feed")
    oldest = time.time() - max_age_days * 86400 if max_age_days else None
    entries = sorted((e for e in entries if e), key=lambda e: on_shelf(video_of(e), before))  # stable
    cards, categories = [], set()
    for e in entries:
        raw, title = e.get("id") or "", (e.get("title") or "").strip()
        video = video_of(e)
        mix = video != raw
        if len(video) != 11 or not title:
            continue
        if oldest and (mix or not e.get("timestamp") or e["timestamp"] < oldest):
            continue
        who = e.get("channel") or e.get("uploader")
        if not allowed(title, who, e.get("description")):
            continue
        # A trailer or episode of a show: that show's genres and tags (AniList, TVmaze) too.
        show = None if mix else show_of(title)
        if show and not allowed(title, about("anime", show), about("series", show)):
            continue
        # One of each category, so five music videos don't fill the shelf. Unknown ones pass.
        category = cached(f"ytcat|{video}", lambda: video_category(video)) or ""
        if category and category in categories:
            continue
        image = thumbnail(video)
        if not image:
            continue
        kind = "Mix" if mix else ("Live" if e.get("live_status") == "is_live" or not e.get("duration")
                                  else duration_text(e.get("duration")))
        categories.add(category)
        cards.append({"title": title[:120], "meta": " · ".join(p for p in ("YouTube", who, kind) if p)[:180],
                      "image": image})
        if len(cards) == (count or MAX_ITEMS):
            break
    return cards


def youtube_history_card(cookies, words, before=None):
    """A video from the signed-in watch history whose title or channel holds one of [words] (e.g.
    zikir, al-ma'thurat), at random, one that wasn't on the previous shelf [before] if there is
    one; None when the history has none. One yt-dlp request."""
    entries = yt_dlp_json(":ythistory", cookies, "--playlist-end", "50").get("entries") or []
    wanted = sorted({norm(w) for w in words} - {""})
    found = {}
    for e in entries:
        video, title = video_of(e), ((e or {}).get("title") or "").strip()
        who = e.get("channel") or e.get("uploader") if e else None
        text = f" {norm(title + ' ' + (who or ''))} "
        if len(video) == 11 and title and video not in found and any(f" {w} " in text for w in wanted) \
                and allowed(title, who, e.get("description")):
            found[video] = (title, who, e)
    pool = random.sample(list(found), len(found))
    for video in sorted(pool, key=lambda v: on_shelf(v, before)):
        image = thumbnail(video)
        if image:
            title, who, e = found[video]
            meta = " · ".join(p for p in ("YouTube", who, duration_text(e.get("duration"))) if p)
            return {"title": title[:120], "meta": meta[:180], "image": image}
    return None


# ---- unifi TV -------------------------------------------------------------------------------

# The guide unifi TV's web player (tm-web-ui-cdn.api.tmcms.quickplay.com) reads: no login, the
# player's own parameters. Not a documented API; it may change.
UNIFI_EPG = "https://data-store-cdn.api.tmcms.quickplay.com/content/epg"
UNIFI_IMAGE = "https://image-resizer-cloud-cdn.api.tmcms.quickplay.com/image/{id}/0-16x9.jpg?width=1280"
UNIFI_PARAMS = {"reg": "my", "dt": "web", "client": "tm-unifitv-web", "pf": "regular", "ml": "regular",
                "custseg": "residential", "locale": "en-US", "pageSize": 20}


def http_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def utc(text):
    return dt.datetime.fromisoformat(text.replace("Z", "+00:00"))


def english(names):
    return next((n.get("n") for n in names or [] if n.get("lang") == "en"), None) or ((names or [{}])[0].get("n") or "")


def unifi_guide(start, end):
    """Every channel with its airings between start and end (the guide pages 20 channels)."""
    params = dict(UNIFI_PARAMS, start=start.strftime("%Y-%m-%dT%H:%M:%SZ"), end=end.strftime("%Y-%m-%dT%H:%M:%SZ"))
    channels = []
    for page in range(1, 11):
        body = http_json(UNIFI_EPG + "?" + urllib.parse.urlencode(dict(params, pageNumber=page)))
        header = body.get("header") or {}
        if header.get("code") not in (None, 0) and not body.get("data"):
            raise RuntimeError(f"guide: {header.get('errors') or header.get('message')}")
        channels += body.get("data") or []
        if not body.get("data") or len(channels) >= (header.get("count") or 0):
            break
    return channels


def clock(t):
    return t.strftime("%I:%M %p").lstrip("0")


# ---- programme pictures ---------------------------------------------------------------------

SPORTSDB = "https://www.thesportsdb.com/api/v1/json/123"  # the free public key; rate-limited
LEAGUES = {  # words in a title -> TheSportsDB league, whose fan art stands in when there's no match picture
    "laliga": 4335, "la liga": 4335, "premier league": 4328, "champions league": 4480, "europa league": 4481,
    "formula 1": 4370, "motogp": 4407, "ligue 1": 4334, "serie a": 4332, "bundesliga": 4331,
    "a-league": 4356, "alm": 4356,
}
CACHE_FILE = ROOT / "image_cache.json"
HIT_DAYS, MISS_DAYS = 30, 3
cache = {}


def norm(text):
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).split())


def cached(key, find):
    """[find]'s answer for [key], remembered: pictures for a month, misses for a few days."""
    hit = cache.get(key)
    today = dt.date.today()
    if hit and (today - dt.date.fromisoformat(hit["at"])).days < (HIT_DAYS if hit["url"] else MISS_DAYS):
        return hit["url"]
    try:
        url = find()
    except Exception as e:
        log(f"picture lookup failed for {key!r}: {e}")
        return hit["url"] if hit else None
    cache[key] = {"url": url, "at": today.isoformat()}
    time.sleep(0.6)
    return url


def same_team(ours, theirs):
    a, b = norm(ours), norm(theirs)
    return bool(a and b) and (a == b or a in b or b in a)


def sports_picture(title):
    """The match's own thumbnail when the title names one ("X vs Y"), else the league's fan art."""
    for part in title.split(" - "):
        teams = re.split(r"\s+vs\.?\s+", part, flags=re.I)
        if len(teams) != 2:
            continue
        home, away = (t.strip(" .") for t in teams)
        query = urllib.parse.quote(f"{home}_vs_{away}".replace(" ", "_"))
        events = http_json(f"{SPORTSDB}/searchevents.php?e={query}").get("event") or []
        today = dt.date.today()
        for e in sorted(events, key=lambda e: abs((dt.date.fromisoformat(e.get("dateEvent") or "1970-01-01") - today).days)):
            near = abs((dt.date.fromisoformat(e.get("dateEvent") or "1970-01-01") - today).days) <= 10
            if near and e.get("strThumb") and same_team(home, e.get("strHomeTeam")) and same_team(away, e.get("strAwayTeam")):
                return e["strThumb"]
    words = f" {norm(title)} "
    for name, league in LEAGUES.items():
        if f" {norm(name)} " in words:
            info = (http_json(f"{SPORTSDB}/lookupleague.php?id={league}").get("leagues") or [{}])[0]
            return info.get("strFanart1") or info.get("strFanart2") or info.get("strBanner")
    return None


def anime_picture(title):
    """AniList's wide banner, when one of the show's names is the title."""
    body = json.dumps({"query": "query($q:String){Media(search:$q,type:ANIME){title{romaji english native} synonyms bannerImage}}",
                       "variables": {"q": title}}).encode()
    req = urllib.request.Request("https://graphql.anilist.co", data=body,
                                 headers={"Content-Type": "application/json", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        media = (json.load(r).get("data") or {}).get("Media") or {}
    names = [n for n in (media.get("title") or {}).values() if n] + (media.get("synonyms") or [])
    return media.get("bannerImage") if any(norm(n) == norm(title) for n in names) else None


def series_picture(title):
    """TVmaze's wide art for the show of that exact name."""
    try:
        show = tvmaze(f"/singlesearch/shows?q={urllib.parse.quote(title)}&embed=images")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    if norm(show.get("name")) != norm(title):
        return None
    images = show.get("_embedded", {}).get("images") or []
    for i in sorted(images, key=lambda i: (i.get("type") != "background", not i.get("main"))):
        o = i.get("resolutions", {}).get("original") or {}
        w, h = o.get("width") or 0, o.get("height") or 0
        if o.get("url") and w >= 960 and h and 1.3 <= w / h <= 2.4:
            return o["url"]
    return None


def youtube_picture(title, channel, cookies):
    """The thumbnail of a YouTube video whose title contains the programme's whole name."""
    if not cookies:
        return None
    run = subprocess.run(["yt-dlp", *cookies, "--flat-playlist", "-J", "--no-warnings", f"ytsearch5:{title} {channel}"],
                         capture_output=True, text=True, timeout=180)
    if run.returncode != 0:
        raise RuntimeError(run.stderr.strip().splitlines()[-1] if run.stderr.strip() else "yt-dlp failed")
    want = norm(re.sub(r"\b(19|20)\d\d\b", "", title))  # "SUMBANG SUARA 2022": the year rarely appears
    for e in json.loads(run.stdout).get("entries") or []:
        if e and len(e.get("id") or "") == 11 and want and want in norm(e.get("title")):
            return thumbnail(e["id"])
    return None


def series_about(title):
    """TVmaze's genres and summary for the show of that exact name ("" when there is none)."""
    try:
        show = tvmaze(f"/singlesearch/shows?q={urllib.parse.quote(title)}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return ""
        raise
    if norm(show.get("name")) != norm(title):
        return ""
    return " ".join([*(show.get("genres") or []), plain(show.get("summary"))]).strip()


def anime_about(title):
    """AniList's genres, tags (e.g. "Boys' Love", "LGBTQ+ Themes") and description."""
    body = json.dumps({"query": "query($q:String){Media(search:$q,type:ANIME){title{romaji english native} synonyms "
                                "genres tags{name} description}}", "variables": {"q": title}}).encode()
    req = urllib.request.Request("https://graphql.anilist.co", data=body,
                                 headers={"Content-Type": "application/json", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            media = (json.load(r).get("data") or {}).get("Media") or {}
    except urllib.error.HTTPError as e:
        if e.code == 404:  # AniList's answer when nothing matches
            return ""
        raise
    names = [n for n in (media.get("title") or {}).values() if n] + (media.get("synonyms") or [])
    if not any(norm(n) == norm(title) for n in names):
        return ""
    return " ".join([*(media.get("genres") or []), *(t["name"] for t in media.get("tags") or []),
                     plain(media.get("description"))]).strip()


def about(kind, title):
    """Genres and description for the "never" check, where [kind]'s source has them."""
    if kind == "series":
        return cached(f"about|series|{norm(title)}", lambda: series_about(title)) or ""
    if kind == "anime":
        return cached(f"about|anime|{norm(title)}", lambda: anime_about(title)) or ""
    return ""


def programme_picture(kind, title, channel, cookies):
    if kind == "sports":
        return cached(f"sports|{norm(title)}", lambda: sports_picture(title))
    if kind == "anime":
        return cached(f"anime|{norm(title)}", lambda: anime_picture(title))
    if kind == "series":
        return cached(f"series|{norm(title)}", lambda: series_picture(title))
    if kind == "youtube" and cookies:
        return cached(f"youtube|{norm(channel)}|{norm(title)}", lambda: youtube_picture(title, channel, cookies))
    return None


def unifi_cards(source, cookies=None):
    """Per channel, the programme on now (skipping filler), or a live event starting within half an
    hour, and with "per_channel" the ones after it; live events first, then the channels in the
    order given."""
    tz = zoneinfo.ZoneInfo(source.get("timezone", "Asia/Kuala_Lumpur"))
    skip = [s.lower() for s in source.get("skip", [])]
    now = dt.datetime.now(dt.timezone.utc)
    guide = unifi_guide(now.replace(minute=0, second=0, microsecond=0), now + dt.timedelta(hours=4))
    by_name = {english(c.get("lon")).strip().lower(): c for c in guide}
    live, rest = [], []

    def add_card(channel, wanted, start, end, title, order):
        is_live = title.startswith("(L)")
        title = title.removeprefix("(L)").strip()
        when = (f"Now until {clock(end.astimezone(tz))}" if start <= now
                else f"{clock(start.astimezone(tz))} – {clock(end.astimezone(tz))}")
        name = english(channel.get("lon"))
        meta = " · ".join(p for p in (name, "Live" if is_live else None, when) if p)
        kind = next((k for k, names in source.get("images", {}).items()
                     if wanted.strip().lower() in (n.lower() for n in names)), None)
        if not allowed(title, about(kind, title)):
            return
        image = (programme_picture(kind, title, name, cookies) if kind else None) or UNIFI_IMAGE.format(id=channel["cid"])
        card = {"title": title[:120], "meta": meta[:180], "image": image}
        if start > now:  # a live event about to start, or with "per_channel" one coming later
            card["source"] = "Starting soon" if is_live else "Coming up"
        (live if is_live else rest).append((order, card))

    for index, wanted in enumerate(source["unifi"]):
        channel = by_name.get(wanted.strip().lower())
        if not channel:
            log(f"unifi: no channel called {wanted!r}")
            continue
        options = []
        for airing in sorted(channel.get("airing") or [], key=lambda a: a.get("sc_st_dt", "")):
            start, end = utc(airing["sc_st_dt"]), utc(airing["sc_ed_dt"])
            pgm = airing.get("pgm") or {}
            title = english(pgm.get("lon")).strip()
            if end <= now or not title or any(s in title.lower() for s in skip):
                continue
            # The guide's own genres ("log") and description ("lod").
            genres = " ".join(n for g in pgm.get("log") or [] for n in (g.get("n") or []))
            if not allowed(title, genres, english(pgm.get("lod")), english(pgm.get("losetl"))):
                continue
            options.append((start, end, title))
        if not options:
            continue
        soon_live = [o for o in options if o[2].startswith("(L)") and o[0] - now <= dt.timedelta(minutes=30)]
        # Never a later programme as if it were on now: a channel with nothing on (an off-air gap,
        # or what's on was skipped) has no card unless a live event starts within half an hour.
        on_now = [o for o in options if o[0] <= now]
        first = soon_live[0] if soon_live else on_now[0] if on_now else None
        if not first:
            continue
        later = [o for o in options if o[0] > first[0]][:source.get("per_channel", 1) - 1]
        for step, (start, end, title) in enumerate([first] + later):
            add_card(channel, wanted, start, end, title, (step, index))
    # Live first; then each channel's show on now, then each one's next, and so on.
    return [card for _, card in sorted(live, key=lambda c: c[0]) + sorted(rest, key=lambda c: c[0])][:MAX_ITEMS]


# ---- a service's YouTube playlists ------------------------------------------------------------

TEASER = re.compile(r"\b(teaser|trailer|coming soon|akan datang)\b", re.I)
EPISODE = re.compile(r"\b(?:episod|episode|ep)\s*\.?\s*(\d+)", re.I)


def yt_dlp_json(url, cookies, *extra):
    run = subprocess.run(["yt-dlp", *(cookies or []), "--flat-playlist", "-J", "--no-warnings", *extra, url],
                         capture_output=True, text=True, timeout=300)
    if run.returncode != 0:
        raise RuntimeError(run.stderr.strip().splitlines()[-1] if run.stderr.strip() else "yt-dlp failed")
    return json.loads(run.stdout)


def video_label(title):
    """"#BayanganDendam : EPISOD 3 | #ViuMalaysia" -> "Episode 3"; teasers and trailers -> "Coming soon"."""
    found = EPISODE.search(title)
    if found:
        return f"Episode {int(found.group(1))}"
    return "Coming soon" if TEASER.search(title) else None


def playlist_cards(source, cookies, before=None):
    """"playlists" (3) of the channel's most recently updated show playlists and two of the newest
    videos of each, taking turns between the shows. Shows and videos that weren't on the previous
    shelf [before] come first: the shows from the 6 most recently updated, the videos from each
    show's newest "depth" (4). One yt-dlp request for the list, one per playlist."""
    channel = source["youtube_playlists"].lstrip("/")
    # sort=lad: by the last video added, the channel's own "Last video added" order.
    listing = yt_dlp_json(f"https://www.youtube.com/{channel}/playlists?view=1&sort=lad", cookies, "--playlist-end", "12")
    skip = [s.lower() for s in source.get("skip", [])]
    service = source.get("service", "")
    candidates, seen = [], set()
    for p in listing.get("entries") or []:
        name = " ".join(((p or {}).get("title") or "").split())
        # "#ViuandiQIYI", "#ViuEventHighlights": hashtag playlists are collections, not shows.
        if not name or name.startswith("#") or any(s in name.lower() for s in skip) or norm(name) in seen:
            continue
        seen.add(norm(name))
        candidates.append((p, name))
    # Of the twice as many most recently updated shows, those not on the previous shelf first, so
    # the shows take turns without asking yt-dlp for more playlists.
    shelf_shows = {norm(b.get("title")) for b in before or []}
    candidates = sorted(candidates[:2 * source.get("playlists", 3)], key=lambda c: norm(c[1]) in shelf_shows) \
        + candidates[2 * source.get("playlists", 3):]
    shows = []
    for p, name in candidates:
        if not allowed(name, about("series", name)):
            continue
        videos = []
        for e in yt_dlp_json(f"https://www.youtube.com/playlist?list={p['id']}", cookies).get("entries") or []:
            title = (e or {}).get("title") or ""
            if len((e or {}).get("id") or "") == 11 and title and not any(s in title.lower() for s in skip) \
                    and allowed(name, title, e.get("description")):
                videos.append(e)
        # Playlists run either way; the highest episode number is the newest, else the first video.
        def episode(e):
            found = EPISODE.search(e["title"])
            return int(found.group(1)) if found else -1
        newest = sorted(videos, key=episode, reverse=True) if any(episode(e) >= 0 for e in videos) else videos
        recent = newest[:source.get("depth", 4)]
        cards = []
        for e in sorted(recent, key=lambda e: on_shelf(e["id"], before)) + newest[len(recent):]:
            image = thumbnail(e["id"])
            if image:
                meta = " · ".join(x for x in (service, video_label(e["title"])) if x)
                cards.append({"title": name[:120], "meta": meta[:180], "image": image})
            if len(cards) == 2:
                break
        if cards:
            shows.append(cards)
        if len(shows) == source.get("playlists", 3):
            break
    # Each show's newest first, then each one's second.
    return [c for step in range(2) for cards in shows for c in cards[step:step + 1]][:MAX_ITEMS]


# ---- Viu ------------------------------------------------------------------------------------

VIU_HOME = "https://www.viu.com/ott/{country}/en"


def viu_cards(country, row="Top 10"):
    """The shows in a row of Viu's home page (its "Top 10" by default) in a random order, for
    rotate(). The page carries its rows as JSON (__NEXT_DATA__), so one fetch does."""
    req = urllib.request.Request(VIU_HOME.format(country=country), headers={"User-Agent": "Mozilla/5.0 (" + UA + ")"})
    with urllib.request.urlopen(req, timeout=60) as r:
        page = r.read().decode("utf-8", "replace")
    found = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page, re.S)
    if not found:
        raise RuntimeError("no __NEXT_DATA__ on Viu's home page")
    home = json.loads(found.group(1))["props"]["pageProps"]["fallback"]["HOME_INDEX"]["data"]
    grid = next((g for g in home.get("grid") or [] if norm(g.get("name")) == norm(row)), None)
    if not grid:
        raise RuntimeError(f"no {row!r} row on Viu's home page")
    # Air times ("Tue - Wed | 12PM") sit on the banner and on rows like "Highlight", not on the Top 10.
    airs = {}
    for show in home.get("banner") or []:
        if show.get("series_update_cycle_description") and "|" in show["series_update_cycle_description"]:
            airs[norm(show.get("series_name"))] = show["series_update_cycle_description"]
    for g in home.get("grid") or []:
        for show in g.get("product") or []:
            t = (show.get("title") or "").strip()
            if re.match(r"(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b", t) and "|" in t:
                airs.setdefault(norm(show.get("series_name")), t)
    pool = []
    for rank, show in enumerate(grid.get("product") or [], 1):
        name = (show.get("series_name") or "").strip()
        image = show.get("cover_landscape_image_url") or show.get("cover_image_url")
        if not name or not image or not allowed(name, show.get("title"), show.get("synopsis"), show.get("series_category_name")):
            continue
        when = airs.get(norm(name), "").replace(" | ", " ")
        meta = " · ".join(p for p in ("Viu", f"#{rank} in {row}", show.get("series_category_name"), when) if p)
        pool.append({"title": name[:120], "meta": meta[:180], "image": image})
    return random.sample(pool, len(pool))


# ---- RTMKlik --------------------------------------------------------------------------------

# The content API and image server RTMKlik's TV app reads (rtmklik.rtm.gov.my itself refuses scripts).
RTM_CONTENT = "https://rtm.glueapi.io/v3/content?idSchemas={schema}&sort=dateAvailability&idApp=5"
RTM_IMAGE = "https://rtm-images.glueapi.io/1280x720/{path}"
RTM_SPECIALS, RTM_CHANNELS = 2012, 2001


def rtm_items(schema):
    return http_json(RTM_CONTENT.format(schema=schema)).get("data") or []


def rtm_image(item):
    images = (item.get("data") or {}).get("images") or {}
    path = next(((images.get(k) or {}).get("path") for k in ("title", "thumbnail", "watermark") if (images.get(k) or {}).get("path")), None)
    return RTM_IMAGE.format(path=path) if path else None


def rtmklik_cards(source, cookies):
    """Saluran Khas first (live events), then the channel cards asked for, then TV1/TV2 now."""
    cards = []
    specials = [i for i in rtm_items(RTM_SPECIALS)
                if allowed(i.get("title"), ((i.get("data") or {}).get("description") or ""))]
    for item in specials[:source.get("max_specials", 2)]:
        if rtm_image(item):
            cards.append({"title": (item.get("title") or "").strip()[:120], "meta": "RTMKlik · Saluran Khas · Live",
                          "image": rtm_image(item)})
    if source.get("channels"):
        channels = {(i.get("title") or "").strip().lower(): i for i in rtm_items(RTM_CHANNELS)}
        for name in source["channels"]:
            item = channels.get(name.strip().lower())
            if not item or not rtm_image(item):
                log(f"rtmklik: no channel called {name!r}")
                continue
            about = ((item.get("data") or {}).get("description") or "").strip()
            cards.append({"title": item["title"].strip()[:120], "meta": " · ".join(p for p in ("RTMKlik · Live", about) if p)[:180],
                          "image": rtm_image(item)})
    if source.get("guide"):
        cards += unifi_cards(source["guide"], cookies)
    return cards[:MAX_ITEMS]


# ---- main -----------------------------------------------------------------------------------

def write_atomically(path, text):
    """A web server may be reading the file: replace it in one step."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".shelf-", suffix=".json")
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=pathlib.Path, default=ROOT / "shelf.json")
    ap.add_argument("--youtube-cookies", metavar="BROWSER",
                    help='browser to read YouTube cookies from, as yt-dlp names it (e.g. "chrome:Default"); '
                         "without it (or --youtube-cookie-file) YouTube apps are left out")
    ap.add_argument("--youtube-cookie-file", metavar="FILE", help="Netscape cookies.txt holding youtube.com cookies")
    ap.add_argument("--only", metavar="KINDS",
                    help='rebuild only apps with these sources, comma-separated (e.g. "unifi,rtmklik"); '
                         "the other apps keep their cards from the previous output")
    args = ap.parse_args()
    cookies = (["--cookies-from-browser", args.youtube_cookies] if args.youtube_cookies
               else ["--cookies", args.youtube_cookie_file] if args.youtube_cookie_file else None)

    global YOUTUBE_COOKIE
    if args.youtube_cookie_file:
        YOUTUBE_COOKIE = cookie_header(args.youtube_cookie_file)
    cfg = json.loads((ROOT / "config.json").read_text())
    global MAX_ITEMS, MIN_WIDE
    MAX_ITEMS = max(1, min(12, int(cfg.get("max_cards", MAX_ITEMS))))
    MIN_WIDE = min(MIN_WIDE, MAX_ITEMS)
    global NEVER
    NEVER = sorted({norm(w) for words in (cfg.get("never") or {}).values() for w in words} - {""})
    try:
        previous = json.loads(args.out.read_text())
        previous = previous if isinstance(previous, dict) else {}
    except (OSError, ValueError):
        previous = {}

    global cache
    try:
        cache = json.loads(CACHE_FILE.read_text())
    except (OSError, ValueError):
        cache = {}
    feed = {}
    only = {k.strip() for k in args.only.split(",") if k.strip()} if args.only else None
    youtube_tried, youtube_health = False, None
    for pkg, source in cfg["apps"].items():
        # The frequent run refreshes what's on TV now; everything else stays as the full run left it.
        if only is not None and not only & set(source):
            if previous.get(pkg):
                feed[pkg] = previous[pkg]
            continue
        # The streaming apps choose against what they showed last time, so each run differs from the
        # last (rotate()); live TV shows what's on, however often that repeats.
        before = previous.get(pkg) or []
        try:
            if "netflix_top10" in source:
                code = source["netflix_top10"]
                top10 = netflix_top10_cards(code, source.get("label", f"Top 10 in {COUNTRIES.get(code, code)}"))
                # New Netflix episodes add to the choice when too few of the Top 10 are new to the shelf.
                cards = [c if "source" in c else dict(c, source="New on Netflix")
                         for c in rotate(tvmaze_pool("Netflix", cfg, before, top10), before)]
            elif "tvmaze" in source:
                cards = [dict(c, source=source.get("label", f"New on {source['tvmaze']}"))
                         for c in rotate(tvmaze_pool(source["tvmaze"], cfg, before), before)]
            elif "youtube_playlists" in source:
                cards = [dict(c, source=source.get("label", f"New on {source.get('service', 'YouTube')}"))
                         for c in playlist_cards(source, cookies, before)]
            elif "viu" in source:
                cards = [dict(c, source=source.get("label", "Top 10 on Viu"))
                         for c in rotate(viu_cards(source["viu"], source.get("row", "Top 10")), before)]
            elif "rtmklik" in source:
                cards = [dict({"source": source.get("label", "On RTMKlik")}, **c) for c in rtmklik_cards(source["rtmklik"], cookies)]
            elif "unifi" in source:
                cards = [dict({"source": source.get("label", "On TV now")}, **c) for c in unifi_cards(source, cookies)]
            elif "youtube" in source:
                if not cookies:
                    log(f"{pkg}: skipped (no YouTube cookies given)")
                    continue
                youtube_tried = True
                # With "islamic", one card is a video from the watch history matching those words, in
                # a random place among the recommendations; without one there, last run's stays.
                words = source.get("islamic")
                cards = [dict(c, source=source.get("label", "Recommended for you"))
                         for c in youtube_cards(cookies, before, source.get("max_age_days"), MAX_ITEMS - bool(words))]
                if words:
                    try:
                        pick = youtube_history_card(cookies, words, before)
                    except Exception as e:
                        log(f"{pkg}: watch history failed ({e})")
                        pick = None
                    pick = (dict(pick, source=source.get("islamic_label", "Watched before")) if pick else
                            next((c for c in before if c.get("source") == source.get("islamic_label", "Watched before")
                                  and allowed(c.get("title"), c.get("meta"))), None))
                    cards = [c for c in cards if not pick or c["image"] != pick["image"]]
                    if pick:
                        cards.insert(random.randint(0, len(cards)), pick)
            else:
                log(f"{pkg}: unknown source {source}")
                continue
            if not cards:
                raise RuntimeError("no cards")
            feed[pkg] = cards
            if "youtube" in source:
                youtube_health = {"ok": True}
            log(f"{pkg}: {len(cards)} cards")
        except Exception as e:  # keep what the TV already had
            log(f"{pkg}: failed ({e}); keeping its previous cards")
            if "youtube" in source:
                signed_out = "logged_in=false" in youtube_note
                youtube_health = {"ok": False, "signed_out": signed_out, "detail": f"{e}{youtube_note}"}
            kept = [c for c in previous.get(pkg) or [] if allowed(c.get("title"), c.get("meta"))]
            if kept:
                feed[pkg] = kept[:MAX_ITEMS]

    # YouTube's state for the workflow, which tells the owner (Telegram) when it changes. Runs that
    # didn't ask YouTube leave the last state alone.
    if youtube_tried and youtube_health is not None:
        write_atomically(HEALTH_FILE, json.dumps({"youtube": youtube_health}, indent=1) + "\n")

    # Expired entries would be looked up again anyway; dropping them keeps the file from growing.
    today = dt.date.today()
    cache = {k: v for k, v in cache.items()
             if (today - dt.date.fromisoformat(v["at"])).days < HIT_DAYS and not k.startswith("category|")}
    cache_text = json.dumps(dict(sorted(cache.items())), ensure_ascii=False, indent=1) + "\n"
    if not CACHE_FILE.exists() or CACHE_FILE.read_text() != cache_text:
        write_atomically(CACHE_FILE, cache_text)
    text = json.dumps(feed, ensure_ascii=False, indent=2) + "\n"
    if args.out.exists() and args.out.read_text() == text:
        log("unchanged")
        return 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_atomically(args.out, text)
    log(f"wrote {args.out}")
    return 0 if feed else 1


if __name__ == "__main__":
    sys.exit(main())
