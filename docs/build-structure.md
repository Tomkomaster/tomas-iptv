# Build code structure

Tomas IPTV keeps command-line entrypoints and primary operator data easy to find at the repository root, while reusable implementation code is being moved gradually under `iptv/`.

## Root entrypoints and primary data

The root intentionally keeps files that are run directly or edited frequently, including:

- `build.py` — thin compatibility/CLI entrypoint
- `reliable_build.py` — production two-pass reliable build
- `healthcheck.py`, `attention.py`, EPG/research entrypoints — operational commands
- `config.json` — primary project configuration
- `audit.json` — persistent manual verification history

Operational entrypoints are not moved merely to make the root shorter; keeping their invocation paths stable is more important than cosmetic nesting.

## `iptv/` implementation package

The package now contains:

- `build_core.py` — transitional remainder of the historical monolithic builder
- `source_loader.py` — source definitions, remote/local loading and M3U parsing
- `playlist_writer.py` — generated M3U headers and playlist writing
- `dashboard.py` — dashboard rendering/publishing helpers
- `identity_overrides.py` — canonical channel identity resolution
- `source_concentration.py` — stable-source concentration reporting

`build.py` deliberately aliases imports to `iptv.build_core` so existing callers continue to use the same module globals. This is especially important for `stable_build.py`, which temporarily replaces feed-quality functions during the second reliable-build pass.

The large `build_core.py` is not the final architecture. It is a compatibility bridge that lets responsibilities be extracted one tested unit at a time instead of rewriting the builder in one risky change.

## `data/`

Slow-changing support data that is not the main project configuration can live under `data/`. Canonical identity corrections now live in:

```text
data/identity_overrides.json
```

`config.json` points to that file explicitly.

## Next extraction candidates

Good next steps, in roughly increasing coupling/risk, are:

1. audit parsing/validation/preparation (`audit.py`)
2. publication/country routing (`channel_routing.py`)
3. stable candidate selection (`stable_selection.py`)

Stable selection should move only together with an explicit home for the same-build health/feed-quality override hooks. The failover behavior must remain testable and must not depend on accidental module-global monkeypatching after that extraction.
