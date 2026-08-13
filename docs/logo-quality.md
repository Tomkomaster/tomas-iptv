# Canonical channel logos

Channel logos are a presentation-quality dimension for the stable family playlist.
The build **does not scrape or discover logos automatically**.

## Manual authority

Reviewed logo mappings live in `data/logo_overrides.json`. Each entry must contain:

- exactly one supported selector;
- an absolute HTTPS `logo` URL;
- non-empty `source` provenance explaining where the image came from;
- an optional `note`.

Supported selectors, in descending precedence, are:

1. `canonical_id`
2. `country_code` + `tvg_id`
3. `country_code` + `channel`

Example:

```json
{
  "match": {"country_code": "HU", "tvg_id": "M1.hu"},
  "logo": "https://example.invalid/m1.png",
  "source": "official broadcaster asset",
  "note": "Reviewed manually"
}
```

Do not add a mapping merely because an image search found something plausible.
The provenance requirement is deliberate.

## Source fallback

Existing upstream `tvg-logo` metadata remains usable so current playlists do not
lose artwork. When no reviewed override exists, all feeds of the same logical
channel are normalized to one existing source logo and classified as **Source
fallback**. Source fallback is not counted as canonical coverage.

The stable dashboard uses three mutually exclusive states:

- **Canonical** — reviewed override from `logo_overrides.json`;
- **Source fallback** — existing upstream `tvg-logo`, normalized across feeds;
- **Missing** — no usable logo URL.

## Generated quality report

Every build writes:

- `public/logo-quality.json`
- `public/missing-logos.csv`

`logo_availability_percent` counts Canonical + Source fallback channels.
`canonical_logo_coverage_percent` counts only reviewed canonical mappings.
Both metrics use stable logical channels rather than stream URLs, so alternate
feeds do not inflate coverage.

The report measures mapping availability, not whether the remote image server is
currently reachable. A future logo-health probe can be added separately without
changing the manual mapping authority.
