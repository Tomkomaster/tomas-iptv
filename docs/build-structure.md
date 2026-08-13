# Build code structure

Tomas IPTV keeps the repository root intentionally small. Primary operator data and the main build entrypoint stay visible; subsystem commands, EPG code and support data are grouped by purpose.

## Repository root

The root now mainly contains:

- `README.md` — project documentation
- `build.py` — thin compatibility/CLI entrypoint
- `run_tests.py` — stable unittest runner for the organized package paths
- `config.json` — primary project configuration
- `audit.json` — persistent manual verification history
- shared compatibility/library modules that are still being extracted gradually
- the top-level subsystem/data folders

The remaining shared root modules (`country_language.py`, `feed_quality.py`, `health_policy.py`, `research_priority.py`, `wanted_channels.py`) are kept temporarily because they are widely imported. They can move into `iptv/` in later tested refactors instead of being relocated cosmetically all at once.

## `tools/` operational commands

Operational commands that used to sit beside `build.py` now live together:

- `tools/reliable_build.py` — production two-pass reliable build
- `tools/healthcheck.py` — stable stream health
- `tools/attention.py` — advisory attention queue
- `tools/research_exports.py` — research/coverage exports
- `tools/migrate_audit.py` — audit migration utility
- `tools/same_build_failover.py` — current verified-redundancy probing
- `tools/stable_build.py` — same-build stable-selection evidence overlay

Invoke them as modules from the repository root, for example:

```bash
python3 -m tools.reliable_build --strict
python3 -m tools.healthcheck --health-policy data/health_policy.json
```

## `epg/` subsystem

All Python code for XMLTV/EPG preparation, merging, local overlays, policy and health now lives under `epg/`:

- `epg/epg_prepare.py`
- `epg/epg_country_prepare.py`
- `epg/epg_merge.py`
- `epg/epg_multi_merge.py`
- `epg/epg_cross_country_alias.py`
- `epg/epg_policy.py`
- `epg/epg_health.py`
- `epg/local_epg.py`

GitHub Actions invokes these with `python3 -m epg.<module>` so the folder is both visually grouped and a real Python package.

## `iptv/` implementation package

The core implementation package contains:

- `build_core.py` — transitional build orchestration and remaining coupled subsystems
- `channel_identity.py` — logical channel identity, canonical stream URLs and safe display-name normalization
- `source_loader.py` — source definitions, remote/local loading and M3U parsing; `build_core.py` no longer carries duplicate parser/downloader implementations
- `deduplication.py` — source collection, canonical identity application, global URL deduplication and source contribution stats
- `playlist_writer.py` — generated M3U headers and playlist writing
- `publication.py` — published names, content groups and EXTINF metadata rewriting
- `reports.py` — country/language build summaries and CSV export helpers
- `playback_status.py` — shared VLC/Samsung manual-test status normalization
- `language_routing.py` — spoken-language interpretation, publication-country routing, country naming and language-catalog assembly
- `audit.py` — manual playback audit validation, decisions and stream-history preparation
- `feed_selection.py` — current-feed suppression and complete test-playlist candidate selection
- `stable_selection.py` — stable-family filtering and callback-driven best-feed ranking
- `dashboard.py` — dashboard rendering/publishing helpers
- `identity_overrides.py` — canonical channel identity resolution
- `source_concentration.py` — stable-source concentration reporting

`build.py` deliberately aliases imports to `iptv.build_core` so existing callers continue to use the same module globals. This is especially important for `tools/stable_build.py`, which temporarily replaces feed-quality functions during the second reliable-build pass.

The large `build_core.py` is not the final architecture. It is a compatibility bridge that lets responsibilities be extracted one tested unit at a time instead of rewriting the builder in one risky change. Channel identity/name normalization is now one of those extracted units; audit, routing and stable selection remain the larger coupled blocks.

## `data/`

Slow-changing support/policy data is grouped under `data/` rather than scattered around the root:

```text
data/identity_overrides.json
data/epg_aliases.json
data/epg_policy.json
data/health_policy.json
data/research_priority.json
data/wanted_channels.json
```

`config.json` remains at the root because it is the primary project configuration.

## Tests

Use the repository test runner:

```bash
python3 run_tests.py
```

It makes the transitional `tools/` and `epg/` module locations available to legacy unit-test imports while those imports are migrated gradually.

## Next extraction candidates

Good next steps, in roughly increasing coupling/risk, are:

1. audit parsing/validation/preparation (`iptv/audit.py`)
2. publication/country routing (`iptv/channel_routing.py`)
3. stable candidate selection (`iptv/stable_selection.py`)
4. move the remaining shared root library modules into `iptv/` as their callers are touched

Stable selection should move only together with an explicit home for the same-build health/feed-quality override hooks. The failover behavior must remain testable and must not depend on accidental module-global monkeypatching after that extraction.
