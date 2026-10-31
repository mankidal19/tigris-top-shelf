# tigris-top-shelf

Feeds for the **custom Top Shelf** of [Tigris](https://github.com/mankidal19/CustomTvLauncher), the
Android TV launcher. One feed serves several apps: when an app's tile is focused in the first row,
Tigris shows that app's cards as a full-width slideshow.

| App | Package | Source |
|---|---|---|
| Netflix | `com.netflix.ninja` | New and upcoming episodes, from [TVmaze](https://www.tvmaze.com) |
| Prime Video | `com.amazon.amazonvideo.livingroom` | New and upcoming episodes, from TVmaze |
| YouTube | `com.google.android.youtube.tv` | Your own YouTube recommendations, built on your Mac only |

## Two ways to run it

**Public, Netflix and Prime Video only.** GitHub Actions rebuilds `shelf.json` here every six
hours. No account needed:

```
https://raw.githubusercontent.com/mankidal19/tigris-top-shelf/main/shelf.json
```

**Private, with YouTube.** Your recommendations need your YouTube login, and they say a lot about
what you watch, so they never go to GitHub. A Mac on the same network builds the whole feed every
hour with your browser's own cookies (read in place by [yt-dlp](https://github.com/yt-dlp/yt-dlp),
never copied) and serves it on the home network only:

```sh
brew install yt-dlp
mac/setup.sh install chrome:Default   # the browser profile signed in to YouTube
# Feed: http://<this Mac's IP>:8765/shelf.json
```

The first build asks macOS for "Chrome Safe Storage": choose **Always Allow**, or the hourly
builds will ask again. `mac/setup.sh status` shows the last runs; `mac/setup.sh uninstall` stops
both jobs. The TV only gets a shelf while the Mac is awake. Give the Mac a fixed address in the
router so the TV's setting keeps working.

## Use it in Tigris

1. Tigris settings → **Top Shelf** → **Custom source**: one of the feed URLs above.
2. Put the apps in the first row of the home screen.
3. Focus an app's tile; its shelf slides in. OK still opens the app.

**Linked app** only matters for an old-style feed that is a plain list.

## The feed

A JSON object keyed by app package; each value is a list of at most 12 cards:

```json
{
  "com.netflix.ninja": [
    {"title": "Black Doves", "meta": "Netflix · S2 · 6 episodes · Coming Thu 5 Nov", "image": "https://…"}
  ]
}
```

`build_shelf.py` writes it. `config.json` says which app gets which source:

```json
{
  "days_back": 7,
  "days_ahead": 7,
  "apps": {
    "com.netflix.ninja": {"tvmaze": "Netflix"},
    "com.amazon.amazonvideo.livingroom": {"tvmaze": "Prime Video"},
    "com.google.android.youtube.tv": {"youtube": "recommended"}
  }
}
```

- `{"tvmaze": "<service>"}`: one card per show with an episode out in the window, ordered today
  first, then the most recent releases, then what is coming soonest. Batch drops read
  "S2 · 6 episodes". The service name is TVmaze's (`Netflix`, `Prime Video`, `Disney+`,
  `HBO Max`, `iQIYI`, …).
- `{"youtube": "recommended"}`: the YouTube home feed, only when `--youtube-cookies` is given.
  Mixes show the picture of their first video.
- Pictures are wide (1280×720 or larger) wherever the source has them; the shelf crops posters
  badly.
- An app whose source fails keeps its previous cards, so a hiccup doesn't empty the shelf.

Run it by hand with `python3 build_shelf.py` (public part) or
`python3 build_shelf.py --out /tmp/shelf.json --youtube-cookies chrome:Default` (everything).

## Notes

- TVmaze's data is licensed [CC BY-SA 4.0](https://www.tvmaze.com/api#licensing); this feed passes
  it on under the same terms. Images are linked, not copied.
- yt-dlp reads YouTube as your browser would, which YouTube's terms don't cover; it is for your own
  TV, on your own account.
- GitHub turns off scheduled workflows in a public repo after 60 days without activity. The
  workflow's own commits normally keep it alive; if it stops, run it once from the Actions tab.
