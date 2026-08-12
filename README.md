# Tomas IPTV

Automatic IPTV playlist builder and manual stream-verification system for family and friends.

The project combines public IPTV sources with manually researched Hungarian, Slovak and Czech channels, removes duplicate stream URLs, tracks playback testing, selects the best available feed for each channel, and publishes the result through GitHub Pages.

## Public playlists

Main family/friends playlist:

```text
https://tomkomaster.github.io/tomas-iptv/tv.m3u
```

Stable country playlists:

```text
https://tomkomaster.github.io/tomas-iptv/hu.m3u
https://tomkomaster.github.io/tomas-iptv/sk.m3u
https://tomkomaster.github.io/tomas-iptv/cz.m3u
```

Stable spoken-language playlists:

```text
https://tomkomaster.github.io/tomas-iptv/by-language/hun.m3u
https://tomkomaster.github.io/tomas-iptv/by-language/slk.m3u
https://tomkomaster.github.io/tomas-iptv/by-language/ces.m3u
```

Language playlists keep geography visible in the channel name. For example, a verified Hungarian-language Serbian station is published as `[RS] ...` inside `by-language/hun.m3u`; it is not moved into `hu.m3u` merely because it speaks Hungarian. This also means future outputs such as `deu.m3u`, `srp.m3u` or `ron.m3u` only require a configured language output plus suitable source/audit data.

Testing/research playlist:

```text
https://tomkomaster.github.io/tomas-iptv/test.m3u
```

Dashboard:

```text
https://tomkomaster.github.io/tomas-iptv/
```

The public URLs are intended to stay stable even as sources, channels and feeds change behind them.

The playlists can be used in IPTV applications, VLC, televisions, phones, tablets and other players that support M3U playlists.

---

## Currently supported countries

The project currently treats all three countries as first-class outputs:

* 🇭🇺 Hungary (`HU`)
* 🇸🇰 Slovakia (`SK`)
* 🇨🇿 Czechia (`CZ`)

Each country has enabled upstream sources, a local extras file and its own generated stable playlist.

---

## How the playlist is built

The builder reads the sources defined in:

```text
config.json
```

Current source layers are:

### Hungary

1. IPTV-org Hungary country playlist (base)
2. IPTV-org raw Hungarian alternative streams
3. IPTV-org Hungarian-language playlist
4. Our manually curated `extras/hu.m3u`

### Slovakia

1. IPTV-org Slovakia country playlist (base)
2. IPTV-org raw Slovak alternative streams
3. IPTV-org Slovak-language playlist
4. Our manually curated `extras/sk.m3u`

### Czechia

1. IPTV-org Czechia country playlist (base)
2. IPTV-org raw Czech alternative streams
3. IPTV-org Czech-language playlist
4. Our manually curated `extras/cz.m3u`

The sources are processed in configuration order.

The builder then:

1. downloads remote playlists;
2. reads the HU/SK/CZ local extras;
3. parses all M3U entries;
4. assigns every entry an explicit source/audit `country_code` and independent spoken `language_codes`;
5. identifies logical channels;
6. removes duplicate stream URLs globally;
7. keeps genuinely different feeds as alternatives;
8. applies manual results from `audit.json`;
9. evaluates confirmed spoken language independently, then applies only explicitly configured country-routing rules;
10. rejects manually excluded/unsupported feeds;
11. selects the preferred feed when a stable verified feed exists;
12. creates country/category `group-title` values;
13. generates the shared stable, testing, per-country and per-language playlists;
14. generates CSV and JSON reports;
15. generates the HTML dashboard.

---

# Source types

Each source has a `kind`.

The main kinds currently used are:

```text
base
alternatives
extras
```

## `base`

A base source supplies the main starting channel set for a country.

Current examples:

```text
IPTV-org Hungary
IPTV-org Slovakia
IPTV-org Czechia
```

If a channel first appears in a base source, the dashboard classifies it as:

```text
Base channel
```

---

## `alternatives`

Alternative sources are additional upstream stream collections.

