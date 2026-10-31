#!/usr/bin/env python3
"""Builds shelf.json for Tigris's custom Top Shelf from TVmaze's streaming schedule.

Tigris wants a JSON array of at most 12 {title, meta, image} objects, where image is an
http(s) URL. The shelf is a full-width slideshow, so landscape show art is preferred over
posters. Standard library only; settings live in config.json.
"""
import datetime as dt
import json
import pathlib
import sys
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
API = "https://api.tvmaze.com"
MAX_ITEMS = 12  # Tigris drops anything past 12
MIN_WIDE = 6  # below this many shows with wide art, posters fill the shelf up


def get(path):
    req = urllib.request.Request(API + path, headers={"User-Agent": "tigris-top-shelf (github.com)"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 2:  # TVmaze allows 20 calls per 10 s
                raise
            time.sleep(5)


def landscape_image(show, episode):
    """Wide art first: the slideshow is full-width, so a poster or a thin banner crops badly.

    Background art, then any other wide image of the show, then the episode's still, and the
    poster only when nothing else exists.
    """
    try:
        images = get(f"/shows/{show['id']}/images")
    except Exception:
        images = []

    def wide(i):
        o = i.get("resolutions", {}).get("original") or {}
        w, h = o.get("width") or 0, o.get("height") or 0
        return o.get("url") if w >= 960 and h and 1.3 <= w / h <= 2.4 else None

    ranked = sorted(images, key=lambda i: (i.get("type") != "background", not i.get("main")))
    for i in ranked:
        if wide(i):
            return wide(i), True
    still = (episode.get("image") or {}).get("original")
    if still:
        return still, True
    return (show.get("image") or {}).get("original"), False


def meta_line(network, episode, count, day, today):
    parts = [network]
    if count > 1 and episode.get("season"):
        parts.append(f"S{episode['season']} · {count} episodes")  # a whole batch dropped at once
    elif episode.get("season") and episode.get("number"):
        parts.append(f"S{episode['season']} E{episode['number']}")
    when = "New today" if day == today else (f"Out {day:%a %-d %b}" if day < today else f"Coming {day:%a %-d %b}")
    parts.append(when)
    return " · ".join(parts)


def main():
    cfg = json.loads((ROOT / "config.json").read_text())
    network = cfg["network"]
    today = dt.date.today()
    newest = {}  # show id -> (day, show, episode); the latest episode in the window wins
    drops = {}  # (show id, day) -> episodes released that day
    for offset in range(-cfg.get("days_back", 7), cfg.get("days_ahead", 7) + 1):
        day = today + dt.timedelta(days=offset)
        for ep in get(f"/schedule/web?date={day}"):
            show = ep.get("_embedded", {}).get("show") or {}
            channel = (show.get("webChannel") or show.get("network") or {}).get("name")
            if channel != network:
                continue
            drops[show["id"], day] = drops.get((show["id"], day), 0) + 1
            if show["id"] not in newest or day >= newest[show["id"]][0]:
                newest[show["id"]] = (day, show, ep)
        time.sleep(0.6)

    # Today first, then what came out most recently, then what is coming soonest.
    def order(entry):
        day = entry[0]
        return (0, 0) if day == today else ((1, (today - day).days) if day < today else (2, (day - today).days))

    wide, posters = [], []
    for day, show, ep in sorted(newest.values(), key=order):
        image, is_wide = landscape_image(show, ep)
        time.sleep(0.6)
        if not image or not image.startswith("http"):
            continue
        item = {"title": show["name"][:120], "meta": meta_line(network, ep, drops[show["id"], day], day, today)[:180], "image": image}
        (wide if is_wide else posters).append(item)
        if len(wide) == MAX_ITEMS:
            break
    items = (wide + (posters if len(wide) < MIN_WIDE else []))[:MAX_ITEMS]

    out = ROOT / "shelf.json"
    text = json.dumps(items, ensure_ascii=False, indent=2) + "\n"
    if out.exists() and out.read_text() == text:
        print("shelf.json unchanged")
        return 0
    out.write_text(text)
    print(f"shelf.json: {len(items)} items ({len(wide)} with wide art) from {len(newest)} {network} shows")
    return 0 if items else 1


if __name__ == "__main__":
    sys.exit(main())
