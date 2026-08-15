#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import date
from pathlib import Path

from epg_merge import (
    channel_index,
    fresh_count,
    load_xml,
    programme_index,
    read_playlist_rows,
)


COUNTRY_RE = re.compile(r"^[A-Z]{2}$")


def load_cross_country_aliases(
    path: Path | None,
) -> tuple[str, dict[str, dict[str, str]]]:
    """Load explicit aliases that intentionally read another country's guide.

    The existing flat ``aliases`` mapping remains handled by epg_merge and is
    therefore fully backward compatible. This separate section exists so a
    cross-country mapping can never happen by name/quality inference.
    """
    if path is None or not path.is_file():
        return "", {}

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("EPG alias file must contain a JSON object.")

    provider = str(data.get("provider") or "").strip()
    raw_aliases = data.get("cross_country_aliases") or {}
    if not isinstance(raw_aliases, dict):
        raise RuntimeError(
            "EPG alias file 'cross_country_aliases' must be a JSON object."
        )

    aliases: dict[str, dict[str, str]] = {}
    for raw_target, raw_spec in raw_aliases.items():
        target = str(raw_target or "").strip()
        if not target:
            raise RuntimeError("Cross-country EPG aliases may not have blank targets.")
        if not isinstance(raw_spec, dict):
            raise RuntimeError(
                f"Cross-country EPG alias {target!r} must contain an object."
            )

        playlist_country = str(
            raw_spec.get("playlist_country_code") or ""
        ).strip().upper()
        external_country = str(
            raw_spec.get("external_country_code") or ""
        ).strip().upper()
        external_id = str(raw_spec.get("external_id") or "").strip()

        if not COUNTRY_RE.fullmatch(playlist_country):
            raise RuntimeError(
                f"Cross-country EPG alias {target!r} has invalid "
                f"playlist_country_code {playlist_country!r}."
            )
        if not COUNTRY_RE.fullmatch(external_country):
            raise RuntimeError(
                f"Cross-country EPG alias {target!r} has invalid "
                f"external_country_code {external_country!r}."
            )
        if playlist_country == external_country:
            raise RuntimeError(
                f"Cross-country EPG alias {target!r} must reference a different "
                "external country. Use the normal 'aliases' section otherwise."
            )
        if not external_id:
            raise RuntimeError(
                f"Cross-country EPG alias {target!r} requires external_id."
            )

        aliases[target] = {
            "playlist_country_code": playlist_country,
            "external_country_code": external_country,
            "external_id": external_id,
        }

    return provider, aliases


def _external_path(
    external_dir: Path | None,
    country_code: str,
) -> Path | None:
    if external_dir is None:
        return None
    for name in (
        f"{country_code}.xml.gz",
        f"{country_code}.xml",
        f"{country_code}.download",
    ):
        candidate = external_dir / name
        if candidate.is_file():
            return candidate
    return None


def _load_external_country(
    external_dir: Path | None,
    country_code: str,
    cache: dict[str, dict],
) -> dict:
    if country_code in cache:
        return cache[country_code]

    path = _external_path(external_dir, country_code)
    if path is None:
        result = {"available": False, "error": "external guide not downloaded"}
        cache[country_code] = result
        return result

    try:
        root = load_xml(path)
        result = {
            "available": True,
            "path": path,
            "root": root,
            "channels": channel_index(root),
            "programmes": programme_index(root),
        }
    except Exception as exc:
        result = {
            "available": False,
            "path": path,
            "error": str(exc),
        }

    cache[country_code] = result
    return result


def _reported_fresh_count(item: dict | None) -> int | None:
    if not isinstance(item, dict) or "fresh_programmes" not in item:
        return None
    try:
        return int(item.get("fresh_programmes") or 0)
    except (TypeError, ValueError):
        return None


