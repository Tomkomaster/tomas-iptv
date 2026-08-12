from pathlib import Path

path = Path("README.md")
text = path.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    text = text.replace(old, new, 1)


def replace_section(start: str, end: str, replacement: str) -> None:
    global text
    start_token = start + "\n"
    end_token = end + "\n"
    start_i = text.find(start_token)
    if start_i < 0:
        raise RuntimeError(f"Missing section start: {start}")
    end_i = text.find(end_token, start_i + len(start_token))
    if end_i < 0:
        raise RuntimeError(f"Missing section end: {end}")
    text = text[:start_i] + replacement.rstrip() + "\n\n---\n\n" + text[end_i:]


replace_once(
    "The project combines public IPTV sources with manually researched Hungarian and Slovak channels, removes duplicate stream URLs, tracks playback testing, selects the best available feed for each channel, and publishes the result through GitHub Pages.",
    "The project combines public IPTV sources with manually researched Hungarian, Slovak and Czech channels, removes duplicate stream URLs, tracks playback testing, selects the best available feed for each channel, and publishes the result through GitHub Pages.",
    "intro countries",
)

replace_section(
    "## Public playlist",
    "## Currently supported countries",
    '''## Public playlists

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

Testing/research playlist:

```text
https://tomkomaster.github.io/tomas-iptv/test.m3u
```

Dashboard:

```text
https://tomkomaster.github.io/tomas-iptv/
```

The public URLs are intended to stay stable even as sources, channels and feeds change behind them.

The playlists can be used in IPTV applications, VLC, televisions, phones, tablets and other players that support M3U playlists.''',
)

replace_section(
    "## Currently supported countries",
    "## How the playlist is built",
    '''## Currently supported countries

The project currently treats all three countries as first-class outputs:

* 🇭🇺 Hungary (`HU`)
* 🇸🇰 Slovakia (`SK`)
* 🇨🇿 Czechia (`CZ`)

Each country has enabled upstream sources, a local extras file and its own generated stable playlist.''',
)

replace_section(
    "## How the playlist is built",
    "# Source types",
    '''## How the playlist is built

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
4. assigns every entry to its source/audit country scope;
5. identifies logical channels;
6. removes duplicate stream URLs globally;
7. keeps genuinely different feeds as alternatives;
8. applies manual results from `audit.json`;
9. uses confirmed spoken language to route verified streams to HU, SK or CZ when the result is unambiguous;
10. rejects manually excluded/unsupported feeds;
11. selects the preferred feed when a stable verified feed exists;
12. creates country/category `group-title` values;
13. generates the shared stable, testing and per-country playlists;
14. generates CSV and JSON reports;
15. generates the HTML dashboard.''',
)

replace_once(
    "```text\nIPTV-org Hungary\nIPTV-org Slovakia\n```",
    "```text\nIPTV-org Hungary\nIPTV-org Slovakia\nIPTV-org Czechia\n```",
    "base examples",
)

replace_once(
    "```text\nextras/hu.m3u\nextras/sk.m3u\n```",
    "```text\nextras/hu.m3u\nextras/sk.m3u\nextras/cz.m3u\n```",
    "extras files",
)

replace_section(
    "# Channel prefixes",
    "# Channel groups",
    '''# Channel prefixes

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

These labels describe playlist organization and playback verification, not broadcasting licences, copyright status or legal availability.''',
)

replace_section(
    "# Channel groups",
    "# Manual verification with `audit.json`",
    '''# Channel groups

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

Where useful, categories supplied by upstream sources are preserved.''',
)

replace_once(
    "[HU OK] / [SK OK]",
    "[HU OK] / [SK OK] / [CZ OK] in `test.m3u`",
    "playback status example",
)

replace_section(
    "# Language verification",
    "# Adding a Hungarian channel",
    '''# Language verification

The audit separately tracks the source/audit identity and the language actually heard during playback.

Important fields include:

```text
playlist_language_code
expected_language_codes
observed_language_codes
```

For a normal Czech candidate sourced from the Czech extras file:

```json
"playlist_language_code": "CZ",
"expected_language_codes": ["CZ"],
"observed_language_codes": ["CZ"]
```

`playlist_language_code` is the saved **audit/source scope**. It protects exact-URL audit identity when the same URL appears under unrelated channel identities or countries.

`observed_language_codes` records what was actually heard during the manual playback test.

For a verified stream with one unambiguous supported observed language, the confirmed spoken language determines its final published country. For example, if a stream was discovered in a Slovak source but manual playback confirms Czech speech, it is published once under `CZ`, not duplicated under `SK` and `CZ`.

Multilingual or ambiguous cases are not blindly duplicated across country outputs. Unsupported observed languages remain rejected until that country/language is actually supported.

Legacy fields such as:

```text
language
language_code
```

are still understood for compatibility with older audit entries.''',
)

replace_section(
    "# Adding a Hungarian channel",
    "# Testing a new channel",
    '''# Adding channels

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
"language_code": "CZ"
```

A new unresolved candidate normally appears as:

```text
[CZ ?] Example Czech TV
```

in `test.m3u`. After successful VLC/Samsung and language verification, the stable outputs are:

```text
tv.m3u -> [CZ] Example Czech TV
cz.m3u -> Example Czech TV
```''',
)

replace_section(
    "# Testing a new channel",
    "# Generated files",
    '''# Testing a new channel

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

Where a channel has multiple URLs, test each feed separately. A successful result on one URL must not be assumed to apply to another URL.''',
)

replace_section(
    "# Generated files",
    "## `index.html`",
    '''# Generated files

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
```''',
)

replace_section(
    "# Adding another country",
    "# GitHub Actions",
    '''# Current country configuration

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

There is no separate Czech builder: Czech entries go through the same deduplication, audit, stable-selection, language-routing, reporting and publication pipeline as HU and SK.''',
)

replace_section(
    "# Important files",
    "# Planned improvements",
    '''# Important files

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
```''',
)

replace_section(
    "# Planned improvements",
    "# Project philosophy",
    '''# Planned improvements

Possible next steps include:

* broader country-aware XMLTV/EPG coverage, especially Czech and Slovak providers;
* additional native HLS source research;
* continued stream-health and event-stream policy improvements;
* further dashboard/report improvements;
* continued refactoring of the builder as the project grows.

The stable/test split, per-country HU/SK/CZ playlists and Czech channel support are already implemented and are no longer future roadmap items.''',
)

path.write_text(text, encoding="utf-8")
