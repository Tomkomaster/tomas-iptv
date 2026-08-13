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

- `build_core.py` — build orchestration, ROOT-aware I/O shims and compatibility wrappers
- `channel_identity.py` — logical channel identity, canonical stream URLs and safe display-name normalization
- `source_loader.py` — source definitions, remote/local loading and M3U parsing; `build_core.py` no longer carries duplicate parser/downloader implementations
- `deduplication.py` — source collection, canonical identity application, global URL deduplication and source contribution stats
- `playlist_writer.py` — generated M3U headers and playlist writing
- `publication.py` — published names, content groups and EXTINF metadata rewriting
- `reports.py` — channel/report context, previous-build diffing, country/language summaries, CSV/machine-report exports and console summaries
- `playback_status.py` — shared VLC/Samsung manual-test status normalization
- `language_routing.py` — spoken-language interpretation, publication-country routing, country naming and language-catalog assembly
- `audit.py` — manual playback audit validation, decisions and stream-history preparation
- `feed_selection.py` — current-feed suppression and complete test-playlist candidate selection
- `stable_selection.py` — stable-family filtering and callback-driven best-feed ranking
- `dashboard.py` — dashboard rendering/publishing helpers
- `identity_overrides.py` — canonical channel identity resolution
- `source_concentration.py` — stable-source concentration reporting

`build.py` deliberately aliases imports to `iptv.build_core` so existing callers continue to use the same module globals. This is especially important for `tools/stable_build.py`, which temporarily replaces feed-quality functions during the second reliable-build pass.

`build_core.py` is now intentionally the orchestration/compatibility layer rather than the home of the build subsystems. `main()` coordinates configuration, source collection, audit preparation, candidate/stable selection, publication, playlist outputs, reports and dashboard generation. Thin wrappers remain where live module globals are part of the compatibility contract. In particular, stable selection receives the current feed-quality functions as callbacks so same-build failover can continue to replace `build.score_feed_quality` safely at runtime.

The test suite enforces that `iptv/build_core.py` stays below 20 KB. New parsing, identity, audit, routing, selection, publication or reporting behavior should normally be added to its owning module rather than growing the core again.

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

The original build-core breakup is substantially complete. Future structural work should be smaller and driven by real maintenance needs rather than file-size targets:

1. move the remaining widely imported root libraries (`country_language.py`, `feed_quality.py`, `health_policy.py`, `research_priority.py`, `wanted_channels.py`) into `iptv/` one at a time when their callers are touched;
2. move ROOT-aware audit/source file loading only if a clean path-based API is useful elsewhere;
3. extract playlist-output orchestration only if country/language output rules become complex enough to deserve their own subsystem;
4. keep the `build` compatibility facade until intentionally making a breaking API change.

Do not bypass the callback boundary in stable selection: same-build verified-feed failover depends on the live scoring hooks remaining explicit and testable.