Current examples are the raw IPTV-org country stream files.

They can contribute:

* another feed for an existing channel;
* a channel missing from the base country playlist.

If a new URL belongs to a channel already seen earlier, it becomes:

```text
Alternative stream
```

If it introduces a completely new channel, it becomes:

```text
Added channel
```

---

## `extras`

Extras are our manually maintained local channel candidates.

Current files:

```text
extras/hu.m3u
extras/sk.m3u
extras/cz.m3u
```

These contain streams we researched or added ourselves, including:

* direct broadcaster HLS streams;
* alternate feeds;
* local television stations;
* web television channels;
* manually discovered streams;
* experimental/test candidates;
* temporary resolver-based feeds where necessary.

Like alternative sources, an extra can either add a new channel or provide another feed for an existing channel.

---

# Duplicate handling

The builder removes duplicate **stream URLs**.

URLs are normalized for comparison in safe ways such as:

* ignoring surrounding whitespace;
* treating host names case-insensitively;
* treating standard `:80` and `:443` ports as equivalent to their defaults;
* ignoring URL fragments.

The original URL is still preserved for playback.

A duplicate URL is not published twice.

Information about ignored duplicates is written to:

```text
public/duplicates.csv
```

Different URLs belonging to the same logical channel are **not automatically considered duplicates**. They can remain as separate candidate feeds.

---

# Multiple feeds for one channel

A channel can have several different stream URLs.

For example:

```text
Channel A
  Feed 1
  Feed 2
  Feed 3
```

While none of the feeds is fully verified, multiple candidates can remain in the playlist and are displayed as:

```text
[HU ?] Channel A [Feed 1/3]
[HU ?] Channel A [Feed 2/3]
[HU ?] Channel A [Feed 3/3]
```

Each URL can then be tested independently.

Once one feed for that logical channel becomes fully:

```text
Verified
```

the builder selects the best verified feed and suppresses the other candidate feeds from the published playlist.

The suppressed feeds are recorded in:

```text
excluded.csv
```

with the reason that another feed for the channel is already verified on both VLC and Samsung.

This allows us to research several streams without permanently exposing unnecessary duplicates to users.

---

# Channel prefixes

Naming depends on which generated playlist is being used.

## Testing/research playlist: `test.m3u`

The testing playlist keeps both country and verification state because those labels are useful during manual research:

```text
[HU OK] Duna
[HU ?] Example TV
[SK TV] Example TV
[SK ?] Example TV
[CZ OK] Example Czech TV
[CZ ?] Example Czech TV
```

Country codes are:

| Prefix | Country |
| ------ | ------- |
| `HU` | Hungary |
| `SK` | Slovakia |
| `CZ` | Czechia |

Verification states are:

| Prefix | Status       | Meaning                                                                   |
| ------ | ------------ | ------------------------------------------------------------------------- |
| `OK`   | Verified     | Works in both VLC and the Samsung TV test                                 |
| `TV`   | TV verified  | Works on Samsung; VLC still needs attention or failed the current PC test |
| `PC`   | PC only      | Works in VLC but not on Samsung in the current test                       |
| `?`    | Needs review | Not fully tested or the result still needs investigation                  |
| `X`    | Rejected     | Feed has been rejected/excluded                                           |

Rejected feeds do not enter the stable family/country playlists, but they can remain visible in the testing/research workflow.

## Shared stable playlist: `tv.m3u`

The family/friends playlist contains only stable channels, so the status suffix is redundant. It keeps only the country code:

```text
[HU] Duna
[SK] JOJ
[CZ] Prima
```

## Per-country stable playlists

The country itself is already defined by the file, so generated country/status prefixes are omitted entirely:

```text
hu.m3u -> Duna
sk.m3u -> JOJ
cz.m3u -> Prima
```

These labels describe playlist organization and playback verification, not broadcasting licences, copyright status or legal availability.

---

# Channel groups

The M3U `group-title` is used for content organization rather than playback status.

Generated groups follow the same model for all supported countries:

