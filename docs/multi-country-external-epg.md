# Multi-country external EPG

External XMLTV fallback is configured per country under `epg.countries.<CC>.external`. The current production sources are:

- HU -> `epg_ripper_HU1.xml.gz`
- SK -> `epg_ripper_SK1.xml.gz`
- CZ -> `epg_ripper_CZ1.xml.gz`
- RO -> `epg_ripper_RO1.xml.gz`
- AT -> `epg_ripper_AT1.xml.gz`

The publish workflow downloads each configured external source independently. A failed download degrades only that country to IPTV-org EPG fallbacks.

`epg_multi_merge.py` runs the existing `epg_merge.merge_guides()` logic once per stable country playlist and then recombines the generated XMLTV channels, programmes, coverage, provider counts and country reports. This deliberately scopes name-based external matching to one publication country at a time.

The final public interface remains unchanged:

```text
public/guide.xml
public/epg-coverage.json
```

The coverage report keeps the previous aggregate `external` fields and adds `external.countries` so HU/SK/CZ/RO/AT availability, freshness and mapping diagnostics can be inspected separately.

## Explicit alias policy

Automatic external matching remains country-scoped: each stable country playlist is inferred only against that country's configured external guide. Runtime fuzzy matching is intentionally not used.

`epg_aliases.json` is the audited exception layer. Normal `aliases` map an exact playlist `tvg-id` to an exact XMLTV ID in the same country's EPGshare guide. `cross_country_aliases` additionally declare both the playlist country and the external guide country. This is useful when EPGshare carries a station in a neighboring country's package but not in its geographic guide. Cross-country aliases are applied only when the declared external XMLTV ID has current/future programme data; stale or empty mappings remain unmatched rather than inflating coverage.

This keeps identification improvements deterministic and reviewable while leaving provider scraping unchanged.
