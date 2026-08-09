# Tomas IPTV

A small public M3U playlist builder.

## What it does

For the first test it downloads the current IPTV-org Hungary playlist:

https://iptv-org.github.io/iptv/countries/hu.m3u

It then appends our manually curated entries from:

extras/hu.m3u

Exact duplicate stream URLs are removed, and the result is published as:

tv.m3u

## Public URL

If your GitHub username is `YOURNAME` and this repository is named `tomas-iptv`,
the playlist URL will normally be:

https://YOURNAME.github.io/tomas-iptv/tv.m3u

Use that URL in the IPTV app on the TV, phone, tablet, VLC, etc.

The important part is that this URL does not need to change when more
countries are added later.

## GitHub setup

1. Create a new PUBLIC repository named `tomas-iptv`.
2. Upload the contents of this project to the repository.
3. Open repository Settings -> Pages.
4. Under Build and deployment -> Source, choose `GitHub Actions`.
5. Open the Actions tab.
6. Run `Build and publish IPTV playlist` once manually.
7. After the deployment succeeds, open the Pages URL.
8. Add `/tv.m3u` to the end of the Pages URL and put that URL into your IPTV app.

## Updating

The workflow rebuilds every day at 04:23 Europe/Bratislava time and whenever
the relevant files are changed.

GitHub documents that scheduled workflows in inactive public repositories can
eventually be disabled. If that ever happens, the existing playlist remains
online; the automatic refresh simply stops until the workflow is re-enabled.

## Adding a new Hungarian channel

Edit `extras/hu.m3u`:

#EXTINF:-1 tvg-id="Example.hu" group-title="Hungary | Extra",Example TV
https://official-broadcaster.example/live/playlist.m3u8

Commit the change. GitHub Actions rebuilds and republishes `tv.m3u`.

## Later expansion

When ready, `config.json` can add:

https://iptv-org.github.io/iptv/countries/sk.m3u
https://iptv-org.github.io/iptv/countries/cz.m3u

or ultimately:

https://iptv-org.github.io/iptv/index.m3u

Family/friends can keep using the same `tv.m3u` URL.
