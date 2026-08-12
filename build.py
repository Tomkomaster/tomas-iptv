#!/usr/bin/env python3
"""Compatibility entrypoint for the Tomas IPTV build.

The implementation is being split gradually under ``iptv/``. Importers still
receive the build core module itself so existing tests and the same-build
failover monkeypatches keep targeting the globals that selection actually uses.
"""
from __future__ import annotations

import sys
from pathlib import Path

from iptv import dashboard as _dashboard
from iptv import identity_overrides as _identity_overrides
from iptv import playlist_writer as _playlist_writer
from iptv import source_loader as _source_loader
from iptv import source_concentration as _source_concentration


PROJECT_ROOT = Path(__file__).resolve().parent

# The packaged dashboard still reads repository-level templates/static assets.
_dashboard.MODULE_ROOT = PROJECT_ROOT
_dashboard.DASHBOARD_TEMPLATE = PROJECT_ROOT / "templates" / "dashboard.html"
_dashboard.DASHBOARD_STATIC = PROJECT_ROOT / "static"

# build_core still uses the historical absolute module names internally. Alias
# the relocated helpers before importing it; other entrypoints can migrate to
# package imports independently as they are touched.
sys.modules["dashboard"] = _dashboard
sys.modules["identity_overrides"] = _identity_overrides
sys.modules["source_concentration"] = _source_concentration

from iptv import build_core as _core  # noqa: E402  (aliases must exist first)


_core.ROOT = PROJECT_ROOT

# Source loading/parsing has moved out of the build core. Re-export the helpers
# through the historical build module API while the remaining core is extracted
# incrementally.
_core.ATTR_RE = _source_loader.ATTR_RE
_core.VALID_SOURCE_KINDS = _source_loader.VALID_SOURCE_KINDS
_core.http_get_text = _source_loader.http_get_text
_core.download_m3u = _source_loader.download_m3u
_core.split_extinf = _source_loader.split_extinf
_core.parse_entries = _source_loader.parse_entries
_core.normalize_source_kind = _source_loader.normalize_source_kind
_core.source_spec = _source_loader.source_spec


def _read_local(path: str) -> str:
    return _source_loader.read_local(PROJECT_ROOT, path)


_core.read_local = _read_local
_core.playlist_header = _playlist_writer.playlist_header


def _write_m3u_playlist(
    path: Path,
    cfg: dict,
    entries: list[dict],
    generated: str,
    playlist_label: str,
    name_style: str = "status",
) -> None:
    return _playlist_writer.write_m3u_playlist(
        path,
        cfg,
        entries,
        generated,
        playlist_label,
        name_style=name_style,
        strip_custom_prefix=_core.strip_custom_prefix,
        normalize_country_code=_core.normalize_country_code,
        rewrite_entry_lines=_core.rewrite_entry_lines,
    )


_core.write_m3u_playlist = _write_m3u_playlist


if __name__ == "__main__":
    try:
        args = sys.argv[1:]
        unknown_args = [arg for arg in args if arg != "--strict"]
        if unknown_args:
            raise RuntimeError(
                "Unknown command-line option(s): " + ", ".join(unknown_args)
            )

        strict = "--strict" in args
        if strict:
            print("Strict audit validation enabled.")

        _core.main(strict=strict)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
else:
    # Make ``import build`` return the implementation module, not a wrapper.
    # This preserves runtime monkeypatching used by stable_build.py.
    sys.modules[__name__] = _core
