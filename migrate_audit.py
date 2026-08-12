#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from country_language import (
    country_code_from_tvg_id,
    country_language_defaults,
    normalize_country_code,
    normalize_language_codes,
)


QUALITY_SUFFIX_RE = re.compile(
    r"\s*(?:\((?:2160p|1440p|1080p|720p|576p|540p|480p|360p|240p|4K|UHD|FHD|HD|SD)\)|"
    r"\[(?:2160p|1440p|1080p|720p|576p|540p|480p|360p|240p|4K|UHD|FHD|HD|SD)\])\s*$",
    re.IGNORECASE,
)
TVG_VARIANT_SUFFIX_RE = re.compile(
    r"@(SD|HD|FHD|UHD|4K|\d{3,4}P)$",
    re.IGNORECASE,
)


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").casefold()
    value = re.sub(r"[^\w]+", " ", value, flags=re.UNICODE)
    return " ".join(value.split())


def clean_channel_name(value: str) -> str:
    value = " ".join((value or "").split()).strip()
    old = None
    while value and value != old:
        old = value
        value = QUALITY_SUFFIX_RE.sub("", value).strip()
    return normalize_text(value)


def normalized_tvg_id(value: str) -> str:
    return TVG_VARIANT_SUFFIX_RE.sub(
        "",
        (value or "").strip(),
    ).casefold()


def canonical_stream_url(url: str) -> str:
    value = (url or "").strip()
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


