#!/usr/bin/env python3
"""Builds shelf.json for Tigris's custom Top Shelf.

The feed is a JSON object keyed by Android TV app package; each value is a list of at most 12
{title, meta, image} cards, where image is an http(s) URL. Tigris shows a package's cards when
that app's tile is focused in the first row. Sources (config.json):

  {"tvmaze": "<service>"}   new and upcoming episodes on a streaming service, from TVmaze's
                            schedule; no account needed
  {"netflix_top10": "MY"}   a random handful of Netflix's official weekly Top 10 shows for a
                            country (top10.netflix.com) that TVmaze has pictures for, a new draw
                            every run; new Netflix episodes (as "tvmaze") fill any free places
  {"youtube": "recommended"} the signed-in YouTube home feed, through yt-dlp; only with
                            --youtube-cookies (a browser) or --youtube-cookie-file
  {"rtmklik": {...}}        RTMKlik: its special live channels (Saluran Khas), chosen channel cards
                            (RTMKlik publishes no schedule) and, from the unifi TV guide, what's on
                            TV1/TV2 now
  {"unifi": [channels]}     what's on now (or next) on these unifi TV channels, from the same
                            public programme guide unifi TV's web player reads; live events first.
                            "images" says where each channel's programme pictures come from
                            (sports: TheSportsDB, anime: AniList, series: TVmaze, youtube: a
                            YouTube search); the channel logo stays the fallback

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


def tvmaze_cards(service, schedule):
    """One card per show: today first, then the latest releases, then the soonest coming."""
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
        image, is_wide = show_image(show, ep)
        time.sleep(0.6)
        if not image or not image.startswith("http"):
            continue
        card = {"title": show["name"][:120], "meta": episode_meta(service, ep, drops[show["id"], day], day, today)[:180],
                "image": image}
        (wide if is_wide else posters).append(card)
        if len(wide) == MAX_ITEMS:
            break
    return (wide + (posters if len(wide) < MIN_WIDE else []))[:MAX_ITEMS]


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
    """MAX_ITEMS of the country's Top 10 shows, drawn at random so the shelf rotates. Only shows
    TVmaze has wide art for take part (TVmaze has no films)."""
    pool = []
    for row in netflix_top10(country):
        if row["category"] != "TV":
            continue
        title = row["show_title"].strip()
        image = programme_picture("series", title, None, None)
        if not image:
            continue
        new = row.get("cumulative_weeks_in_top_10") == "1"
        meta = " · ".join(p for p in ("Netflix", f"#{row['weekly_rank']} in TV", "New this week" if new else None) if p)
        pool.append({"title": title[:120], "meta": meta[:180], "image": image, "source": label})
    return random.sample(pool, min(MAX_ITEMS, len(pool)))


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


def youtube_cards(cookies):
    """The signed-in YouTube home feed; [cookies] are yt-dlp's cookie options."""
    run = subprocess.run(
        ["yt-dlp", *cookies, "--flat-playlist", "-J", "--playlist-end", "30", "--no-warnings", ":ytrec"],
        capture_output=True, text=True, timeout=300,
    )
    if run.returncode != 0:
        raise RuntimeError(run.stderr.strip().splitlines()[-1] if run.stderr.strip() else f"yt-dlp exit {run.returncode}")
    cards = []
    for e in json.loads(run.stdout).get("entries") or []:
        if not e:
            continue
        raw, title = e.get("id") or "", (e.get("title") or "").strip()
        # A Mix is a playlist "RD" + the id of the video it starts with.
        mix = raw.startswith("RD") and len(raw) == 13
        video = raw[2:] if mix else raw
        if len(video) != 11 or not title:
            continue
        image = thumbnail(video)
        if not image:
            continue
        who = e.get("channel") or e.get("uploader")
        kind = "Mix" if mix else ("Live" if e.get("live_status") == "is_live" or not e.get("duration")
                                  else duration_text(e.get("duration")))
        cards.append({"title": title[:120], "meta": " · ".join(p for p in ("YouTube", who, kind) if p)[:180],
                      "image": image})
        if len(cards) == MAX_ITEMS:
            break
    return cards


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
        image = (programme_picture(kind, title, name, cookies) if kind else None) or UNIFI_IMAGE.format(id=channel["cid"])
        (live if is_live else rest).append((order, {"title": title[:120], "meta": meta[:180], "image": image}))

    for index, wanted in enumerate(source["unifi"]):
        channel = by_name.get(wanted.strip().lower())
        if not channel:
            log(f"unifi: no channel called {wanted!r}")
            continue
        options = []
        for airing in sorted(channel.get("airing") or [], key=lambda a: a.get("sc_st_dt", "")):
            start, end = utc(airing["sc_st_dt"]), utc(airing["sc_ed_dt"])
            title = english((airing.get("pgm") or {}).get("lon")).strip()
            if end <= now or not title or any(s in title.lower() for s in skip):
                continue
            options.append((start, end, title))
        if not options:
            continue
        soon_live = [o for o in options if o[2].startswith("(L)") and o[0] - now <= dt.timedelta(minutes=30)]
        first = soon_live[0] if soon_live else options[0]
        later = [o for o in options if o[0] > first[0]][:source.get("per_channel", 1) - 1]
        for step, (start, end, title) in enumerate([first] + later):
            add_card(channel, wanted, start, end, title, (step, index))
    # Live first; then each channel's show on now, then each one's next, and so on.
    return [card for _, card in sorted(live, key=lambda c: c[0]) + sorted(rest, key=lambda c: c[0])][:MAX_ITEMS]


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
    for item in rtm_items(RTM_SPECIALS)[:source.get("max_specials", 2)]:
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
    args = ap.parse_args()
    cookies = (["--cookies-from-browser", args.youtube_cookies] if args.youtube_cookies
               else ["--cookies", args.youtube_cookie_file] if args.youtube_cookie_file else None)

    cfg = json.loads((ROOT / "config.json").read_text())
    global MAX_ITEMS, MIN_WIDE
    MAX_ITEMS = max(1, min(12, int(cfg.get("max_cards", MAX_ITEMS))))
    MIN_WIDE = min(MIN_WIDE, MAX_ITEMS)
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
    feed, schedule = {}, None
    for pkg, source in cfg["apps"].items():
        try:
            if "netflix_top10" in source:
                code = source["netflix_top10"]
                cards = netflix_top10_cards(code, source.get("label", f"Top 10 in {COUNTRIES.get(code, code)}"))
                if len(cards) < MAX_ITEMS:  # fill up with new episodes
                    if schedule is None:
                        schedule = tvmaze_schedule(cfg.get("days_back", 7), cfg.get("days_ahead", 7))
                    seen = {norm(c["title"]) for c in cards}
                    cards += [dict(c, source="New on Netflix") for c in tvmaze_cards("Netflix", schedule)
                              if norm(c["title"]) not in seen][:MAX_ITEMS - len(cards)]
            elif "tvmaze" in source:
                if schedule is None:
                    schedule = tvmaze_schedule(cfg.get("days_back", 7), cfg.get("days_ahead", 7))
                cards = [dict(c, source=source.get("label", f"New on {source['tvmaze']}")) for c in tvmaze_cards(source["tvmaze"], schedule)]
            elif "rtmklik" in source:
                cards = [dict(c, source=source.get("label", "On RTMKlik")) for c in rtmklik_cards(source["rtmklik"], cookies)]
            elif "unifi" in source:
                cards = [dict(c, source=source.get("label", "On TV now")) for c in unifi_cards(source, cookies)]
            elif "youtube" in source:
                if not cookies:
                    log(f"{pkg}: skipped (no YouTube cookies given)")
                    continue
                cards = [dict(c, source=source.get("label", "Recommended for you")) for c in youtube_cards(cookies)]
            else:
                log(f"{pkg}: unknown source {source}")
                continue
            if not cards:
                raise RuntimeError("no cards")
            feed[pkg] = cards
            log(f"{pkg}: {len(cards)} cards")
        except Exception as e:  # keep what the TV already had
            log(f"{pkg}: failed ({e}); keeping {len(previous.get(pkg) or [])} previous cards")
            if previous.get(pkg):
                feed[pkg] = previous[pkg][:MAX_ITEMS]

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
