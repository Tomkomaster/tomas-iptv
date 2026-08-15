# Tomas IPTV

Automatic IPTV playlist builder and manual stream-verification system for family and friends.

The project combines public IPTV sources with manually researched Hungarian, Slovak, Czech, Romanian, Austrian and Serbian channels, removes duplicate stream URLs, tracks playback testing, selects the best available feed for each channel, and publishes the result through GitHub Pages.

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
https://tomkomaster.github.io/tomas-iptv/ro.m3u
https://tomkomaster.github.io/tomas-iptv/at.m3u
https://tomkomaster.github.io/tomas-iptv/rs.m3u
```

Stable spoken-language playlists:

```text
https://tomkomaster.github.io/tomas-iptv/by-language/hun.m3u
https://tomkomaster.github.io/tomas-iptv/by-language/slk.m3u
https://tomkomaster.github.io/tomas-iptv/by-language/ces.m3u
https://tomkomaster.github.io/tomas-iptv/by-language/ron.m3u
https://tomkomaster.github.io/tomas-iptv/by-language/deu.m3u
https://tomkomaster.github.io/tomas-iptv/by-language/srp.m3u
```

Language playlists keep geography visible in the channel name. For example, a verified Hungarian-language Serbian station is published as `[RS] ...` inside `by-language/hun.m3u`; it is not moved into `hu.m3u` merely because it speaks Hungarian. Serbian-language output is enabled as `by-language/srp.m3u`, Romanian-language output is enabled as `by-language/ron.m3u`, and German-language output is enabled as `by-language/deu.m3u` for the German-speaking channels discovered through the currently configured country sources. The global IPTV-org German-language source (`languages/deu.m3u`) is intentionally **not** enabled, so adding Austria does not automatically import German-language channels from Germany, Switzerland or other countries.

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

The project currently treats all six countries as first-class outputs:

* 🇭🇺 Hungary (`HU`)
* 🇸🇰 Slovakia (`SK`)
* 🇨🇿 Czechia (`CZ`)
* 🇷🇴 Romania (`RO`)
* 🇦🇹 Austria (`AT`)
* 🇷🇸 Serbia (`RS`)

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

### Romania

1. IPTV-org Romania country playlist (base)
2. IPTV-org raw Romanian alternative streams
3. IPTV-org Romanian-language playlist
4. Our manually curated `extras/ro.m3u`

### Austria

1. IPTV-org Austria country playlist (base)
2. IPTV-org raw Austrian alternative streams
3. Our manually curated `extras/at.m3u`

Austria defines German (`deu`) as its default spoken language and publishes `by-language/deu.m3u`, but the global IPTV-org German-language playlist is deliberately not configured as a source yet.

### Serbia

1. IPTV-org Serbia country playlist (base)
2. IPTV-org raw Serbian alternative streams
3. IPTV-org Serbian-language playlist
4. Our manually curated `extras/rs.m3u`

Serbia defines Serbian (`srp`) as its default spoken language and publishes `by-language/srp.m3u`.

The sources are processed in configuration order.

The builder then:

1. downloads remote playlists;
2. reads the HU/SK/CZ/RO/AT/RS local extras;
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
IPTV-org Romania
IPTV-org Austria
IPTV-org Serbia
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
extras/ro.m3u
extras/at.m3u
extras/rs.m3u
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
[RO OK] Example Romanian TV
[RO ?] Example Romanian TV
[AT OK] Example Austrian TV
[AT ?] Example Austrian TV
[RS OK] Example Serbian TV
[RS ?] Example Serbian TV
```

Country codes are:

| Prefix | Country |
| ------ | ------- |
| `HU` | Hungary |
| `SK` | Slovakia |
| `CZ` | Czechia |
| `RO` | Romania |
| `AT` | Austria |
| `RS` | Serbia |

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
[RO] Example Romanian TV
[AT] Example Austrian TV
[RS] Example Serbian TV
```

## Per-country stable playlists

The country itself is already defined by the file, so generated country/status prefixes are omitted entirely:

```text
hu.m3u -> Duna
sk.m3u -> JOJ
cz.m3u -> Prima
ro.m3u -> Example Romanian TV
at.m3u -> Example Austrian TV
rs.m3u -> Example Serbian TV
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

