#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

from tools.research_exports import (
    derive_channel_status,
    group_channels,
    is_current,
    is_stable,
    load_audit_rows,
    match_wanted_channels,
)


COUNTRIES = ("hu", "sk", "cz", "ro")


def main() -> None:
    audit_rows = load_audit_rows(Path("audit.csv"))
    grouped = group_channels(audit_rows)

    total_removed = 0
    for country in COUNTRIES:
        path = Path(f"data/wanted_channels_{country}.json")
        data = json.loads(path.read_text(encoding="utf-8"))
        channels = list(data.get("channels") or [])

        matched, _unmatched = match_wanted_channels(grouped, channels)
        resolved_ids: set[int] = set()
        resolved_details: list[str] = []

        for group_key, wanted in matched.items():
            rows = grouped[group_key]
            if derive_channel_status(rows) != "WORKING":
                continue

            stable_rows = [row for row in rows if is_current(row) and is_stable(row)]
            if not stable_rows:
                continue

            resolved_ids.add(id(wanted))
            best = stable_rows[0]
            resolved_details.append(
                f"{wanted.get('channel', 'Unnamed')}"
                f" | tvg-id={wanted.get('tvg_id', '') or best.get('tvg_id', '')}"
                f" | tested={best.get('tested_on', '')}"
                f" | source={best.get('source', '')}"
            )

        if not resolved_ids:
            print(f"{country.upper()}: no resolved wanted targets to remove.")
            continue

        data["channels"] = [item for item in channels if id(item) not in resolved_ids]
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        print(
            f"{country.upper()}: removed {len(resolved_ids)} resolved target(s); "
            f"{len(data['channels'])} remain."
        )
        for detail in resolved_details:
            print(f"  - {detail}")
        total_removed += len(resolved_ids)

    print(f"Total resolved wanted targets removed: {total_removed}")


if __name__ == "__main__":
    main()
