#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import urllib.request
from datetime import date, datetime, timezone
from urllib.parse import urlparse, urlunparse


DEFAULT_WEIGHTS = {
    "samsung_works": 100,
    "vlc_works": 60,
    "vlc_works_with_warning": 50,
    "official_broadcaster": 50,
    "broadcaster_cdn": 30,
    "https": 20,
    "current_epg": 20,
    "high_definition": 10,
    "recent_manual_test": 10,
    "redirect": -15,
    "tls_certificate_warning": -25,
    "provider_relay": -30,
    "health_warning": -40,
    "stale_manual_test": -50,
    "event_only": -80,
}

DEFAULT_PROVIDER_RELAY_TERMS = (
    "antik",
    "panaccess",
    "lexanetwork",
    "rebit",
    "kabelko",
    "provider relay",
)

DEFAULT_OFFICIAL_SOURCE_TERMS = (
    "official broadcaster",
    "current broadcaster stream",
    "direct broadcaster",
    "broadcaster stream",
    "broadcaster cdn",
)

DEFAULT_BROADCASTER_CDN_TERMS = (
    "broadcaster cdn",
    "direct joj cdn",
    "joj cdn",
)

HIGH_DEFINITION_RE = re.compile(
    r"(?<!\d)(?:1080p|1440p|2160p)(?!\d)|\b(?:FHD|UHD|4K)\b",
    re.IGNORECASE,
)


def canonical_stream_url(url: str) -> str:
    """Normalize a stream URL only for evidence lookup/identity comparison."""
    value = str(url or "").strip()
    if not value:
        return ""

    parsed = urlparse(value)
    scheme = parsed.scheme.lower()
    if not scheme or not parsed.netloc or parsed.hostname is None:
        return value

    hostname = parsed.hostname.lower()
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"

    userinfo = ""
    if "@" in parsed.netloc:
        userinfo = parsed.netloc.rsplit("@", 1)[0] + "@"

    try:
        port = parsed.port
    except ValueError:
        return value

    if (scheme == "https" and port == 443) or (scheme == "http" and port == 80):
        port = None

    netloc = f"{userinfo}{hostname}"
    if port is not None:
        netloc += f":{port}"

    return urlunparse((
        scheme,
        netloc,
        parsed.path or "/",
        parsed.params,
        parsed.query,
        "",
    ))


def _quality_config(cfg: dict | None) -> dict:
    cfg = cfg or {}
    stable = cfg.get("stable_playlist") or {}
    quality = stable.get("feed_quality") or {}
    return quality if isinstance(quality, dict) else {}


def _weights(cfg: dict | None) -> dict[str, int]:
    quality = _quality_config(cfg)
    configured = quality.get("weights") or {}
    output = dict(DEFAULT_WEIGHTS)
    if isinstance(configured, dict):
        for key, value in configured.items():
            if key not in output:
                continue
            try:
                output[key] = int(value)
            except (TypeError, ValueError):
                continue
    return output


def _term_list(cfg: dict | None, key: str, default: tuple[str, ...]) -> tuple[str, ...]:
    quality = _quality_config(cfg)
    configured = quality.get(key)
    if not isinstance(configured, list):
        return default
    values = tuple(
        str(value).strip().casefold()
        for value in configured
        if str(value).strip()
    )
    return values or default


def _parse_quality_flags(entry: dict, audit: dict) -> set[str]:
    raw_values = []
    for raw in (entry.get("quality_flags"), audit.get("quality_flags")):
        if isinstance(raw, str):
            raw_values.extend(re.split(r"[,;|]", raw))
        elif isinstance(raw, (list, tuple, set)):
            raw_values.extend(raw)
    return {
        str(value).strip().casefold().replace("-", "_").replace(" ", "_")
        for value in raw_values
        if str(value).strip()
    }


def _text_haystack(entry: dict, audit: dict) -> str:
    values = [
        entry.get("source"),
        entry.get("channel_name"),
        entry.get("display_name"),
        entry.get("tvg_name"),
        entry.get("group_title"),
        entry.get("url"),
        audit.get("channel"),
        audit.get("source"),
        audit.get("discovery"),
        audit.get("provenance"),
        audit.get("reason"),
        audit.get("notes"),
    ]
    return " ".join(str(value or "") for value in values).casefold()