Romania | General
Romania | Music
Romania | News
Romania | Sports

Austria | General
Austria | Music
Austria | News
Austria | Sports

Serbia | General
Serbia | Music
Serbia | News
Serbia | Sports
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
  "playlist_country_code": "HU",
  "output_country_code": "HU",
  "vlc": "works",
  "samsung": "works",
  "vlc_note": "ok",
  "samsung_note": "ok",
  "expected_language_codes": ["hun"],
  "observed_language_codes": ["hun"],
  "decision": "auto",
  "exclude_from_playlist": false,
  "tested_on": "2026-08-10",
  "provenance": "Official broadcaster",
  "discovery": "Manual research",
  "notes": "Passed both playback tests."
}
```

Not every field is required for every record.

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
[HU OK] / [SK OK] / [CZ OK] / [RO OK] / [AT OK] / [RS OK] in `test.m3u`
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

Source/channel metadata uses:

```json
{
  "country_code": "AT",
  "language_codes": ["deu"]
}
```

`country_code` is the publication/audit geography (ISO-3166-style two-letter code). `language_codes` contains spoken/content languages using ISO-639-3-style codes such as `hun`, `slk`, `ces`, `deu`, `srp` or `ron`.

Manual audit/export rows use:

```text
playlist_country_code
output_country_code
expected_language_codes
observed_language_codes
```

The first two are countries. The latter two are spoken-language evidence and use ISO-639-3-style values such as `hun`, `slk`, `ces`, `ron`, `deu` or `srp`.

Verified streams are **not** generically routed by language. Current HU/SK/CZ cross-routing is explicitly configured in `verified_country_routes`, for example `SK + ces -> CZ`. Romania and Serbia remain their own geographies even when a station is verified in another spoken language; such a station can also appear in the appropriate by-language playlist without being moved to another country output.

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

Use the extras file for the country where the candidate belongs. Do **not** manually add `[HU ...]`, `[SK ...]`, `[CZ ...]`, `[RO ...]`, `[AT ...]` or `[RS ...]` prefixes to source names; the builder formats generated playlists automatically.

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

## Adding a Romanian channel

Edit:

```text
extras/ro.m3u
```

Example:

```text
# Example Romanian TV — direct official HLS candidate
#EXTINF:-1 tvg-id="ExampleTV.ro" tvg-name="Example Romanian TV" group-title="General",Example Romanian TV
https://example.ro/live/playlist.m3u8
```

`extras/ro.m3u` is configured with:

```json
"country_code": "RO",
"language_codes": ["ron"]
```

A new unresolved candidate normally appears as:

```text
[RO ?] Example Romanian TV
```

in `test.m3u`. After successful VLC/Samsung and language verification, the stable outputs are:

```text
tv.m3u -> [RO] Example Romanian TV
ro.m3u -> Example Romanian TV
```

## Adding an Austrian channel

Edit:

```text
extras/at.m3u
```

Example:

```text
# Example Austrian TV — direct official HLS candidate
#EXTINF:-1 tvg-id="ExampleTV.at" tvg-name="Example Austrian TV" group-title="General",Example Austrian TV
https://example.at/live/playlist.m3u8
```

`extras/at.m3u` is configured with:

```json
"country_code": "AT",
"language_codes": ["deu"]
```

A new unresolved candidate normally appears as:

```text
[AT ?] Example Austrian TV
```

in `test.m3u`. After successful VLC/Samsung and language verification, the stable outputs are:

```text
tv.m3u -> [AT] Example Austrian TV
at.m3u -> Example Austrian TV
by-language/deu.m3u -> [AT] Example Austrian TV
```

## Adding a Serbian channel

Edit:

```text
extras/rs.m3u
```

Example:

```text
# Example Serbian TV — direct official HLS candidate
#EXTINF:-1 tvg-id="ExampleTV.rs" tvg-name="Example Serbian TV" group-title="General",Example Serbian TV
https://example.rs/live/playlist.m3u8
```

`extras/rs.m3u` is configured with:

```json
"country_code": "RS",
"language_codes": ["srp"]
```

A new unresolved candidate normally appears as:

```text
[RS ?] Example Serbian TV
```

in `test.m3u`. After successful VLC/Samsung and language verification, the stable outputs are:

```text
tv.m3u -> [RS] Example Serbian TV
rs.m3u -> Example Serbian TV
by-language/srp.m3u -> [RS] Example Serbian TV
```

---

# Testing a new channel

The same manual workflow applies to Hungarian, Slovak, Czech, Romanian, Austrian and Serbian candidates:

1. add the exact candidate URL to `extras/hu.m3u`, `extras/sk.m3u`, `extras/cz.m3u`, `extras/ro.m3u`, `extras/at.m3u` or `extras/rs.m3u` as appropriate;
2. let the playlist rebuild;
3. find the candidate in `test.m3u` (`[HU ?]`, `[SK ?]`, `[CZ ?]`, `[RO ?]`, `[AT ?]` or `[RS ?]` initially);
4. test that exact stream/feed in VLC;
5. test that exact stream/feed on the Samsung IPTV application;
6. verify the actual channel identity and spoken language/content;
7. add or update the exact-URL entry in `audit.json`;
8. rebuild and confirm the resulting status on the dashboard;
9. confirm stable results use the correct country prefix in `tv.m3u` and plain names in their country playlists.

A typical Austrian audit record can look like:

```json
{
  "channel": "Example Austrian TV",
  "stream_url": "https://example.at/live/playlist.m3u8",
  "playlist_country_code": "AT",
  "output_country_code": "AT",
  "expected_language_codes": ["deu"],
  "observed_language_codes": ["deu"],
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

Shared stable family/friends playlist containing HU, SK, CZ, RO, AT and RS channels. Stable names use country prefixes such as `[HU]`, `[SK]`, `[CZ]`, `[RO]`, `[AT]` and `[RS]`.

```text
https://tomkomaster.github.io/tomas-iptv/tv.m3u
```

## `test.m3u`

Testing/research playlist. This is where diagnostic status prefixes such as `[HU OK]`, `[SK ?]`, `[CZ ?]`, `[RO ?]`, `[AT ?]` and `[RS ?]` remain visible.

```text
https://tomkomaster.github.io/tomas-iptv/test.m3u
```

## Country playlists

Stable country-specific outputs use plain channel names because the country is already implied by the playlist:

```text
public/hu.m3u -> https://tomkomaster.github.io/tomas-iptv/hu.m3u
public/sk.m3u -> https://tomkomaster.github.io/tomas-iptv/sk.m3u
public/cz.m3u -> https://tomkomaster.github.io/tomas-iptv/cz.m3u
public/ro.m3u -> https://tomkomaster.github.io/tomas-iptv/ro.m3u
public/at.m3u -> https://tomkomaster.github.io/tomas-iptv/at.m3u
public/rs.m3u -> https://tomkomaster.github.io/tomas-iptv/rs.m3u
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
* country placement;
* spoken-language information;
* audit decisions;
* exclusions;
* testing dates;
* notes;
* whether the exact feed is currently in the playlist.

Country-related export columns use `playlist_country_code` and `output_country_code`. Spoken-language evidence uses `expected_language_codes` and `observed_language_codes`.

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

Romania, Austria and Serbia have their own EPG country configurations and external guide sources, alongside the Hungary, Slovakia and Czechia EPG configurations. Austria uses EPGShare `AT1` and Serbia uses EPGShare `RS1` as their configured external sources.

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

A simplified modern structure looks like:

```json
{
  "site_title": "Tomas IPTV",
  "default_country_code": "HU",
  "default_language_codes": ["hun"],

  "country_names": {
    "HU": "Hungary",
    "SK": "Slovakia",
    "CZ": "Czechia",
    "RO": "Romania",
    "AT": "Austria",
    "RS": "Serbia"
  },
  "country_outputs": {
    "HU": "public/hu.m3u",
    "SK": "public/sk.m3u",
    "CZ": "public/cz.m3u",
    "RO": "public/ro.m3u",
    "AT": "public/at.m3u",
    "RS": "public/rs.m3u"
  },

  "language_names": {
    "hun": "Hungarian",
    "slk": "Slovak",
    "ces": "Czech",
    "ron": "Romanian",
    "deu": "German",
    "srp": "Serbian"
  },
  "language_outputs": {
    "hun": "public/by-language/hun.m3u",
    "slk": "public/by-language/slk.m3u",
    "ces": "public/by-language/ces.m3u",
    "ron": "public/by-language/ron.m3u",
    "deu": "public/by-language/deu.m3u",
    "srp": "public/by-language/srp.m3u"
  },

  "output": "public/tv.m3u",
  "audit_path": "audit.json",
  "sources": [],
  "extras": []
}
```

A fixed-country remote source uses separate country and spoken-language metadata:

```json
{
  "name": "Example source",
  "kind": "base",
  "country_code": "HU",
  "language_codes": ["hun"],
  "url": "https://example.com/list.m3u"
}
```

A local extras source uses the same model:

```json
{
  "name": "Example extras",
  "kind": "extras",
  "country_code": "HU",
  "language_codes": ["hun"],
  "path": "extras/example.m3u"
}
```

Language-wide sources should use `country_mode: "tvg_id"` so geography comes from each channel's `tvg-id` rather than from the language of the source. German output is configured, but a German-wide upstream source is not currently enabled.

---

# Current country configuration

HU, SK, CZ, RO, AT and RS are fully enabled as first-class country outputs. `config.json` defines all six country names and generated country outputs:

```json
"country_names": {
  "HU": "Hungary",
  "SK": "Slovakia",
  "CZ": "Czechia",
  "RO": "Romania",
  "AT": "Austria",
  "RS": "Serbia"
},
"country_outputs": {
  "HU": "public/hu.m3u",
  "SK": "public/sk.m3u",
  "CZ": "public/cz.m3u",
  "RO": "public/ro.m3u",
  "AT": "public/at.m3u",
  "RS": "public/rs.m3u"
}
```

Romania has the base country playlist, raw alternatives, Romanian-language playlist and local extras enabled. Austria has the base country playlist, raw alternatives and local extras enabled, with German (`deu`) configured as its spoken-language output. Serbia has the base country playlist, raw alternatives, Serbian-language playlist and local extras enabled, with Serbian (`srp`) configured as its spoken-language output:

```text
IPTV-org Romania
IPTV-org Romania raw alternatives
IPTV-org Romanian language
extras/ro.m3u

IPTV-org Austria
IPTV-org Austria raw alternatives
extras/at.m3u
by-language/deu.m3u

IPTV-org Serbia
IPTV-org Serbia raw alternatives
IPTV-org Serbian language
extras/rs.m3u
by-language/srp.m3u
```

The global IPTV-org German-language playlist is intentionally not enabled for Austria. This keeps the Austrian expansion country-scoped instead of importing the wider German-language catalog.

There is no separate Romanian, Austrian or Serbian builder: entries from all three countries go through the same deduplication, audit, stable-selection, language-routing, reporting and publication pipeline as HU, SK and CZ.

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
│   ├── cz.m3u
│   ├── ro.m3u
│   ├── at.m3u
│   └── rs.m3u
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
    ├── ro.m3u
    ├── at.m3u
    ├── rs.m3u
    ├── by-language/
    │   ├── hun.m3u
    │   ├── slk.m3u
    │   ├── ces.m3u
    │   ├── ron.m3u
    │   ├── deu.m3u
    │   └── srp.m3u
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
extras/ro.m3u
extras/at.m3u
extras/rs.m3u
build.py
tests/
```

---

# Planned improvements

Possible next steps include:

* broader country-aware XMLTV/EPG coverage, including continued work on Austrian, Czech, Slovak, Romanian and Serbian mappings;
* additional native HLS source research;
* continued stream-health and event-stream policy improvements;
* further dashboard/report improvements;
* continued refactoring of the builder as the project grows.

The stable/test split, per-country HU/SK/CZ/RO/AT/RS playlists and Austrian/Czech/Romanian/Serbian country support are already implemented and are no longer future roadmap items.

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