```text
Hungary | General
Hungary | Music
Hungary | News
Hungary | Sports

Slovakia | General
Slovakia | Music
Slovakia | News

Czechia | General
Czechia | Music
Czechia | News
Czechia | Sports
```

Where useful, categories supplied by upstream sources are preserved.

---

# Manual verification with `audit.json`

Manual playback history is stored in:

```text
audit.json
```

This is the persistent test database for the project.

A typical audited stream can contain information such as:

```json
{
  "channel": "Example TV",
  "stream_url": "https://example.com/live/playlist.m3u8",
  "tvg_id": "ExampleTV.hu",
  "vlc": "works",
  "samsung": "works",
  "vlc_note": "ok",
  "samsung_note": "ok",
  "expected_language_codes": ["HU"],
  "observed_language_codes": ["HU"],
  "decision": "auto",
  "exclude_from_playlist": false,
  "tested_on": "2026-08-10",
  "provenance": "Official broadcaster",
  "discovery": "Manual research",
  "notes": "Passed both playback tests."
}
```

Not every field is required for every historical entry.

The builder also understands older audit entries while the audit format continues to evolve.

---

## Playback test values

Common VLC/Samsung values include:

```text
works
works_with_warning
loads
mrl_error
format_error
generic_error
wrong_language
not_tested
needs_review
```

The automatic decision logic uses the playback tests and language information to determine the resulting status.

For example:

```text
VLC works + Samsung works
        ↓
Verified
        ↓
[HU OK] / [SK OK] / [CZ OK] in `test.m3u`
```

---

## `decision`

Normally use:

```json
"decision": "auto"
```

and allow the builder to calculate the result from the test information.

Explicit decisions are also supported:

```text
verified
tv_verified
pc_only
needs_review
rejected
```

Explicit decisions should only be used when there is a good reason to override automatic classification.

---

## `exclude_from_playlist`

To explicitly remove a feed from the shared playlist:

```json
"exclude_from_playlist": true
```

The feed remains documented in `audit.json`, but is excluded from the generated `tv.m3u`.

This is useful for:

* dead URLs;
* wrong-language feeds;
* obsolete stations;
* feeds that fail on both devices;
* mistaken channel identities;
* known unsuitable streams.

---

# URL-specific auditing

Whenever possible, audit a specific feed using:

```json
"stream_url": "https://..."
```

This is especially important when a channel has several candidate feeds.

Testing:

```text
Channel A / Feed 1
```

must not automatically mark:

```text
Channel A / Feed 2
```

as working.

The builder therefore prefers exact stream-URL audit matches.

Older channel-level audits can still be used when the match is unambiguous.

If an old channel-level audit becomes ambiguous because several current feeds exist, the builder warns about it instead of incorrectly assigning the historical result to one of the feeds.

---

# Country and language metadata

Country, spoken language and publication destination are separate concepts.

Modern source/channel metadata uses:

```json
{
  "country_code": "AT",
  "language_codes": ["deu"]
}
```

`country_code` is the publication/audit geography (ISO-3166-style two-letter code). `language_codes` contains spoken/content languages using ISO-639-3-style codes such as `hun`, `slk`, `ces`, `deu`, `srp` or `ron`.

Manual audit rows additionally expose:

```text
playlist_country_code
output_country_code
expected_language_codes
observed_language_codes
```

The first two are countries. The latter two are spoken-language evidence. Existing audit values such as `["HU"]`, `["SK"]` and `["CZ"]` remain accepted and normalize to `hun`, `slk` and `ces`. Historical fields `language_code`, `playlist_language_code` and `output_language_code` remain supported as compatibility aliases for the old country bucket.

Verified streams are **not** generically routed by language. Current HU/SK/CZ cross-routing is explicitly configured in `verified_country_routes`, for example `SK + ces -> CZ`. That preserves today's useful behavior without creating a future rule that would incorrectly force every German stream into Germany or every Hungarian stream into Hungary.

This allows models such as:

```text
Austria      -> country AT, language deu
Germany      -> country DE, language deu
Serbia       -> country RS, languages srp/hun
Romania      -> country RO, languages ron/hun
Switzerland  -> country CH, languages deu/fra/ita
```

Multilingual or ambiguous language results are not blindly duplicated across country outputs. Country placement changes only when source geography, canonical identity, a manual output country, or an explicit verified routing rule says it should.

---

# Adding channels

Use the extras file for the country where the candidate belongs. Do **not** manually add `[HU ...]`, `[SK ...]` or `[CZ ...]` prefixes to source names; the builder formats generated playlists automatically.

## Adding a Hungarian channel

Edit:

```text
extras/hu.m3u
```

Example:

```text
# Example TV — direct official HLS candidate
#EXTINF:-1 tvg-id="ExampleTV.hu" tvg-name="Example TV" group-title="General",Example TV
https://example.com/live/playlist.m3u8
```

A new unresolved candidate normally appears as `[HU ?] Example TV` in `test.m3u`. Once stable, it appears as `[HU] Example TV` in `tv.m3u` and plain `Example TV` in `hu.m3u`.

## Adding a Slovak channel

Edit:

```text
extras/sk.m3u
```

Example:

```text
# Example Slovak TV — direct official HLS candidate
#EXTINF:-1 tvg-id="ExampleTV.sk" tvg-name="Example TV" group-title="General",Example TV
https://example.sk/live/playlist.m3u8
```

A new unresolved candidate normally appears as `[SK ?] Example TV` in `test.m3u`. Once stable, it appears as `[SK] Example TV` in `tv.m3u` and plain `Example TV` in `sk.m3u`.

## Adding a Czech channel

Edit:

```text
extras/cz.m3u
```

Example:

```text
# Example Czech TV — direct official HLS candidate
#EXTINF:-1 tvg-id="ExampleTV.cz" tvg-name="Example Czech TV" group-title="General",Example Czech TV
https://example.cz/live/playlist.m3u8
```

`extras/cz.m3u` is configured with:

```json
"country_code": "CZ",
"language_codes": ["ces"]
```

A new unresolved candidate normally appears as:

```text
[CZ ?] Example Czech TV
```

in `test.m3u`. After successful VLC/Samsung and language verification, the stable outputs are:

```text
tv.m3u -> [CZ] Example Czech TV
cz.m3u -> Example Czech TV
```

---

# Testing a new channel

The same manual workflow applies to Hungarian, Slovak and Czech candidates:

1. add the exact candidate URL to `extras/hu.m3u`, `extras/sk.m3u` or `extras/cz.m3u` as appropriate;
2. let the playlist rebuild;
3. find the candidate in `test.m3u` (`[HU ?]`, `[SK ?]` or `[CZ ?]` initially);
4. test that exact stream/feed in VLC;
5. test that exact stream/feed on the Samsung IPTV application;
6. verify the actual channel identity and spoken language/content;
7. add or update the exact-URL entry in `audit.json`;
8. rebuild and confirm the resulting status on the dashboard;
9. for a stable Czech result, confirm it is `[CZ]` in `tv.m3u` and plain-named in `cz.m3u`.

A typical Czech audit record can look like:

```json
{
  "channel": "Example Czech TV",
  "stream_url": "https://example.cz/live/playlist.m3u8",
  "playlist_language_code": "CZ",
  "expected_language_codes": ["CZ"],
  "observed_language_codes": ["CZ"],
  "vlc": "works",
  "samsung": "works",
  "decision": "auto",
  "exclude_from_playlist": false
}
```

Where a channel has multiple URLs, test each feed separately. A successful result on one URL must not be assumed to apply to another URL.

---

# Generated files

The build writes public output into:

```text
public/
```

## `tv.m3u`

Shared stable family/friends playlist containing HU, SK and CZ channels. Stable names use language-only prefixes such as `[HU]`, `[SK]` and `[CZ]`.

```text
https://tomkomaster.github.io/tomas-iptv/tv.m3u
```

## `test.m3u`

