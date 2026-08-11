#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


WARNING_RE = re.compile(
    r"WARNING:\s+audit item #(\d+) \(.+?\): "
    r"legacy channel-level audit still matches one current feed "
    r"\((.+)\)\. Add stream_url when this row is next edited\."
)


def parse_matches(path: Path) -> dict[int, str]:
    matches: dict[int, str] = {}
    for line in path.read_text(
        encoding="utf-8",
        errors="replace",
    ).splitlines():
        match = WARNING_RE.search(line)
        if not match:
            continue
        index = int(match.group(1))
        url = match.group(2).strip()
        if url:
            matches[index] = url
    return matches


def migrate(
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

    matches = parse_matches(build_log_path)
    changed = 0

    for index, url in sorted(matches.items()):
        if index < 1 or index > len(items):
            raise RuntimeError(
                f"Builder warning references invalid audit item #{index}."
            )

        item = items[index - 1]
        if not isinstance(item, dict):
            raise RuntimeError(
                f"Builder warning references non-object audit item #{index}."
            )

        existing = str(item.get("stream_url") or "").strip()
        if existing:
            continue

        channel = str(
            item.get("channel")
            or item.get("channel_name")
            or f"item #{index}"
        ).strip()

        print(f"MIGRATE builder-confirmed #{index}: {channel} -> {url}")
        if write:
            item["stream_url"] = url
        changed += 1

    if write and changed:
        audit_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    print(
        f"Builder-confirmed audit migration: {changed} row(s) "
        + ("written." if write else "found (dry run).")
    )
    return changed


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Migrate only legacy audit rows that build.py itself reports "
            "as matching exactly one current feed."
        )
    )
    parser.add_argument("--audit", type=Path, default=Path("audit.json"))
    parser.add_argument("--build-log", type=Path, required=True)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    migrate(
        audit_path=args.audit,
        build_log_path=args.build_log,
        write=args.write,
    )


if __name__ == "__main__":
    main()
