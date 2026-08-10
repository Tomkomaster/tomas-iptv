# Tomas IPTV

Automatic IPTV playlist builder and manual stream-verification system for family and friends.

The project combines public IPTV sources with manually researched Hungarian and Slovak channels, removes duplicate stream URLs, tracks playback testing, selects the best available feed for each channel, and publishes the result through GitHub Pages.

## Public playlist

Main playlist:

```text
https://tomkomaster.github.io/tomas-iptv/tv.m3u
```

Dashboard:

```text
https://tomkomaster.github.io/tomas-iptv/
```

The playlist URL is intended to stay stable even as sources, channels, countries and feeds are changed behind it.

It can be used in IPTV applications, VLC, televisions, phones, tablets and other players that support M3U playlists.

---

## Currently supported countries

The project currently builds channels for:

* 🇭🇺 Hungary (`HU`)
* 🇸🇰 Slovakia (`SK`)

Czechia (`CZ`) is already known by the builder and is a planned future expansion, but Czech sources are not currently enabled in `config.json`.

---

## How the playlist is built

The builder reads the sources defined in:

```text
config.json
```

Current source layers are:

### Hungary

1. IPTV-org Hungary country playlist
2. IPTV-org raw Hungarian alternative streams
3. Our manually curated `extras/hu.m3u`

### Slovakia

1. IPTV-org Slovakia country playlist
2. IPTV-org raw Slovak alternative streams
3. Our manually curated `extras/sk.m3u`

The sources are processed in configuration order.

The builder then:

1. downloads remote playlists;
2. reads our local extras;
3. parses all M3U entries;
4. assigns every entry to a country/language;
5. identifies logical channels;
6. removes duplicate stream URLs;
7. keeps genuinely different feeds as alternatives;
8. applies manual results from `audit.json`;
9. rejects manually excluded feeds;
10. selects the preferred feed when a fully verified feed exists;
11. adds verification prefixes to channel names;
12. creates country/category `group-title` values;
13. generates the public playlist;
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

Published channel names contain a country code and manual verification status.

Examples:

```text
[HU OK] Duna
[HU TV] Example TV
[HU PC] Example TV
[HU ?] Example TV
[SK OK] Example TV
[SK ?] Example TV
```

The first part identifies the playlist/country:

| Prefix | Country                     |
| ------ | --------------------------- |
| `HU`   | Hungary                     |
| `SK`   | Slovakia                    |
| `CZ`   | Czechia, when enabled later |

The second part describes playback testing:

| Prefix | Status       | Meaning                                                                   |
| ------ | ------------ | ------------------------------------------------------------------------- |
| `OK`   | Verified     | Works in both VLC and the Samsung TV test                                 |
| `TV`   | TV verified  | Works on Samsung; VLC still needs attention or failed the current PC test |
| `PC`   | PC only      | Works in VLC but not on Samsung in the current test                       |
| `?`    | Needs review | Not fully tested or the result still needs investigation                  |
| `X`    | Rejected     | Feed has been rejected/excluded                                           |

Normally rejected feeds do not appear in the published playlist, so `[HU X]` / `[SK X]` mainly exists as an understood internal status.

These are **playback verification labels**, not statements about broadcasting licences, copyright status or legal availability.

---

# Channel groups

Verification status is kept in the channel prefix.

The M3U `group-title` is instead used for actual content organization.

Generated groups follow this structure:

