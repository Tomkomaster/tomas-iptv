#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlparse, urlunparse


SCHEMA_VERSION = 1


def canonical_stream_url(url: str) -> str:
    """Normalize a URL only for identity-selector comparison."""
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


def normalize_source(value: str) -> str:
    return " ".join(str(value or "").split()).strip().casefold()


def normalize_name(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = re.sub(r"[^\w]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def normalize_tvg_id(value: str) -> str:
    return str(value or "").strip().casefold()


class IdentityRegistry:
    """Resolve feed/source evidence to one canonical channel identity."""

    _MATCH_SHAPES = {
        frozenset({"url"}): (400, "exact_url"),
        frozenset({"source", "tvg_id"}): (300, "source_tvg_id"),
        frozenset({"source", "normalized_name"}): (200, "source_normalized_name"),
    }

    _IDENTITY_FIELDS = {
        "channel_name",
        "tvg_name",
        "tvg_id",
        "language_code",  # legacy country alias
        "country_code",
        "language_codes",
    }

    def __init__(self, data: dict):
        if not isinstance(data, dict):
            raise RuntimeError("identity_overrides.json must contain a JSON object.")

        schema_version = data.get("schema_version", SCHEMA_VERSION)
        if schema_version != SCHEMA_VERSION:
            raise RuntimeError(
                f"Unsupported identity_overrides schema_version: {schema_version!r}"
            )

        raw_identities = data.get("identities") or {}
        raw_selectors = data.get("selectors") or []

        if not isinstance(raw_identities, dict):
            raise RuntimeError("identity_overrides identities must be an object.")
        if not isinstance(raw_selectors, list):
            raise RuntimeError("identity_overrides selectors must be a list.")

        self.identities: dict[str, dict] = {}
        for raw_id, raw_identity in raw_identities.items():
            canonical_id = str(raw_id or "").strip()
            if not canonical_id:
                raise RuntimeError("Canonical identity IDs must not be empty.")
            if not isinstance(raw_identity, dict):
                raise RuntimeError(
                    f"Canonical identity {canonical_id!r} must be an object."
                )

            unknown = set(raw_identity) - self._IDENTITY_FIELDS
            if unknown:
                raise RuntimeError(
                    f"Canonical identity {canonical_id!r} has unsupported fields: "
                    + ", ".join(sorted(unknown))
                )

            identity: dict = {}
            for key in self._IDENTITY_FIELDS:
                if key not in raw_identity:
                    continue
                if key == "language_codes":
                    raw_codes = raw_identity.get(key)
                    if not isinstance(raw_codes, list):
                        raise RuntimeError(
                            f"Canonical identity {canonical_id!r} language_codes "
                            "must be a JSON list."
                        )
                    codes = [
                        str(value or "").strip()
                        for value in raw_codes
                        if str(value or "").strip()
                    ]
                    if not codes:
                        raise RuntimeError(
                            f"Canonical identity {canonical_id!r} language_codes "
                            "must not be empty when supplied."
                        )
                    identity[key] = codes
                else:
                    identity[key] = str(raw_identity.get(key) or "").strip()

            if not identity.get("channel_name"):
                raise RuntimeError(
                    f"Canonical identity {canonical_id!r} requires channel_name."
                )

            self.identities[canonical_id] = identity

        self.selectors: list[dict] = []
        seen_selector_keys: dict[tuple, str] = {}

        for index, raw_selector in enumerate(raw_selectors):
            if not isinstance(raw_selector, dict):
                raise RuntimeError(f"Identity selector #{index + 1} must be an object.")

            canonical_id = str(raw_selector.get("canonical_id") or "").strip()
            if canonical_id not in self.identities:
                raise RuntimeError(
                    f"Identity selector #{index + 1} references unknown canonical_id "
                    f"{canonical_id!r}."
                )

            match = raw_selector.get("match")
            if not isinstance(match, dict):
                raise RuntimeError(
                    f"Identity selector #{index + 1} requires a match object."
                )

            shape = frozenset(match)
            shape_info = self._MATCH_SHAPES.get(shape)
            if not shape_info:
                allowed = "url; source+tvg_id; source+normalized_name"
                raise RuntimeError(
                    f"Identity selector #{index + 1} has unsupported match fields. "
                    f"Allowed selector shapes: {allowed}."
                )

            priority, match_type = shape_info
            normalized_match = self._normalize_match(match_type, match)
            if not all(normalized_match.values()):
                raise RuntimeError(
                    f"Identity selector #{index + 1} contains an empty match value."
                )

            selector_key = (
                match_type,
                tuple(sorted(normalized_match.items())),
            )
            previous_id = seen_selector_keys.get(selector_key)
            if previous_id is not None:
                raise RuntimeError(
                    f"Duplicate identity selector #{index + 1} for {match_type}; "
                    f"already points to {previous_id!r}."
                )
            seen_selector_keys[selector_key] = canonical_id

            self.selectors.append({
                "canonical_id": canonical_id,
                "match": normalized_match,
                "priority": priority,
                "match_type": match_type,
                "selector_index": index + 1,
                "note": str(raw_selector.get("note") or "").strip(),
            })

    @staticmethod
    def _normalize_match(match_type: str, match: dict) -> dict[str, str]:
        if match_type == "exact_url":
            return {"url": canonical_stream_url(match.get("url"))}
        if match_type == "source_tvg_id":
            return {
                "source": normalize_source(match.get("source")),
                "tvg_id": normalize_tvg_id(match.get("tvg_id")),
            }
        if match_type == "source_normalized_name":
            return {
                "source": normalize_source(match.get("source")),
                "normalized_name": normalize_name(match.get("normalized_name")),
            }
        raise AssertionError(match_type)

    def _identity_result(
        self,
        canonical_id: str,
        match_type: str,
        priority: int,
        selector_index: int | None = None,
        note: str = "",
    ) -> dict:
        return {
            "canonical_id": canonical_id,
            "identity": dict(self.identities[canonical_id]),
            "match_type": match_type,
            "priority": priority,
            "selector_index": selector_index,
            "note": note,
        }

    def resolve(
        self,
        entry: dict,
        *,
        source: str = "",
        normalized_name: str = "",
    ) -> dict | None:
        source_key = normalize_source(source or entry.get("source"))
        evidence = {
            "url": canonical_stream_url(entry.get("url")),
            "source": source_key,
            "tvg_id": normalize_tvg_id(entry.get("tvg_id")),
            "normalized_name": normalize_name(normalized_name),
        }

        matches: list[dict] = []
        for selector in self.selectors:
            if all(
                evidence.get(key, "") == value
                for key, value in selector["match"].items()
            ):
                matches.append(selector)

        if matches:
            highest = max(selector["priority"] for selector in matches)
            winners = [selector for selector in matches if selector["priority"] == highest]
            winner_ids = {selector["canonical_id"] for selector in winners}
            if len(winner_ids) != 1:
                raise RuntimeError(
                    "Ambiguous canonical identity: equally strong selectors match "
                    f"different identities for {entry.get('url') or normalized_name!r}."
                )
            winner = winners[0]
            return self._identity_result(
                winner["canonical_id"],
                winner["match_type"],
                winner["priority"],
                selector_index=winner["selector_index"],
                note=winner["note"],
            )

        manual_id = str(entry.get("canonical_id") or "").strip()
        if manual_id:
            if manual_id not in self.identities:
                raise RuntimeError(
                    f"Stream references unknown canonical-id {manual_id!r}."
                )
            return self._identity_result(
                manual_id,
                "canonical_id",
                100,
            )

        return None


def load_identity_registry(path: Path) -> IdentityRegistry:
    if not path.is_file():
        raise RuntimeError(f"Canonical identity file not found: {path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON in canonical identity file {path}: {exc}") from exc

    return IdentityRegistry(data)