def load_current_rows(path: Path) -> list[dict[str, str]]:
    with path.open(
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        return list(csv.DictReader(handle))


def candidate_rows(
    item: dict,
    rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    tvg_key = normalized_tvg_id(
        str(item.get("tvg_id") or "")
    )
    name_key = clean_channel_name(
        str(
            item.get("channel")
            or item.get("channel_name")
            or ""
        )
    )

    if tvg_key:
        matches = [
            row for row in rows
            if normalized_tvg_id(
                row.get("tvg_id", "")
            ) == tvg_key
        ]
        if matches:
            return matches

    if not name_key:
        return []

    return [
        row for row in rows
        if clean_channel_name(
            row.get("channel", "")
        ) == name_key
    ]


def choose_unique_candidate(
    item: dict,
    rows: list[dict[str, str]],
) -> dict[str, str] | None:
    matches = candidate_rows(item, rows)

    by_url: dict[str, dict[str, str]] = {}
    for row in matches:
        url = (row.get("stream_url") or "").strip()
        key = canonical_stream_url(url)
        if key:
            by_url.setdefault(key, row)

    if len(by_url) != 1:
        return None

    return next(iter(by_url.values()))


def _first_country(*values) -> str:
    for value in values:
        code = normalize_country_code(str(value or ""))
        if code:
            return code
    return ""


def modernize_audit_item(
    item: dict,
    candidate: dict[str, str] | None = None,
    cfg: dict | None = None,
) -> bool:
    """Add the modern country/language model while retaining legacy aliases.

    The migration deliberately leaves cross-language output_country_code blank
    unless an explicit legacy output exists. A blank modern output field lets
    the normal verified-country routing logic decide later and avoids pinning a
    rejected/untested row to the wrong destination.
    """
    cfg = cfg or {}
    candidate = candidate or {}

    playlist_country = _first_country(
        item.get("playlist_country_code"),
        item.get("playlist_language_code"),
        item.get("language_code"),
        candidate.get("playlist_country_code"),
        candidate.get("country_code"),
        candidate.get("language_code"),
    )
    if not playlist_country:
        playlist_country = country_code_from_tvg_id(
            str(item.get("tvg_id") or candidate.get("tvg_id") or "")
        )

    expected = normalize_language_codes(
        item.get("expected_language_codes")
    )
    if not expected and playlist_country:
        expected = country_language_defaults(cfg, playlist_country)

    observed = normalize_language_codes(
        item.get("observed_language_codes")
    )
    if not observed:
        observed = normalize_language_codes(
            item.get("language")
        )

    language_codes = normalize_language_codes(
        item.get("language_codes")
    )
    if not language_codes:
        language_codes = list(observed or expected)

    output_country = _first_country(
        item.get("output_country_code"),
        item.get("output_language_code"),
        candidate.get("output_country_code"),
    )
    if not output_country and playlist_country:
        defaults = set(
            country_language_defaults(cfg, playlist_country)
        )
        # Same-country/unknown-language rows are safe to make explicit. For a
        # true cross-language row, leave output blank so verified routing stays
        # authoritative instead of this migration silently pinning a country.
        if not observed or defaults.intersection(observed):
            output_country = playlist_country

    modern = {
        "playlist_country_code": playlist_country,
        "output_country_code": output_country,
        "language_codes": language_codes,
        "expected_language_codes": expected,
        "observed_language_codes": observed,
    }

    changed = False
    for key, value in modern.items():
        if item.get(key) != value:
            item[key] = value
            changed = True
    return changed


def migrate(
    audit_path: Path,
    current_path: Path,
    write: bool = False,
    modernize_only: bool = False,
    config_path: Path | None = None,
) -> dict[str, int]:
    payload = json.loads(
        audit_path.read_text(
            encoding="utf-8-sig"
        )
    )

    if isinstance(payload, dict):
        items = payload.get("channels")
    else:
        items = payload

    if not isinstance(items, list):
        raise RuntimeError(
            "audit.json must contain a channels list."
        )

    rows = load_current_rows(current_path)

    cfg: dict = {}
    resolved_config = config_path
    if resolved_config is None:
        sibling = audit_path.parent / "config.json"
        if sibling.is_file():
            resolved_config = sibling
    if resolved_config is not None and resolved_config.is_file():
        loaded = json.loads(resolved_config.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            cfg = loaded

    migrated = 0
    modernized = 0
    ambiguous = 0
    missing = 0
    already_exact = 0

    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue

        candidate = choose_unique_candidate(
            item,
            rows,
        )

        if modernize_audit_item(
            item,
            candidate=candidate,
            cfg=cfg,
        ):
            modernized += 1

        if modernize_only:
            continue

        if str(item.get("stream_url") or "").strip():
            already_exact += 1
            continue

        channel = str(
            item.get("channel")
            or item.get("channel_name")
            or f"item #{index}"
        ).strip()

        if candidate is None:
            matches = candidate_rows(item, rows)
            urls = {
                canonical_stream_url(
                    row.get("stream_url", "")
                )
                for row in matches
                if canonical_stream_url(
                    row.get("stream_url", "")
                )
            }

            if len(urls) > 1:
                ambiguous += 1
                print(
                    f"AMBIGUOUS: {channel}: "
                    f"{len(urls)} current feeds; left unchanged."
                )
            else:
                missing += 1
                print(
                    f"NO MATCH: {channel}: "
                    "no unique current feed; left unchanged."
                )
            continue

        url = (
            candidate.get("stream_url")
            or ""
        ).strip()

        print(
            f"MIGRATE: {channel} -> {url}"
        )

        if write:
            item["stream_url"] = url

            if (
                not str(item.get("tvg_id") or "").strip()
                and str(candidate.get("tvg_id") or "").strip()
            ):
                item["tvg_id"] = candidate["tvg_id"].strip()

            if (
                not str(item.get("protocol") or "").strip()
                and str(candidate.get("protocol") or "").strip()
            ):
                item["protocol"] = candidate["protocol"].strip()

        migrated += 1

    if write and (migrated or modernized):
        audit_path.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )

    summary = {
        "migrated": migrated,
        "modernized": modernized,
        "already_exact": already_exact,
        "ambiguous": ambiguous,
        "missing": missing,
    }

    print()
    print(
        "Audit migration summary: "
        f"{migrated} safe one-to-one, "
        f"{modernized} modernized metadata rows, "
        f"{already_exact} already exact, "
        f"{ambiguous} ambiguous, "
        f"{missing} no match."
    )

    if not write:
        print(
            "Dry run only. Re-run with --write to update audit.json."
        )

    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Safely migrate legacy audit rows to exact stream URLs and/or "
            "the modern country + ISO-639-3 spoken-language model."
        )
    )
    parser.add_argument(
        "--audit",
        type=Path,
        default=Path("audit.json"),
    )
    parser.add_argument(
        "--current",
        type=Path,
        default=Path("public/audit.csv"),
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write safe migrations back to audit.json.",
    )
    parser.add_argument(
        "--modernize-only",
        action="store_true",
        help=(
            "Only add/update modern country and ISO-639-3 language fields; "
            "do not attach missing stream URLs."
        ),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config.json"),
        help="Project config used for country-to-language defaults.",
    )
    args = parser.parse_args()

    migrate(
        args.audit,
        args.current,
        write=args.write,
        modernize_only=args.modernize_only,
        config_path=args.config,
    )


if __name__ == "__main__":
    main()
