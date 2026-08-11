#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from migrate_audit import canonical_stream_url
from migrate_builder_warnings import parse_matches


def cleanup(
    audit_path: Path,
    build_log_path: Path,
    write: bool = False,
) -> int:
    payload = json.loads(
        audit_path.read_text(encoding="utf-8-sig")
    )
    items = payload.get("channels") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise RuntimeError("audit.json must contain a channels list.")

    warning_matches = parse_matches(build_log_path)

    exact_urls: dict[str, list[int]] = {}
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        url = canonical_stream_url(
            str(item.get("stream_url") or "")
        )
        if url:
            exact_urls.setdefault(url, []).append(index)

    remove_indexes: list[int] = []

    for legacy_index, warning_url in sorted(warning_matches.items()):
        if legacy_index < 1 or legacy_index > len(items):
            continue

        item = items[legacy_index - 1]
        if not isinstance(item, dict):
            continue
        if str(item.get("stream_url") or "").strip():
            continue

        canonical = canonical_stream_url(warning_url)
        exact_indexes = exact_urls.get(canonical, [])
        if not exact_indexes:
            continue

        channel = str(
            item.get("channel")
            or item.get("channel_name")
            or f"item #{legacy_index}"
        ).strip()
        exact_text = ", ".join(f"#{i}" for i in exact_indexes)
        print(
            f"REMOVE legacy duplicate #{legacy_index}: {channel}; "
            f"same feed already has exact audit row {exact_text}."
        )
        remove_indexes.append(legacy_index)

    if write:
        for index in reversed(remove_indexes):
            del items[index - 1]

        if remove_indexes:
            audit_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

    print(
        f"Legacy duplicate cleanup: {len(remove_indexes)} row(s) "
        + ("removed." if write else "found (dry run).")
    )
    return len(remove_indexes)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Remove legacy channel-level audit rows only when build.py "
            "confirms one current feed and that exact URL already has "
            "a URL-specific audit row."
        )
    )
    parser.add_argument("--audit", type=Path, default=Path("audit.json"))
    parser.add_argument("--build-log", type=Path, required=True)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    cleanup(
        audit_path=args.audit,
        build_log_path=args.build_log,
        write=args.write,
    )


if __name__ == "__main__":
    main()