def apply_cross_country_aliases(
    *,
    country_code: str,
    playlist_path: Path,
    country_root: ET.Element,
    country_report: dict,
    aliases: dict[str, dict[str, str]],
    alias_provider: str,
    countries_cfg: dict,
    external_dir: Path | None,
    external_cache: dict[str, dict],
    reference_date: date | None,
    future_days: int,
) -> dict[str, object]:
    """Apply only explicit, fresh, cross-country EPG aliases.

    A target with current/future data from its own country's deterministic
    mapping is never replaced. A mapped-but-empty target may fall back to an
    explicit cross-country alias when that alias has fresh programme data.
    An alias whose foreign EPG entry has no current/future programmes leaves
    the existing mapping untouched.
    """
    code = str(country_code or "").strip().upper()
    playlist_ids = {
        tvg_id
        for tvg_id, _ in read_playlist_rows(playlist_path)
    }
    matched_items = [
        dict(item)
        for item in (country_report.get("matched") or [])
        if isinstance(item, dict)
    ]
    matched_by_id = {
        str(item.get("tvg_id") or "").strip(): item
        for item in matched_items
        if str(item.get("tvg_id") or "").strip()
    }
    matched_ids = set(matched_by_id)

    if reference_date is None:
        raw_reference = str(country_report.get("reference_date") or "").strip()
        reference_date = (
            date.fromisoformat(raw_reference)
            if raw_reference
            else date.today()
        )

    configured_targets = [
        target
        for target, spec in aliases.items()
        if spec.get("playlist_country_code") == code
    ]
    used: list[dict[str, object]] = []
    skipped: list[dict[str, object]] = []

    for target in configured_targets:
        if target not in playlist_ids:
            continue

        existing_match = matched_by_id.get(target)
        existing_fresh = _reported_fresh_count(existing_match)
        if existing_match is not None and (
            existing_fresh is None or existing_fresh > 0
        ):
            continue

        spec = aliases[target]
        source_code = spec["external_country_code"]
        external_id = spec["external_id"]
        source_cfg = countries_cfg.get(source_code) or {}
        if not isinstance(source_cfg, dict):
            source_cfg = {}
        source_external_cfg = source_cfg.get("external") or {}
        if not isinstance(source_external_cfg, dict):
            source_external_cfg = {}
        source_provider = str(
            source_external_cfg.get("provider") or "epgshare01.online"
        ).strip() or "epgshare01.online"

        if alias_provider and source_provider != alias_provider:
            raise RuntimeError(
                "Cross-country EPG alias provider mismatch for "
                f"{target}: alias file {alias_provider!r}, "
                f"{source_code} source {source_provider!r}."
            )

        source = _load_external_country(
            external_dir,
            source_code,
            external_cache,
        )
        if not source.get("available"):
            skipped.append({
                "tvg_id": target,
                "external_country_code": source_code,
                "provider_xmltv_id": external_id,
                "reason": str(source.get("error") or "external guide unavailable"),
            })
            continue

        source_channel = (source.get("channels") or {}).get(external_id)
        if source_channel is None:
            skipped.append({
                "tvg_id": target,
                "external_country_code": source_code,
                "provider_xmltv_id": external_id,
                "reason": "external XMLTV channel ID not present",
            })
            continue

        programmes = list((source.get("programmes") or {}).get(external_id, []))
        fresh_programmes = fresh_count(
            programmes,
            reference_date,
            max(int(future_days), 0),
        )
        if fresh_programmes <= 0:
            skipped.append({
                "tvg_id": target,
                "external_country_code": source_code,
                "provider_xmltv_id": external_id,
                "reason": "no current/future programme data",
            })
            continue

        replaced_provider = ""
        if existing_match is not None:
            replaced_provider = str(existing_match.get("provider") or "").strip()
            matched_items = [
                item
                for item in matched_items
                if str(item.get("tvg_id") or "").strip() != target
            ]
            matched_ids.discard(target)
            matched_by_id.pop(target, None)

            for channel in list(country_root.findall("channel")):
                if str(channel.get("id") or "").strip() == target:
                    country_root.remove(channel)
            for programme in list(country_root.findall("programme")):
                if str(programme.get("channel") or "").strip() == target:
                    country_root.remove(programme)

        channel_copy = copy.deepcopy(source_channel)
        channel_copy.set("id", target)
        country_root.append(channel_copy)

        seen_programmes: set[tuple[str, str, str]] = set()
        for programme in programmes:
            programme_copy = copy.deepcopy(programme)
            programme_copy.set("channel", target)
            key = (
                target,
                str(programme_copy.get("start") or ""),
                str(programme_copy.get("stop") or ""),
            )
            if key in seen_programmes:
                continue
            seen_programmes.add(key)
            country_root.append(programme_copy)

        match_item = {
            "tvg_id": target,
            "provider": source_provider,
            "provider_xmltv_id": external_id,
            "match_type": "external_explicit_cross_country_alias",
            "external_country_code": source_code,
            "fresh_programmes": fresh_programmes,
        }
        matched_items.append(match_item)
        matched_ids.add(target)
        matched_by_id[target] = match_item

        used_item: dict[str, object] = {
            "tvg_id": target,
            "external_country_code": source_code,
            "provider_xmltv_id": external_id,
            "fresh_programmes": fresh_programmes,
        }
        if replaced_provider:
            used_item["replaced_provider"] = replaced_provider
        used.append(used_item)

        providers = Counter({
            str(provider): int(count or 0)
            for provider, count in (country_report.get("providers") or {}).items()
        })
        if replaced_provider:
            providers[replaced_provider] -= 1
            if providers[replaced_provider] <= 0:
                del providers[replaced_provider]
        providers[source_provider] += 1
        country_report["providers"] = dict(sorted(providers.items()))

        fresh_providers = Counter({
            str(provider): int(count or 0)
            for provider, count in (
                country_report.get("fresh_channels_by_provider") or {}
            ).items()
        })
        fresh_providers[source_provider] += 1
        country_report["fresh_channels_by_provider"] = dict(
            sorted(fresh_providers.items())
        )

    country_report["matched"] = matched_items
    country_report["unmatched_tvg_ids"] = [
        tvg_id
        for tvg_id in (country_report.get("unmatched_tvg_ids") or [])
        if str(tvg_id).strip() not in matched_ids
    ]
    total = int(country_report.get("playlist_tvg_ids") or len(playlist_ids))
    mapped = len(matched_ids)
    country_report["matched_tvg_ids"] = mapped
    country_report["mapping_coverage_percent"] = round(
        mapped / total * 100.0 if total else 0.0,
        1,
    )

    external_info = country_report.get("external") or {}
    if not isinstance(external_info, dict):
        external_info = {}
    external_info["cross_country_aliases_configured"] = len(configured_targets)
    external_info["cross_country_aliases_used"] = used
    external_info["cross_country_aliases_skipped"] = skipped
    country_report["external"] = external_info

    return {
        "configured": len(configured_targets),
        "used": used,
        "skipped": skipped,
    }
