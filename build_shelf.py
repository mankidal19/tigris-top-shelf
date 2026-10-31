#!/usr/bin/env python3
"""Builds shelf.json for Tigris's custom Top Shelf.

The feed is a JSON object keyed by Android TV app package; each value is a list of at most 12
{title, meta, image} cards, where image is an http(s) URL. Tigris shows a package's cards when
that app's tile is focused in the first row. Sources (config.json):

  {"tvmaze": "<service>"}   new and upcoming episodes on a streaming service, from TVmaze's
                            schedule; no account needed
  {"youtube": "recommended"} the signed-in YouTube home feed, through yt-dlp; only with
                            --youtube-cookies (a browser) or --youtube-cookie-file
  {"unifi": [channels]}     what's on now (or next) on these unifi TV channels, from the same
                            public programme guide unifi TV's web player reads; live events first

The shelf is a full-width slideshow, so wide pictures are preferred everywhere. An app whose
source fails keeps the cards it had in the previous output. Standard library plus yt-dlp.
"""
import argparse
import datetime as dt
import json
import os
import pathlib
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


def unifi_cards(source):
    """Per channel, the programme on now (skipping filler), or a live event starting within half an
    hour; live events first, then the channels in the order given."""
    tz = zoneinfo.ZoneInfo(source.get("timezone", "Asia/Kuala_Lumpur"))
    skip = [s.lower() for s in source.get("skip", [])]
    now = dt.datetime.now(dt.timezone.utc)
    guide = unifi_guide(now.replace(minute=0, second=0, microsecond=0), now + dt.timedelta(hours=4))
    by_name = {english(c.get("lon")).strip().lower(): c for c in guide}
    live, rest = [], []
    for wanted in source["unifi"]:
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
        # The show on now, unless a live event starts within half an hour.
        soon_live = [o for o in options if o[2].startswith("(L)") and o[0] - now <= dt.timedelta(minutes=30)]
        start, end, title = soon_live[0] if soon_live else options[0]
        is_live = title.startswith("(L)")
        title = title.removeprefix("(L)").strip()
        when = (f"Now until {clock(end.astimezone(tz))}" if start <= now
                else f"{clock(start.astimezone(tz))} – {clock(end.astimezone(tz))}")
        meta = " · ".join(p for p in (english(channel.get("lon")), "Live" if is_live else None, when) if p)
        card = {"title": title[:120], "meta": meta[:180], "image": UNIFI_IMAGE.format(id=channel["cid"])}
        (live if is_live else rest).append(card)
    return (live + rest)[:MAX_ITEMS]


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

    feed, schedule = {}, None
    for pkg, source in cfg["apps"].items():
        try:
            if "tvmaze" in source:
                if schedule is None:
                    schedule = tvmaze_schedule(cfg.get("days_back", 7), cfg.get("days_ahead", 7))
                cards = tvmaze_cards(source["tvmaze"], schedule)
            elif "unifi" in source:
                cards = unifi_cards(source)
            elif "youtube" in source:
                if not cookies:
                    log(f"{pkg}: skipped (no YouTube cookies given)")
                    continue
                cards = youtube_cards(cookies)
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
