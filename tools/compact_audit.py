#!/usr/bin/env python3
"""Compact the Git-tracked manual audit without touching generated telemetry."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from iptv.audit_storage import compact_manual_audit_payload


def compact(path: Path, *, write: bool = False) -> tuple[int, int]:
    raw = path.read_text(encoding="utf-8-sig")
    payload = json.loads(raw)
    compacted = compact_manual_audit_payload(payload)
    rendered = json.dumps(compacted, indent=2, ensure_ascii=False) + "\n"
    before = len(raw.encode("utf-8"))
    after = len(rendered.encode("utf-8"))

    print(f"Manual audit rows: {len(compacted['channels']):,}")
    print(f"audit.json: {before:,} -> {after:,} bytes ({before - after:,} bytes removed)")
    if write:
        path.write_text(rendered, encoding="utf-8")
    else:
        print("Dry run only. Re-run with --write to save the compact representation.")
    return before, after


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Remove generated/default duplication from manual audit.json."
    )
    parser.add_argument("--audit", type=Path, default=ROOT / "audit.json")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    compact(args.audit, write=args.write)


if __name__ == "__main__":
    main()
