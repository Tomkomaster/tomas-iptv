#!/usr/bin/env python3
"""Repair canonical URL duplicates introduced by the 2026-08-15 manual audit import."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

AUDIT_PATH = Path("audit.json")
BATCH_DATE = "2026-08-15"

RESULT_FIELDS = {
    "channel",
    "vlc",
    "samsung",
    "vlc_note",
    "samsung_note",
    "tested_on",
    "reason",
    "notes",
    "expected_language_codes",
    "observed_language_codes",
    "playlist_country_code",
    "output_country_code",
    "decision",
    "exclude_from_playlist",
}


def canonical_url(url: str) -> str:
    value = (url or "").strip()
    if not value:
        return ""
    parsed = urlsplit(value)
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    port = parsed.port
    if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        port = None
    netloc = host
    if port is not None:
        netloc = f"{host}:{port}"
    if parsed.username:
        auth = parsed.username
        if parsed.password:
            auth += f":{parsed.password}"
        netloc = f"{auth}@{netloc}"
    return urlunsplit((scheme, netloc, parsed.path, parsed.query, ""))


def is_batch_row(row: dict) -> bool:
    return row.get("tested_on") == BATCH_DATE and (
        "2026-08-15" in str(row.get("discovery", ""))
        or "2026-08-15" in str(row.get("reason", ""))
        or "2026-08-15" in str(row.get("notes", ""))
    )


def merge_latest_into_existing(existing: dict, latest: dict) -> dict:
    merged = dict(existing)

    # A fresh working retest intentionally clears stale explicit rejection fields.
    for field in ("decision", "exclude_from_playlist"):
        if field not in latest:
            merged.pop(field, None)

    for field in RESULT_FIELDS:
        if field in latest:
            merged[field] = latest[field]

    # Keep the established stream spelling and stronger historical identity/provenance
    # unless the older row did not have them.
    for field in ("tvg_id", "provenance", "discovery", "source_flags"):
        if field not in merged and field in latest:
            merged[field] = latest[field]

    return merged


def main() -> None:
    data = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    rows = data.get("channels", [])
    output: list[dict] = []
    key_to_index: dict[str, int] = {}
    repaired: list[tuple[str, str, str]] = []

    for row in rows:
        key = canonical_url(str(row.get("stream_url", "")))
        if not key or key not in key_to_index:
            key_to_index[key] = len(output)
            output.append(row)
            continue

        previous_index = key_to_index[key]
        previous = output[previous_index]
        previous_batch = is_batch_row(previous)
        current_batch = is_batch_row(row)

        if not (previous_batch or current_batch):
            raise RuntimeError(
                f"Refusing to alter pre-existing canonical duplicate: {key!r} "
                f"({previous.get('channel')!r} / {row.get('channel')!r})"
            )

        if current_batch:
            output[previous_index] = merge_latest_into_existing(previous, row)
            repaired.append((key, str(previous.get("channel", "")), str(row.get("channel", ""))))
        else:
            # Extremely defensive branch: if the earlier row is the batch row, keep it.
            repaired.append((key, str(row.get("channel", "")), str(previous.get("channel", ""))))

    # Verify the resulting file has no canonical URL duplicates at all.
    seen: dict[str, int] = {}
    for index, row in enumerate(output, start=1):
        key = canonical_url(str(row.get("stream_url", "")))
        if not key:
            continue
        if key in seen:
            raise RuntimeError(
                f"Canonical duplicate remains after repair: item #{index} duplicates #{seen[key]}: {key}"
            )
        seen[key] = index

    data["channels"] = output
    AUDIT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"Canonical duplicate repair complete: {len(repaired)} duplicate row(s) merged.")
    for key, old_name, new_name in repaired:
        print(f"- {key}: kept existing identity {old_name!r}, applied latest test from {new_name!r}")


if __name__ == "__main__":
    main()