def _normalized_status(value: object) -> str:
    return (
        str(value or "")
        .strip()
        .casefold()
        .replace("-", "_")
        .replace(" ", "_")
    )


def _parse_test_date(value: object) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _safe_remote_json(url: str, timeout: float) -> tuple[dict, str]:
    if not str(url or "").strip():
        return {}, ""
    try:
        req = urllib.request.Request(
            str(url).strip(),
            headers={
                "User-Agent": "Mozilla/5.0 Tomas-IPTV-Feed-Quality/1.0",
                "Accept": "application/json,*/*",
                "Cache-Control": "no-cache",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8-sig", errors="replace"))
        return (payload if isinstance(payload, dict) else {}), ""
    except Exception as exc:  # best-effort historical evidence only
        return {}, f"{type(exc).__name__}: {exc}"


def _derived_public_url(cfg: dict, filename: str) -> str:
    epg = cfg.get("epg") or {}
    public_url = str(epg.get("public_url") or "").strip()
    if not public_url or "/" not in public_url:
        return ""
    return public_url.rsplit("/", 1)[0] + "/" + filename


def build_feed_quality_context(
    cfg: dict | None,
    *,
    reference_date: date | None = None,
    fetch_remote: bool = True,
) -> dict:
    """
    Build optional historical evidence used by feed scoring.

    Selection runs before the current build's health/EPG jobs, so only the
    previous deployed reports may be consulted. Failure to fetch any report is
    deliberately non-fatal; manual VLC/Samsung verification remains authority.
    """
    cfg = cfg or {}
    quality = _quality_config(cfg)
    today = reference_date or datetime.now(timezone.utc).date()

    try:
        timeout = max(float(quality.get("evidence_timeout_seconds") or 4), 0.5)
    except (TypeError, ValueError):
        timeout = 4.0

    health_url = str(
        quality.get("previous_health_url")
        or ((cfg.get("health") or {}).get("previous_url"))
        or ""
    ).strip()
    coverage_url = str(
        quality.get("previous_epg_coverage_url")
        or _derived_public_url(cfg, "epg-coverage.json")
    ).strip()
    epg_health_url = str(
        quality.get("previous_epg_health_url")
        or _derived_public_url(cfg, "epg-health.json")
    ).strip()

    health_data = {}
    coverage_data = {}
    epg_health_data = {}
    errors: dict[str, str] = {}

    if fetch_remote:
        health_data, error = _safe_remote_json(health_url, timeout)
        if error:
            errors["health"] = error
        coverage_data, error = _safe_remote_json(coverage_url, timeout)
        if error:
            errors["epg_coverage"] = error
        epg_health_data, error = _safe_remote_json(epg_health_url, timeout)
        if error:
            errors["epg_health"] = error

    health_by_url = {}
    for stream in health_data.get("streams", []) or []:
        if not isinstance(stream, dict):
            continue
        key = canonical_stream_url(str(stream.get("stream_url") or ""))
        if key:
            health_by_url[key] = stream

    epg_mapped_ids = {
        str(item.get("tvg_id") or "").strip()
        for item in (coverage_data.get("matched") or [])
        if isinstance(item, dict) and str(item.get("tvg_id") or "").strip()
    }
    epg_empty_ids = {
        str(item.get("tvg_id") or "").strip()
        for item in (epg_health_data.get("mapped_without_programmes") or [])
        if isinstance(item, dict) and str(item.get("tvg_id") or "").strip()
    }

    return {
        "reference_date": today,
        "health_by_url": health_by_url,
        "epg_mapped_ids": epg_mapped_ids,
        "epg_empty_ids": epg_empty_ids,
        "evidence_urls": {
            "health": health_url,
            "epg_coverage": coverage_url,
            "epg_health": epg_health_url,
        },
        "evidence_errors": errors,
    }


def score_feed_quality(
    entry: dict,
    cfg: dict | None = None,
    *,
    context: dict | None = None,
    reference_date: date | None = None,
) -> dict:
    """Return a transparent weighted score for one already-TV-safe candidate."""
    audit = entry.get("_audit") or {}
    if not isinstance(audit, dict):
        audit = {}

    weights = _weights(cfg)
    quality = _quality_config(cfg)
    context = context or {}
    today = reference_date or context.get("reference_date") or datetime.now(timezone.utc).date()

    try:
        stale_days = max(
            int(
                quality.get("manual_stale_days")
                or ((cfg or {}).get("attention") or {}).get("manual_stale_days")
                or 30
            ),
            1,
        )
    except (TypeError, ValueError):
        stale_days = 30

    components: list[dict] = []

    def add(key: str, label: str) -> None:
        points = int(weights.get(key, 0))
        if points:
            components.append({"key": key, "points": points, "label": label})

    samsung = _normalized_status(audit.get("samsung"))
    vlc = _normalized_status(audit.get("vlc"))
    if samsung == "works":
        add("samsung_works", "Samsung works")
    if vlc == "works":
        add("vlc_works", "VLC works")
    elif vlc == "works_with_warning":
        add("vlc_works_with_warning", "VLC works with warning")

    url = str(entry.get("url") or audit.get("stream_url") or "").strip()
    parsed = urlparse(url)
    if parsed.scheme.casefold() == "https":
        add("https", "HTTPS")

    flags = _parse_quality_flags(entry, audit)
    haystack = _text_haystack(entry, audit)

    official_terms = _term_list(cfg, "official_source_terms", DEFAULT_OFFICIAL_SOURCE_TERMS)
    official = (
        "official_broadcaster" in flags
        or any(term in haystack for term in official_terms)
    )
    if official:
        add("official_broadcaster", "Official broadcaster source")

    cdn_terms = _term_list(cfg, "broadcaster_cdn_terms", DEFAULT_BROADCASTER_CDN_TERMS)
    broadcaster_cdn = (
        "broadcaster_cdn" in flags
        or any(term in haystack for term in cdn_terms)
    )
    if broadcaster_cdn:
        add("broadcaster_cdn", "Broadcaster CDN")

    relay_terms = _term_list(cfg, "provider_relay_terms", DEFAULT_PROVIDER_RELAY_TERMS)
    provider_relay = (
        "provider_relay" in flags
        or any(term in haystack for term in relay_terms)
    )
    if provider_relay:
        add("provider_relay", "Provider relay")

    if HIGH_DEFINITION_RE.search(haystack):
        add("high_definition", "1080p-or-better source")

    tested_on = _parse_test_date(audit.get("tested_on"))
    if tested_on is not None:
        age_days = max((today - tested_on).days, 0)
        if age_days < stale_days:
            add("recent_manual_test", f"Manual test is recent ({age_days} d)")
        else:
            add("stale_manual_test", f"Manual test is stale ({age_days} d)")

    health = (context.get("health_by_url") or {}).get(canonical_stream_url(url)) or {}
    if isinstance(health, dict):
        status = str(health.get("status") or "").strip()
        if bool(health.get("redirected")) or status == "Redirected":
            add("redirect", "Previous health check redirected")
        if bool(health.get("tls_certificate_warning")) or status == "TLS certificate warning":
            add("tls_certificate_warning", "Previous TLS certificate warning")
        if (
            bool(health.get("actionable_failure"))
            or bool(health.get("manual_retest_recommended"))
            or status == "Slow startup"
        ):
            add("health_warning", f"Previous health warning: {status or 'failure'}")

    source_flags = {
        str(value).strip().casefold()
        for raw_flags in (
            entry.get("source_flags") or [],
            audit.get("source_flags") or [],
        )
        for value in raw_flags
        if str(value).strip()
    }
    event_only = (
        "event_only" in flags
        or "event_based" in flags
        or "not 24/7" in source_flags
        or str(health.get("health_policy") or "").strip().casefold() == "event_based"
        or status_if_dict(health) == "Event inactive"
    )
    if event_only:
        add("event_only", "Event-only / not-24/7 stream")

    tvg_id = str(entry.get("tvg_id") or audit.get("tvg_id") or "").strip()
    mapped_ids = context.get("epg_mapped_ids") or set()
    empty_ids = context.get("epg_empty_ids") or set()
    if tvg_id and tvg_id in mapped_ids and tvg_id not in empty_ids:
        add("current_epg", "Current EPG programme data")

    score = sum(int(component["points"]) for component in components)
    summary = "; ".join(
        f"{component['points']:+d} {component['label']}"
        for component in components
    ) or "No quality bonuses or penalties"

    return {
        "score": score,
        "components": components,
        "summary": summary,
    }


def status_if_dict(value: object) -> str:
    if not isinstance(value, dict):
        return ""
    return str(value.get("status") or "").strip()
