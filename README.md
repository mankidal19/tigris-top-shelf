# tigris-top-shelf

A proof of concept feed for the **custom Top Shelf** of [Tigris](https://github.com/mankidal19/CustomTvLauncher),
the Android TV launcher: new and upcoming **Netflix** episodes, with wide show art, rebuilt every six hours
by GitHub Actions.

Feed URL (point Tigris here):

```
https://raw.githubusercontent.com/mankidal19/tigris-top-shelf/main/shelf.json
```

## Use it in Tigris

1. Put the linked app (Netflix) in the first row of the home screen.
2. Tigris settings → **Top Shelf** → **Custom source**: paste the feed URL above.
3. **Linked app**: choose Netflix.
4. Focus the Netflix tile; the shelf slides in after a moment and changes slides every few seconds.

The shelf only shows pictures and text. OK on the tile still opens Netflix.

## How it works

`build_shelf.py` (Python standard library only) reads [TVmaze](https://www.tvmaze.com)'s streaming
schedule for the days around today, keeps one entry per show on the network named in `config.json`,
and writes `shelf.json` in the shape Tigris expects:

```json
[{"title": "Black Doves", "meta": "Netflix · S2 · 6 episodes · Coming Thu 5 Nov", "image": "https://…"}]
```

- Order: today, then the most recent releases, then what is coming soonest.
- Images: the shelf is a full-width slideshow, so shows with wide art come first; posters only fill
  in when fewer than six shows have it. At most 12 items (Tigris ignores the rest).
- `.github/workflows/update.yml` runs it every six hours, on demand (Actions → Update shelf → Run
  workflow), and when the script or config changes. It commits only when the feed changed.

## Change what it shows

Edit `config.json`:

```json
{ "network": "Netflix", "days_back": 7, "days_ahead": 7 }
```

`network` is the streaming service's name as TVmaze spells it (`Netflix`, `Prime Video`, `Disney+`,
`Viu`, `iQIYI`, `HBO Max`, …). Run locally with `python3 build_shelf.py`.

## Notes

- TVmaze's data is licensed [CC BY-SA 4.0](https://www.tvmaze.com/api#licensing); this feed passes
  it on under the same terms. Images are TVmaze's and are linked, not copied.
- GitHub turns off scheduled workflows in a public repo after 60 days without activity. The
  workflow's own commits normally keep it alive; if it stops, run it once from the Actions tab.
