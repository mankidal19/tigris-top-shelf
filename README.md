# tigris-top-shelf

Feeds for the **custom Top Shelf** of [Tigris](https://github.com/mankidal19/CustomTvLauncher), the
Android TV launcher. One feed serves several apps: when an app's tile is focused in the first row,
Tigris shows that app's cards as a full-width slideshow.

| App | Package | Source |
|---|---|---|
| Netflix | `com.netflix.ninja` | New and upcoming episodes, from [TVmaze](https://www.tvmaze.com) |
| Prime Video | `com.amazon.amazonvideo.livingroom` | New and upcoming episodes, from TVmaze |
| YouTube | `com.google.android.youtube.tv` | Your own YouTube recommendations (needs the `YT_COOKIES` secret) |

## How it runs

GitHub Actions rebuilds `shelf.json` every three hours (and on demand: Actions → Update shelf →
Run workflow). Point Tigris at:

```
https://raw.githubusercontent.com/mankidal19/tigris-top-shelf/main/shelf.json
```

Netflix and Prime Video need nothing. YouTube needs the repo secret **`YT_COOKIES`**: the
`youtube.com` cookies of a signed-in browser, in Netscape `cookies.txt` format. The workflow writes
it to a private temp file for the run only. Without the secret, YouTube is left out.

To create or refresh it (only youtube.com cookies, not Google-wide ones):

```sh
yt-dlp --cookies-from-browser chrome:Default --cookies all.txt --skip-download --playlist-end 1 :ytrec
{ echo "# Netscape HTTP Cookie File"; awk -F'\t' 'NF>=7 && $1 ~ /^(#HttpOnly_)?\.?([a-z0-9-]+\.)*youtube\.com$/' all.txt; } > yt.txt
gh secret set YT_COOKIES -R mankidal19/tigris-top-shelf < yt.txt && rm all.txt yt.txt
```

Things to know:

- **The feed is public.** Anyone with the URL can read your recommended video titles.
- YouTube signs the cookies out when they expire or when you sign out of that browser, and it
  sometimes blocks GitHub's servers ("confirm you're not a bot"). Either way the YouTube cards
  stop changing (the last ones stay); refresh the secret as above.

## Use it in Tigris

1. Tigris settings → **Top Shelf** → **Custom source**: the feed URL above.
2. Put the apps in the first row of the home screen.
3. Focus an app's tile; its shelf slides in. OK still opens the app.

**Linked app** only matters for an old-style feed that is a plain list.

## The feed

A JSON object keyed by app package; each value is a list of cards (`max_cards` in `config.json`, 5 by default; Tigris takes up to 12):

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
  "max_cards": 5,
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

Run it by hand with `python3 build_shelf.py` (no YouTube),
`python3 build_shelf.py --youtube-cookies chrome:Default` (YouTube from a browser) or
`--youtube-cookie-file yt.txt`.

## Notes

- TVmaze's data is licensed [CC BY-SA 4.0](https://www.tvmaze.com/api#licensing); this feed passes
  it on under the same terms. Images are linked, not copied.
- yt-dlp reads YouTube as your browser would, which YouTube's terms don't cover; it is for your own
  TV, on your own account.
- GitHub turns off scheduled workflows in a public repo after 60 days without activity. The
  workflow's own commits normally keep it alive; if it stops, run it once from the Actions tab.
