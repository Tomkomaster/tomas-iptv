# Multi-country external EPG

External XMLTV fallback is configured per country under `epg.countries.<CC>.external`. The current production sources are:

- HU -> `epg_ripper_HU1.xml.gz`
- SK -> `epg_ripper_SK1.xml.gz`
- CZ -> `epg_ripper_CZ1.xml.gz`

The publish workflow downloads each configured external source independently. A failed download degrades only that country to IPTV-org EPG fallbacks.

`epg_multi_merge.py` runs the existing `epg_merge.merge_guides()` logic once per stable country playlist and then recombines the generated XMLTV channels, programmes, coverage, provider counts and country reports. This deliberately scopes name-based external matching to one publication country at a time.

The final public interface remains unchanged:

```text
public/guide.xml
public/epg-coverage.json
```

The coverage report keeps the previous aggregate `external` fields and adds `external.countries` so HU/SK/CZ availability, freshness and mapping diagnostics can be inspected separately.
