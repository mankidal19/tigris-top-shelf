# tigris-top-shelf

Feeds for the **custom Top Shelf** of [Tigris](https://github.com/mankidal19/CustomTvLauncher), the
Android TV launcher. One feed serves several apps: when an app's tile is focused in the first row,
Tigris shows that app's cards as a full-width slideshow.

| App | Package | Source |
|---|---|---|
| Netflix | `com.netflix.ninja` | Netflix's official Top 10 shows in Malaysia (5 different ones each run), topped up with new episodes |
| Viu | `com.vuclip.viu.tv` | The newest episode or teaser of each of Viu Malaysia's 5 most recently updated shows on YouTube, one card per show, with no kissing (or nearly kissing) in the picture |
| Prime Video | `com.amazon.amazonvideo.livingroom` | New and upcoming episodes, from TVmaze |
| YouTube | `com.google.android.youtube.tv` | Your own YouTube recommendations from the last 7 days, plus one Islamic video (zikir, al-ma'thurat, …) from your watch history (needs the `YT_COOKIES` secret) |
| unifi TV | `com.tm.unifitv.tv` | What's on now on your channels, from unifi TV's programme guide |
| RTMKlik | `my.gov.rtm.tv` | RTMKlik's special live channels (Saluran Khas), Sukan+, and what's on TV1 and TV2 now |

## How it runs

GitHub Actions rebuilds `shelf.json` every 2 hours from 6am to 10pm Malaysia time, and refreshes
just the live-TV apps (unifi TV, RTMKlik; `--only unifi,rtmklik`) on the half hours between, until
midnight, so "On TV now" is never more than about half an hour old while YouTube is asked no more
often than before (and on demand: Actions → Update shelf →
Run workflow). Point Tigris at:

```
https://raw.githubusercontent.com/mankidal19/tigris-top-shelf/main/shelf.json
```

Netflix and Prime Video need nothing. Checking pictures for kissing (Viu) needs the repo secret
**`ANTHROPIC_API_KEY`** (see `"never_pictures"` below); without it pictures are not checked.
YouTube needs the repo secret **`YT_COOKIES`**: the
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

### Starting it by hand

GitHub runs scheduled workflows late, or skips them, when it is busy. A run can also be started by
hand (Actions → Update shelf → Run workflow) or through the API; its `only` input picks the apps
(`unifi,rtmklik` for live TV only), and empty rebuilds everything.

### A Telegram message when YouTube breaks

Each run that asks YouTube records whether it worked in `health.json`. When that changes (the
first run that finds YouTube signed out or failing, and the first that works again) the workflow
sends a Telegram message. To receive them:

1. In Telegram, talk to [@BotFather](https://t.me/BotFather), send `/newbot`, and keep the token it
   gives you.
2. Send your new bot any message, then open
   `https://api.telegram.org/bot<token>/getUpdates` in a browser: your chat id is the number under
   `"chat":{"id":…`.
3. Add both as repository secrets (Settings → Secrets and variables → Actions):
   `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.

Without them the step only writes the message to the run's log.

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
  ([top10.netflix.com](https://top10.netflix.com)), drawn at random. Only shows TVmaze has wide
  art for take part (TVmaze has no films, so films are left out); new Netflix episodes add to
  the choice when fewer than 5 shows are left that weren't on the previous shelf. Netflix's own data has no pictures.
- `{"tvmaze": "<service>"}`: one card per show with an episode out in the window, ordered today
  first, then the most recent releases, then what is coming soonest. Batch drops read
  "S2 · 6 episodes". The service name is TVmaze's (`Netflix`, `Prime Video`, `Disney+`,
  `HBO Max`, `iQIYI`, …). When fewer than 5 shows in the window weren't on the previous shelf,
  shows released before it (`"older_days_back"`, back to 21 days ago) join after them.
- `{"youtube": "recommended"}`: the YouTube home feed, only with YouTube cookies (see above), one
  video per YouTube category (Music, Gaming, Sports, …) so no category fills the shelf. A video's
  category is read once from its watch page and remembered.
  Mixes show the picture of their first video. `"max_age_days": 7` keeps only videos uploaded in
  the last 7 days (YouTube's own "3 days ago", read with yt-dlp's `approximate_date`), which leaves
  out Mixes and undated videos. `"islamic": [words]` makes one card a video from the account's
  watch history (`:ythistory`, one more yt-dlp request) whose title or channel holds one of the
  words (zikir, al-ma'thurat, selawat, …), chosen at random, in a random place among the
  recommendations, and marked "Watched before"; when the history has none, last run's stays.
- `{"unifi": ["TV3", "beIN SPORTS 1", …], "skip": ["WOW SHOP"]}`: per channel (names as unifi TV
  shows them), the programme on now, or a live event starting within 3 hours
  (`"live_soon_hours"`), marked "Live soon"; live events on now first, then those about to
  start, then the channels in the order listed. Titles containing a `skip` text are passed over.
  `"per_channel": 3` also shows each channel's next programmes, alternating channels.
- `{"youtube_playlists": "@ViuMalaysia", "service": "Viu", "skip": [...]}`: the channel's most
  recently updated playlists (YouTube's "Last video added" order), one card per show (`"playlists"`,
  default 5), so a show with several new episodes is still on the shelf once. Each card is one of
  the show's 4 newest videos (`"depth"`, highest episode number first) that wasn't on the previous
  shelf, and shows that weren't on it come first. Playlists of several shows are passed over:
  hashtag ones ("#ViuEventHighlights"), genre and collection names ("Cdrama Recommendation",
  "Thai Drama [True Visions]", "Best of …", "OST"), those whose videos mostly don't name the
  playlist, and those containing a `skip` text ("Viu Shorts"). Through yt-dlp: one request for the
  list and one per playlist each run.
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
- The streaming apps (Netflix, Prime Video, YouTube, Viu) don't show the same cards twice in a
  row while their source has others: each picks from more than 5 (TVmaze's 10 nearest releases,
  the whole Top 10, YouTube's 30 recommendations, each Viu show's 4 newest videos, from its 10 latest shows) and takes
  last run's cards only to fill up. The live-TV apps (unifi TV, RTMKlik) always show what's on.
  The half-hourly live-TV runs leave the streaming apps alone, so they change every 2 hours.
- An app whose source fails keeps its previous cards, so a hiccup doesn't empty the shelf.
- `"never"`: words and phrases that keep a card off every shelf, grouped as `horror` and `lgbtq`
  (any group name works). They are matched as whole words, ignoring case and punctuation, against
  the card's title and details and, where the source has them, its genres and description: TVmaze's
  genres and summary (Netflix, Prime Video, and tvN/AXN/K Plus on unifi TV), AniList's genres and
  tags such as "Boys' Love" or "LGBTQ+ Themes" (Animax), the unifi TV guide's own genres and
  descriptions, and Viu's and RTMKlik's synopses. A YouTube video that is a show's trailer or
  episode ("Show Name | Official Trailer | Crunchyroll") is also checked against that show's AniList
  and TVmaze genres and tags; other YouTube videos only have their title and channel to go on. Previous cards kept after a failure are checked again too.
  The `kissing` group (kiss, ciuman, cium, kucup, …) leaves out videos whose title says so.
- `"never_pictures"`: what a card's *picture* must not show, in plain words (now: a romantic kiss,
  an almost-kiss with faces close and lips nearly touching, a couple in bed). Words can't see a
  thumbnail, so an app with `"check_pictures": true` (Viu) has each new picture looked at by Claude
  (`"picture_model"`, `claude-haiku-5-5` by default), told to say yes when in doubt. A flagged
  picture is passed over: the Viu show uses its next newest video instead, and other apps take
  their next card. Each picture is asked about once and the answer remembered in `image_cache.json`
  for a month, so a run only pays for new pictures (a few cents a day for Viu). A picture that
  can't be checked (API down) isn't used that run, so the shelf keeps its previous, checked cards.
  Needs the repo secret `ANTHROPIC_API_KEY` (an API key from
  [console.anthropic.com](https://console.anthropic.com)); without it, pictures are not checked
  and the run says so in its log. Add `"check_pictures": true` to another app in `config.json` to
  check its pictures too.

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
