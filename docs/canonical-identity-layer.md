# Canonical channel identity layer

Canonical channel identity is intentionally separate from stream/feed identity, audit history, source provenance, and display formatting.

## Files

- `data/identity_overrides.json` contains manually curated canonical identities and selector rules.
- `iptv/identity_overrides.py` validates the file and resolves one current feed to at most one canonical identity.
- `config.json` only points to the identity data file through `identity_overrides_path`.

## Data model

`identities` is keyed by a stable manual canonical ID:

```json
{
  "identities": {
    "sk:kanal1": {
      "channel_name": "Kanal1",
      "tvg_name": "Kanal1",
      "tvg_id": "",
      "country_code": "SK",
      "language_codes": ["slk"]
    }
  }
}
```

A canonical identity describes the channel. Country geography and spoken-language metadata remain separate: `country_code` uses the two-letter country model, while `language_codes` uses ISO-639-3-style spoken-language codes.

A canonical identity does not contain playback test results, source URLs, research labels, health state, EPG health, or display prefixes.

`selectors` connect feed/source evidence to that identity:

```json
{
  "selectors": [
    {
      "match": {
        "url": "https://example.test/live.m3u8"
      },
      "canonical_id": "sk:kanal1"
    }
  ]
}
```

## Selector precedence

The resolver chooses the strongest matching evidence:

1. exact/canonicalized stream URL;
2. source name + exact `tvg-id`;
3. source name + normalized channel name;
4. an explicit `canonical-id` carried by the input entry.

Source names are whitespace-normalized and case-insensitive. Normalized-name selectors use Unicode normalization, case folding, and punctuation/whitespace folding. URL matching uses the same safe identity normalizations used elsewhere in the builder: host/scheme case, default ports, fragments, and empty paths are normalized while path case and query strings are preserved.

Duplicate selectors at the same selector key are rejected during load rather than silently depending on rule order.

## Separation of concerns

### Canonical channel identity

Stable manual ID plus canonical channel metadata. This is what downstream logical grouping should trust when present.

### Stream/feed identity

The playable URL and the metadata supplied by a particular source. Multiple feeds may resolve to the same canonical channel.

### Audit history

`audit.json` remains URL-oriented manual playback/language evidence. Moving or correcting canonical identity does not rewrite historical test results.

### Source provenance

`source`, source kind, comments, and research provenance remain attached to the feed. Canonicalization never pretends that an upstream provider became the broadcaster.

### Display formatting

Published prefixes, feed numbering, quality suffixes, and country/content groups are produced later. They are not part of canonical identity matching.

## Adding a new identity correction

1. Add or reuse a stable ID in `data/identity_overrides.json`.
2. Add the strongest safe selector available.
3. Prefer exact URL when the problem is unique to one feed.
4. Prefer source + `tvg-id` when URLs rotate but the provider metadata is stable.
5. Prefer source + normalized name only when the provider consistently names the same channel incorrectly.
6. Use an input `canonical-id` only for manually curated sources where the identity is already known at ingest time.

Do not put new one-off identity dictionaries back into `config.json`.