Testing/research playlist. This is where diagnostic status prefixes such as `[HU OK]`, `[SK ?]` and `[CZ ?]` remain visible.

```text
https://tomkomaster.github.io/tomas-iptv/test.m3u
```

## Country playlists

Stable country-specific outputs use plain channel names because the country is already implied by the playlist:

```text
public/hu.m3u -> https://tomkomaster.github.io/tomas-iptv/hu.m3u
public/sk.m3u -> https://tomkomaster.github.io/tomas-iptv/sk.m3u
public/cz.m3u -> https://tomkomaster.github.io/tomas-iptv/cz.m3u
```

---

## `index.html`

```text
public/index.html
```

Generated dashboard showing playlist statistics, sources, channels and manual verification information.

Public URL:

```text
https://tomkomaster.github.io/tomas-iptv/
```

The dashboard includes:

* unique channel count;
* unique stream count;
* channels added beyond the base playlists;
* alternative stream count;
* duplicate URL count;
* per-country statistics;
* per-source statistics;
* channel inventory;
* source classification;
* manual VLC/Samsung verification results;
* verification status;
* language verification;
* search/filter controls;
* added/removed channel information compared with the previous build.

---

## `channels.csv`

```text
public/channels.csv
```

Complete inventory of stream entries published in the playlist.

Includes information such as:

* published playlist name;
* underlying channel name;
* feed number;
* `tvg-id`;
* country;
* content group;
* generated group;
* verification status;
* source;
* source classification;
* stream URL;
* logo.

---

## `duplicates.csv`

```text
public/duplicates.csv
```

URLs ignored because the same normalized stream URL had already been encountered earlier in the source chain.

---

## `excluded.csv`

```text
public/excluded.csv
```

Feeds deliberately left out of the final playlist.

Reasons can include:

* manual rejection;
* `exclude_from_playlist`;
* wrong language;
* another feed for the same channel already being fully verified.

---

## `audit.csv`

```text
public/audit.csv
```

CSV version of the prepared manual verification data.

Useful for reviewing:

* individual feeds;
* VLC tests;
* Samsung tests;
* language information;
* audit decisions;
* exclusions;
* testing dates;
* notes;
* whether the exact feed is currently in the playlist.

---

## `report.json`

```text
public/report.json
```

Machine-readable build report.

It contains information including:

* build timestamp;
* summary statistics;
* source statistics;
* language statistics;
* audit summaries;
* audit warnings;
* current channels;
* added channels;
* removed channels;
* EPG configuration state.

The previous public `report.json` is also used to determine what changed between builds.

---

## `.nojekyll`

```text
public/.nojekyll
```

Deployment helper used for GitHub Pages.

---

# Optional EPG support

The project also has optional XMLTV EPG support.

When an `epg` configuration is enabled in `config.json`, the GitHub Actions workflow can use the IPTV-org EPG project to generate:

```text
public/guide.xml
```

The workflow validates that the result:

* exists;
* is not empty;
* is valid XML;
* has an XMLTV `<tv>` root;
* contains channels;
* contains programme entries.

When EPG is disabled, this step is skipped.

EPG is therefore supported by the project architecture but is not required for the normal playlist build.

---

# Running locally

The core builder uses Python 3.

From the repository directory:

```bash
python3 build.py
```

On Windows, depending on the Python installation:

```powershell
py build.py
```

The generated files appear under:

```text
public/
```

Because the build downloads the configured remote sources, internet access is required for a normal full build.

---

# Running tests locally

Run the complete unit-test suite with:

```bash
python3 -m unittest discover -s tests -v
```

On Windows:

```powershell
py -m unittest discover -s tests -v
```

The GitHub Actions workflow runs the same Python unit tests before building and deploying the playlist.

---

# Strict audit validation

The builder also supports:

```bash
python3 build.py --strict
```

or on Windows:

```powershell
py build.py --strict
```

Strict mode turns audit-validation warnings that are considered unsafe/ambiguous into build failures where appropriate.

This is useful after substantial edits to `audit.json`.