```text
Hungary | General
Hungary | Music
Hungary | News
Hungary | Sports

Slovakia | General
Slovakia | Music
Slovakia | News
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
[HU OK] / [SK OK]
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

# Language verification

The audit can separately track:

```text
expected_language_codes
observed_language_codes
```

Example:

```json
"expected_language_codes": ["HU"],
"observed_language_codes": ["HU"]
```

Multilingual streams are supported.

If the expected language is among the observed languages, the stream can still be considered a language match.

A confirmed wrong-language stream can be rejected from that country's playlist.

Legacy fields such as:

```text
language
language_code
```

are still understood for compatibility with older audit entries.

---

# Adding a Hungarian channel

Edit:

```text
extras/hu.m3u
```

Add a normal M3U entry:

```text
# Example TV — direct official HLS candidate
#EXTINF:-1 tvg-id="ExampleTV.hu" tvg-name="Example TV" group-title="General",Example TV
https://example.com/live/playlist.m3u8
```

Do **not** manually add:

```text
[HU OK]
[HU ?]
```

to the name.

The builder creates the country/status prefix automatically from the audit information.

After committing the change, GitHub Actions rebuilds the playlist.

The new feed will normally begin as:

```text
[HU ?]
```

until it has enough manual verification information.

---

# Adding a Slovak channel

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

The builder assigns it to Slovakia because `extras/sk.m3u` is configured with:

```json
"language_code": "SK"
```

Its generated prefix will therefore use:

```text
[SK ?]
```

until testing changes its status.

---

# Testing a new channel

Our normal manual process is:

1. add the candidate stream to the appropriate extras file;
2. let the playlist rebuild;
3. test the exact stream/feed in VLC;
4. test the exact stream/feed on the Samsung IPTV application;
5. verify the actual language/content;
6. add or update its entry in `audit.json`;
7. rebuild;
8. confirm the resulting status on the dashboard.

Where a channel has multiple URLs, test each feed separately.

A successful result on one URL must not be assumed to apply to another URL.

---

# Generated files

The build writes its public output into:

```text
public/
```

## `tv.m3u`

```text
public/tv.m3u
```

The main generated IPTV playlist.

Public URL:

```text
https://tomkomaster.github.io/tomas-iptv/tv.m3u
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

# Adding another country

To add another country, for example Czechia:

## 1. Add the country name

`config.json` already contains:

```json
"CZ": "Czechia"
```

for future use.

## 2. Add a base source

Example:

```json
{
  "name": "IPTV-org Czechia",
  "kind": "base",
  "language_code": "CZ",
  "url": "https://iptv-org.github.io/iptv/countries/cz.m3u"
}
```

## 3. Optionally add raw alternatives

For example:

```json
{
  "name": "IPTV-org Czechia raw alternatives",
  "kind": "alternatives",
  "language_code": "CZ",
  "url": "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/cz.m3u"
}
```

## 4. Create a local extras file

```text
extras/cz.m3u
```

Then register it:

```json
{
  "name": "Our Czech test/verified extras",
  "kind": "extras",
  "language_code": "CZ",
  "path": "extras/cz.m3u"
}
```

The builder will then automatically use prefixes such as:

```text
[CZ OK]
[CZ TV]
[CZ PC]
[CZ ?]
```

and groups such as:

```text
Czechia | General
Czechia | News
Czechia | Music
```

No separate playlist-building program is required for each country.

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
│   └── sk.m3u
│
├── tests/
│   └── test_build.py
│
├── .github/
│   └── workflows/
│       └── build-and-publish.yml
│
└── public/                 # generated during the build
    ├── tv.m3u
    ├── index.html
    ├── channels.csv
    ├── duplicates.csv
    ├── excluded.csv
    ├── audit.csv
    ├── report.json
    ├── guide.xml           # only when EPG is enabled
    └── .nojekyll
```

The `public/` directory is generated output rather than the main source of truth.

The important editable source files are primarily:

```text
config.json
audit.json
extras/hu.m3u
extras/sk.m3u
build.py
tests/test_build.py
```

---

# Planned improvements

Possible next steps include:

* separate stable and experimental/test playlists;
* country-specific generated playlists;
* Czech channel support;
* expanded XMLTV/EPG support;
* additional native HLS source research;
* automated stream-health reporting;
* further dashboard/report improvements.

A future stable/test split could provide:

```text
tv.m3u
test.m3u
```

where `tv.m3u` is intended for normal family/friend use and `test.m3u` contains unresolved experimental candidates.

This split is **not implemented yet** and should not be treated as a currently available public URL.

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
