#!/usr/bin/env python3
import json
from pathlib import Path

from iptv.playback_status import normalize_test_status

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "audit.json"
AUDIT_PY = ROOT / "iptv" / "audit.py"
TESTS = ROOT / "tests" / "test_audit_storage.py"
REPORT = ROOT / "audit_exclusion_reconciliation_report.json"

payload = json.loads(AUDIT.read_text(encoding="utf-8"))
rows = payload["channels"]

added = []
for index, row in enumerate(rows, start=1):
    if "exclude_from_playlist" in row:
        continue
    samsung = normalize_test_status(str(row.get("samsung") or ""))
    if samsung in {"format_error", "generic_error", "loads"}:
        row["exclude_from_playlist"] = True
        added.append({
            "index": index,
            "channel": row.get("channel"),
            "stream_url": row.get("stream_url"),
            "decision": row.get("decision"),
            "samsung": row.get("samsung"),
        })

AUDIT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

unresolved = []
for index, row in enumerate(rows, start=1):
    if "exclude_from_playlist" not in row:
        unresolved.append({
            "index": index,
            "channel": row.get("channel"),
            "stream_url": row.get("stream_url"),
            "decision": row.get("decision"),
            "vlc": row.get("vlc"),
            "samsung": row.get("samsung"),
        })

expected_unresolved = {
    "Neshama TV",
    "TV Severka",
    "TV Vega",
    "TV Poprad",
    "TV Lux",
    "TV NRSR",
    "TV NRSR Feed 3",
}
actual_unresolved = {str(row.get("channel") or "") for row in unresolved}
if len(added) != 25:
    raise SystemExit(f"Expected to add 25 true exclusions, added {len(added)}")
if actual_unresolved != expected_unresolved:
    raise SystemExit(
        "Unexpected unresolved rows: "
        f"expected={sorted(expected_unresolved)!r}, actual={sorted(actual_unresolved)!r}"
    )

explicit_true = sum(row.get("exclude_from_playlist") is True for row in rows)
explicit_false = sum(row.get("exclude_from_playlist") is False for row in rows)
if (explicit_true, explicit_false, len(unresolved)) != (405, 516, 7):
    raise SystemExit(
        "Unexpected final counts: "
        f"true={explicit_true}, false={explicit_false}, unresolved={len(unresolved)}"
    )

text = AUDIT_PY.read_text(encoding="utf-8")
old = '        if exclude and decision_token in {"verified", "tv_verified", "pc_only"}:\n'
new = (
    "        # PC-only describes playback capability. It may also be explicitly\n"
    "        # excluded from the Samsung-safe shared playlist.\n"
    '        if exclude and decision_token in {"verified", "tv_verified"}:\n'
)
if old in text:
    text = text.replace(old, new, 1)
elif 'if exclude and decision_token in {"verified", "tv_verified"}:' not in text:
    raise SystemExit("Expected audit.py exclusion conflict guard not found")
AUDIT_PY.write_text(text, encoding="utf-8")

tests = TESTS.read_text(encoding="utf-8")
if "from iptv.playback_status import normalize_test_status\n" not in tests:
    anchor = "from iptv.audit_storage import (\n"
    if anchor not in tests:
        raise SystemExit("Expected test import anchor not found")
    tests = tests.replace(
        anchor,
        "from iptv.playback_status import normalize_test_status\n" + anchor,
        1,
    )

if "def test_pc_only_may_be_explicitly_excluded" not in tests:
    anchor = "    def test_machine_telemetry_is_rejected(self):\n"
    if anchor not in tests:
        raise SystemExit("Expected test method anchor not found")
    methods = '''    def test_pc_only_may_be_explicitly_excluded(self):
        warnings, ambiguities = validate_audit_items([{
            "channel": "PC-only example",
            "stream_url": "https://example.test/pc-only.m3u8",
            "vlc": "works",
            "samsung": "format_error",
            "decision": "pc_only",
            "exclude_from_playlist": True,
        }], [])
        self.assertEqual(warnings, [])
        self.assertEqual(ambiguities, [])

    def test_repository_decisive_rows_have_explicit_exclusion(self):
        payload = json.loads((ROOT / "audit.json").read_text(encoding="utf-8"))
        failures = []
        decisive_decisions = {"verified", "tv_verified", "rejected", "pc_only"}
        decisive_samsung = {"works", "format_error", "generic_error", "loads"}

        for index, row in enumerate(payload["channels"], start=1):
            if "exclude_from_playlist" in row:
                continue
            decision = str(row.get("decision") or "").strip().casefold().replace(" ", "_")
            samsung = normalize_test_status(str(row.get("samsung") or ""))
            if decision in decisive_decisions or samsung in decisive_samsung:
                failures.append(
                    f"row {index} ({row.get('channel')}): decision={decision or 'auto'}, "
                    f"samsung={samsung}"
                )

        self.assertEqual(failures, [], "\\n".join(failures))

'''
    tests = tests.replace(anchor, methods + anchor, 1)
TESTS.write_text(tests, encoding="utf-8")

REPORT.write_text(
    json.dumps(
        {
            "total_rows": len(rows),
            "explicit_true": explicit_true,
            "explicit_false": explicit_false,
            "added_true_second_pass": len(added),
            "unresolved_count": len(unresolved),
            "added_true_rows": added,
            "unresolved": unresolved,
        },
        ensure_ascii=False,
        indent=2,
    ) + "\n",
    encoding="utf-8",
)

print(
    f"Audit exclusions finalized: {explicit_true} true, {explicit_false} false, "
    f"{len(unresolved)} unresolved."
)