---

# Configuration

The main configuration lives in:

```text
config.json
```

Current simplified structure:

```json
{
  "site_title": "Tomas IPTV",
  "default_language_code": "HU",

  "country_names": {
    "HU": "Hungary",
    "SK": "Slovakia",
    "CZ": "Czechia"
  },

  "output": "public/tv.m3u",
  "audit_path": "audit.json",

  "sources": [],
  "extras": []
}
```

Remote sources use:

```json
{
  "name": "Example source",
  "kind": "base",
  "language_code": "HU",
  "url": "https://example.com/list.m3u"
}
```

Local sources use:

```json
{
  "name": "Example extras",
  "kind": "extras",
  "language_code": "HU",
  "path": "extras/example.m3u"
}
```

---

# Current country configuration

HU, SK and CZ are already fully enabled. `config.json` defines all three country names and generated country outputs:

```json
"country_names": {
  "HU": "Hungary",
  "SK": "Slovakia",
  "CZ": "Czechia"
},
"country_outputs": {
  "HU": "public/hu.m3u",
  "SK": "public/sk.m3u",
  "CZ": "public/cz.m3u"
}
```

Czechia also has all normal source layers enabled, including the base country playlist, raw alternatives, Czech-language playlist and local extras:

```text
IPTV-org Czechia
IPTV-org Czechia raw alternatives
IPTV-org Czech language
extras/cz.m3u
```

There is no separate Czech builder: Czech entries go through the same deduplication, audit, stable-selection, language-routing, reporting and publication pipeline as HU and SK.

---

# GitHub Actions

The workflow is:

```text
.github/workflows/build-and-publish.yml
```

It currently runs when relevant files are pushed to `main`, can be started manually, and is scheduled daily.

The scheduled rebuild is:

```text
04:23 Europe/Bratislava
```

The workflow:

1. checks out the repository;
2. runs the Python tests;
3. builds the IPTV playlist and reports;
4. optionally builds the XMLTV EPG;
5. validates the EPG when enabled;
6. uploads `public/`;
7. deploys it to GitHub Pages.

---

# Important files

```text
tomas-iptv/
│
├── README.md
├── build.py
├── config.json
├── audit.json
│
├── extras/
│   ├── hu.m3u
│   ├── sk.m3u
│   └── cz.m3u
│
├── tests/
│   ├── test_build.py
│   └── test_regressions.py
│
├── .github/
│   └── workflows/
│       ├── ci.yml
│       └── build-and-publish.yml
│
└── public/                 # generated during the build
    ├── tv.m3u
    ├── test.m3u
    ├── hu.m3u
    ├── sk.m3u
    ├── cz.m3u
    ├── index.html
    ├── channels.csv
    ├── duplicates.csv
    ├── excluded.csv
    ├── audit.csv
    ├── report.json
    ├── guide.xml
    └── .nojekyll
```

The `public/` directory is generated output rather than the main source of truth.

The important editable source files include:

```text
config.json
audit.json
extras/hu.m3u
extras/sk.m3u
extras/cz.m3u
build.py
tests/
```

---

# Planned improvements

Possible next steps include:

* broader country-aware XMLTV/EPG coverage, especially Czech and Slovak providers;
* additional native HLS source research;
* continued stream-health and event-stream policy improvements;
* further dashboard/report improvements;
* continued refactoring of the builder as the project grows.

The stable/test split, per-country HU/SK/CZ playlists and Czech channel support are already implemented and are no longer future roadmap items.

---

# Project philosophy

The goal is not simply to collect as many IPTV URLs as possible.

The project tries to maintain a useful shared playlist by:

* combining several discovery sources;
* researching missing channels;
* preferring direct/native streams where possible;
* keeping alternative feeds when useful;
* testing feeds manually;
* tracking results persistently;
* removing known-bad feeds;
* avoiding duplicate URLs;
* preserving research history;
* keeping one stable public playlist URL for users.

Stream availability can change at any time, so a previously verified stream may still need to be retested later.
