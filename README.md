# tigris-top-shelf

Feeds for the **custom Top Shelf** of [Tigris](https://github.com/mankidal19/CustomTvLauncher), the
Android TV launcher. One feed serves several apps: when an app's tile is focused in the first row,
Tigris shows that app's cards as a full-width slideshow.

| App | Package | Source |
|---|---|---|
| Netflix | `com.netflix.ninja` | Netflix's official Top 10 shows in Malaysia (random 5 each run), topped up with new episodes |
| Viu | `com.vuclip.viu.tv` | The newest episodes and teasers of Viu Malaysia's 3 most recently updated show playlists on YouTube |
| Prime Video | `com.amazon.amazonvideo.livingroom` | New and upcoming episodes, from TVmaze |
| YouTube | `com.google.android.youtube.tv` | Your own YouTube recommendations (needs the `YT_COOKIES` secret) |
| unifi TV | `com.tm.unifitv.tv` | What's on now on your channels, from unifi TV's programme guide |
| RTMKlik | `my.gov.rtm.tv` | RTMKlik's special live channels (Saluran Khas), Sukan+, and what's on TV1 and TV2 now |

## How it runs

GitHub Actions rebuilds `shelf.json` every 2 hours from 6am to 10pm Malaysia time (and on demand: Actions → Update shelf →
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

A JSON object keyed by app package. Each value is a list of at most `max_cards` cards (5 by default,
set in `config.json`; Tigris takes up to 12). Each card may carry `source`, the small heading Tigris
shows over the title ("Top 10 in Malaysia", "On TV now"); set `"label"` on an app in `config.json`
to change it:

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

- `{"netflix_top10": "MY"}`: Netflix's official weekly Top 10 shows for that country
  ([top10.netflix.com](https://top10.netflix.com)), drawn at random each run so the shelf rotates.
  Only shows TVmaze has wide art for take part (TVmaze has no films, so films are left out);
  new Netflix episodes fill any free places. Netflix's own data has no pictures.
- `{"tvmaze": "<service>"}`: one card per show with an episode out in the window, ordered today
  first, then the most recent releases, then what is coming soonest. Batch drops read
  "S2 · 6 episodes". The service name is TVmaze's (`Netflix`, `Prime Video`, `Disney+`,
  `HBO Max`, `iQIYI`, …).
- `{"youtube": "recommended"}`: the YouTube home feed, only with YouTube cookies (see above).
  Mixes show the picture of their first video.
- `{"unifi": ["TV3", "beIN SPORTS 1", …], "skip": ["WOW SHOP"]}`: per channel (names as unifi TV
  shows them), the programme on now, or a live event starting within half an hour; live events
  first, then the channels in the order listed. Titles containing a `skip` text are passed over.
  `"per_channel": 3` also shows each channel's next programmes, alternating channels.
- `{"youtube_playlists": "@ViuMalaysia", "playlists": 3, "service": "Viu", "skip": [...]}`: the
  channel's most recently updated playlists (YouTube's "Last video added" order), one per show,
  and the newest two videos of each (highest episode number), taking turns between the shows.
  Hashtag playlists ("#ViuEventHighlights") and those containing a `skip` text ("Viu Shorts") are
  passed over. Through yt-dlp: one request for the list and one per playlist each run.
- `{"viu": "my"}`: the "Top 10" row of Viu's home page for that country (`"row"` picks another,
  e.g. "New Release"), drawn at random each run, with Viu's 1920×1080 covers and air times where
  Viu gives them. The page carries its rows as JSON, so it is one ordinary page fetch. Viu only
  serves the page to Malaysian connections, so this works from a computer in Malaysia but not on
  GitHub's servers; the feed uses the YouTube channel instead.
- `{"rtmklik": {"max_specials": 2, "channels": ["Sukan+"], "guide": {"unifi": ["TV1", "TV2"]}}}`:
  RTMKlik's special live channels (Saluran Khas, e.g. MotoGP or election coverage) with RTM's own
  banners, then a card for each channel named (RTMKlik publishes no schedule, so these say only
  that the channel is live), then `guide`, a `unifi` source for what's on TV1 and TV2 now. It reads
  the content API RTMKlik's TV app uses (`rtm.glueapi.io`), without a login; not documented.
  It is the guide unifi TV's web player reads, without a login; not a documented API, so it may change.
  The guide has no programme pictures, so `"images"` says where each channel's come from, with the
  channel's logo as the fallback:
  - `sports`: [TheSportsDB](https://www.thesportsdb.com) (free public key): the match's own
    picture when the title names one ("Villarreal vs Espanyol") within ten days, else the league's
    fan art (LaLiga, Premier League, Champions/Europa League, F1, MotoGP, A-League, …);
  - `anime`: [AniList](https://anilist.co)'s banner;
  - `series`: TVmaze's wide art;
  - `youtube`: the thumbnail of a YouTube video whose title contains the programme's whole name
    (good for TV3/TV9 shows, whose clips the channels upload); needs the YouTube cookies.

  A picture is only used when the names agree, so a miss shows the logo rather than the wrong show.
  Lookups are remembered in `image_cache.json` (found pictures for 30 days, misses for 3), so each
  programme is looked up once rather than on every run.
- Pictures are wide (1280×720 or larger) wherever the source has them; the shelf crops posters
  badly.
- An app whose source fails keeps its previous cards, so a hiccup doesn't empty the shelf.
- `"never"`: words and phrases that keep a card off every shelf, grouped as `horror` and `lgbtq`
  (any group name works). They are matched as whole words, ignoring case and punctuation, against
  the card's title and details and, where the source has them, its genres and description: TVmaze's
  genres and summary (Netflix, Prime Video, and tvN/AXN/K Plus on unifi TV), AniList's genres and
  tags such as "Boys' Love" or "LGBTQ+ Themes" (Animax), the unifi TV guide's own genres and
  descriptions, and Viu's and RTMKlik's synopses. A YouTube video that is a show's trailer or
  episode ("Show Name | Official Trailer | Crunchyroll") is also checked against that show's AniList
  and TVmaze genres and tags; other YouTube videos only have their title and channel to go on. Previous cards kept after a failure are checked again too.

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
