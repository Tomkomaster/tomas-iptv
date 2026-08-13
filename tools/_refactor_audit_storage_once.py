#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def replace_exact(path: str, old: str, new: str, expected: int = 1) -> None:
    p = ROOT / path
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != expected:
        raise SystemExit(
            f"{path}: expected {expected} occurrence(s) of marker, found {count}\nMARKER:\n{old}"
        )
    p.write_text(text.replace(old, new), encoding="utf-8")


AUDIT_STORAGE = '''#!/usr/bin/env python3
"""Compact, human-maintained storage contract for ``audit.json``.

``audit.json`` is the Git-tracked authority for manual playback facts and
deliberate routing/exclusion decisions. Automated probe/health/EPG telemetry
belongs in generated Pages JSON such as ``health.json``,
``same-build-health.json`` and ``epg-health.json``.

The build enriches manual rows with derived context at runtime. The complete
operational view is published under ``report.json -> audit.channels`` and
``audit.csv`` instead of being written back into the manual source file.
"""
from __future__ import annotations

from country_language import normalize_country_code, normalize_language_codes
from iptv.playback_status import normalize_test_status


MANUAL_AUDIT_SCHEMA_VERSION = 2
MANUAL_AUDIT_STORAGE_KIND = "manual_only"

MACHINE_TELEMETRY_FIELDS = frozenset({
    "success",
    "checked_at",
    "generated_at",
    "startup_seconds",
    "request_count",
    "redirected",
    "final_url",
    "consecutive_failures",
    "last_success_at",
    "last_failure_at",
    "stream_state",
    "actionable_failure",
    "tls_certificate_warning",
    "tls_certificate_detail",
})
MACHINE_TELEMETRY_PREFIXES = (
    "probe_",
    "health_",
    "epg_",
    "http_",
    "automatic_",
)

# Runtime/build context reconstructed by prepare_audit_rows().
GENERATED_CONTEXT_FIELDS = frozenset({
    "source",
    "protocol",
    "language_codes",
    "playlist_language_code",
    "output_language_code",
    "country_code",
    "language_acceptance",
    "in_playlist",
    "in_stable_playlist",
    "feed_index",
    "feed_count",
    "feed_label",
})

MANUAL_FIELD_ORDER = (
    "channel",
    "stream_url",
    "tvg_id",
    "playlist_country_code",
    "output_country_code",
    "expected_language_codes",
    "observed_language_codes",
    "language_match",
    "vlc",
    "samsung",
    "vlc_note",
    "samsung_note",
    "decision",
    "exclude_from_playlist",
    "tested_on",
    "reason",
    "notes",
    "provenance",
    "discovery",
    "source_flags",
    # Retained only for a legacy row whose language text cannot yet be
    # normalized into observed_language_codes.
    "language",
    "language_code",
)

_UNKNOWN_LANGUAGE_TEXT = {
    "",
    "unknown",
    "untested",
    "not tested",
    "not_tested",
    "pending",
}


def machine_telemetry_fields(item: dict) -> list[str]:
    """Return fields that belong in generated telemetry, not audit.json."""
    found: list[str] = []
    for raw_key in item:
        key = str(raw_key or "").strip()
        token = key.casefold()
        if (
            token in MACHINE_TELEMETRY_FIELDS
            or token.startswith(MACHINE_TELEMETRY_PREFIXES)
            or token.endswith("_latency_ms")
            or token.endswith("_latency_seconds")
        ):
            found.append(key)
    return sorted(found)


def compact_manual_audit_item(item: dict) -> dict:
    """Remove generated/default duplication while preserving manual facts."""
    out = dict(item)

    telemetry = machine_telemetry_fields(out)
    if telemetry:
        raise ValueError(
            "Machine telemetry does not belong in audit.json: "
            + ", ".join(telemetry)
        )

    # Migrate old country aliases before dropping generated compatibility aliases.
    if not out.get("playlist_country_code"):
        legacy_scope = normalize_country_code(
            str(out.get("playlist_language_code") or out.get("country_code") or "")
        )
        if legacy_scope:
            out["playlist_country_code"] = legacy_scope

    if not out.get("output_country_code"):
        legacy_output = normalize_country_code(
            str(out.get("output_language_code") or "")
        )
        if legacy_output:
            out["output_country_code"] = legacy_output

    for field in GENERATED_CONTEXT_FIELDS:
        out.pop(field, None)

    for field in ("playlist_country_code", "output_country_code"):
        if field in out:
            code = normalize_country_code(str(out.get(field) or ""))
            if code:
                out[field] = code
            else:
                out.pop(field, None)

    for field in ("expected_language_codes", "observed_language_codes"):
        codes = normalize_language_codes(out.get(field))
        if codes:
            out[field] = codes
        else:
            out.pop(field, None)

    # Convert legacy human language text to the modern explicit human fact.
    observed = list(out.get("observed_language_codes") or [])
    legacy_language = str(out.get("language") or "").strip()
    legacy_token = " ".join(
        legacy_language.casefold().replace("_", " ").split()
    )
    if not observed and legacy_token not in _UNKNOWN_LANGUAGE_TEXT:
        observed = normalize_language_codes([legacy_language])
        if not observed:
            observed = normalize_language_codes([
                str(out.get("language_code") or "")
            ])
        if observed:
            out["observed_language_codes"] = observed

    if observed or legacy_token in _UNKNOWN_LANGUAGE_TEXT:
        out.pop("language", None)
        out.pop("language_code", None)

    # Missing values are the compact representation of these defaults.
    decision = str(out.get("decision") or "auto").strip()
    if decision.casefold().replace(" ", "_") == "auto":
        out.pop("decision", None)

    if out.get("exclude_from_playlist") is False:
        out.pop("exclude_from_playlist", None)

    for field in ("vlc", "samsung"):
        status = normalize_test_status(str(out.get(field) or ""))
        if status == "not_tested":
            out.pop(field, None)
        else:
            out[field] = status

    for field in (
        "stream_url",
        "tvg_id",
        "vlc_note",
        "samsung_note",
        "reason",
        "tested_on",
        "notes",
        "provenance",
        "discovery",
    ):
        if field in out and not str(out.get(field) or "").strip():
            out.pop(field, None)

    if not out.get("source_flags"):
        out.pop("source_flags", None)

    compact: dict = {}
    for field in MANUAL_FIELD_ORDER:
        if field in out:
            compact[field] = out[field]
    # Preserve unknown future manual fields rather than silently deleting them.
    for field, value in out.items():
        if field not in compact:
            compact[field] = value
    return compact


def compact_manual_audit_payload(payload) -> dict:
    """Return schema-v2 manual-only payload from list or legacy object form."""
    if isinstance(payload, dict):
        items = payload.get("channels")
        extras = {
            key: value
            for key, value in payload.items()
            if key not in {"schema_version", "storage", "channels"}
        }
    else:
        items = payload
        extras = {}

    if not isinstance(items, list):
        raise RuntimeError("audit.json must contain a channels list.")

    channels = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise RuntimeError(f"audit item #{index} must be a JSON object.")
        channels.append(compact_manual_audit_item(item))

    return {
        "schema_version": MANUAL_AUDIT_SCHEMA_VERSION,
        "storage": MANUAL_AUDIT_STORAGE_KIND,
        **extras,
        "channels": channels,
    }
'''

COMPACT_TOOL = '''#!/usr/bin/env python3
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
    rendered = json.dumps(compacted, indent=2, ensure_ascii=False) + "\\n"
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
'''

TESTS = '''import json
import unittest
from pathlib import Path

from iptv.audit import validate_audit_items
from iptv.audit_storage import (
    GENERATED_CONTEXT_FIELDS,
    MANUAL_AUDIT_SCHEMA_VERSION,
    MANUAL_AUDIT_STORAGE_KIND,
    compact_manual_audit_item,
    machine_telemetry_fields,
)


ROOT = Path(__file__).resolve().parents[1]


class AuditStorageTests(unittest.TestCase):
    def test_compaction_keeps_manual_facts_and_drops_generated_defaults(self):
        compact = compact_manual_audit_item({
            "channel": "Example TV",
            "stream_url": "https://example.test/live.m3u8",
            "protocol": "HLS",
            "language": "Czech",
            "language_code": "CZ",
            "language_codes": ["ces"],
            "expected_language_codes": ["ces"],
            "playlist_language_code": "CZ",
            "output_language_code": "CZ",
            "vlc": "works",
            "samsung": "not_tested",
            "vlc_note": "manual VLC check",
            "samsung_note": "",
            "decision": "auto",
            "exclude_from_playlist": False,
            "tested_on": "2026-08-13",
            "notes": "Keep this manual note.",
        })

        self.assertEqual(compact["playlist_country_code"], "CZ")
        self.assertEqual(compact["output_country_code"], "CZ")
        self.assertEqual(compact["observed_language_codes"], ["ces"])
        self.assertEqual(compact["expected_language_codes"], ["ces"])
        self.assertEqual(compact["vlc"], "works")
        self.assertEqual(compact["vlc_note"], "manual VLC check")
        self.assertEqual(compact["tested_on"], "2026-08-13")
        self.assertEqual(compact["notes"], "Keep this manual note.")

        for field in (
            "protocol", "language", "language_code", "language_codes",
            "playlist_language_code", "output_language_code", "samsung",
            "samsung_note", "decision", "exclude_from_playlist",
        ):
            self.assertNotIn(field, compact)

    def test_explicit_manual_overrides_are_preserved(self):
        compact = compact_manual_audit_item({
            "channel": "Cross-language TV",
            "playlist_country_code": "SK",
            "output_country_code": "CZ",
            "expected_language_codes": ["slk"],
            "observed_language_codes": ["ces"],
            "language_match": "no",
            "decision": "rejected",
            "exclude_from_playlist": True,
            "reason": "Manual decision.",
        })
        self.assertEqual(compact["output_country_code"], "CZ")
        self.assertEqual(compact["language_match"], "no")
        self.assertEqual(compact["decision"], "rejected")
        self.assertIs(compact["exclude_from_playlist"], True)
        self.assertEqual(compact["reason"], "Manual decision.")

    def test_machine_telemetry_is_rejected(self):
        row = {"channel": "Example", "probe_status": "HTTP error", "http_status": 503}
        self.assertEqual(machine_telemetry_fields(row), ["http_status", "probe_status"])
        with self.assertRaisesRegex(ValueError, "Machine telemetry"):
            compact_manual_audit_item(row)
        with self.assertRaisesRegex(RuntimeError, "Machine telemetry fields"):
            validate_audit_items([row], [])

    def test_repository_audit_is_manual_only_schema(self):
        path = ROOT / "audit.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], MANUAL_AUDIT_SCHEMA_VERSION)
        self.assertEqual(payload["storage"], MANUAL_AUDIT_STORAGE_KIND)
        self.assertGreater(len(payload["channels"]), 0)

        failures = []
        for index, row in enumerate(payload["channels"], start=1):
            telemetry = machine_telemetry_fields(row)
            generated = sorted(set(row).intersection(GENERATED_CONTEXT_FIELDS))
            if telemetry:
                failures.append(f"row {index}: telemetry {telemetry}")
            if generated:
                failures.append(f"row {index}: generated context {generated}")
            if row.get("decision") == "auto":
                failures.append(f"row {index}: explicit default decision")
            if row.get("exclude_from_playlist") is False:
                failures.append(f"row {index}: explicit default exclusion")

        self.assertEqual(failures, [], "\\n".join(failures))


if __name__ == "__main__":
    unittest.main()
'''

DOC = '''# Audit data ownership

`audit.json` is the Git-tracked **manual authority**. It should contain facts a
person deliberately established or wants to preserve: stream identity, VLC and
Samsung playback results, observed spoken language, manual notes/reasons,
exclusions, explicit routing overrides, source flags, and test dates.

It is intentionally **not** a telemetry database. Automated observations belong
in generated Pages output:

- `public/health.json` — scheduled stream probes and bounded health history;
- `public/same-build-health.json` — same-build failover probe evidence;
- `public/epg-health.json` — EPG mapping/programme health;
- `public/report.json` → `audit.channels` and `public/audit.csv` — the full
  runtime-enriched audit view, including derived source/protocol/routing state.

The manual file uses `schema_version: 2` and `storage: "manual_only"`. Runtime
code still accepts older rows for compatibility, but new machine fields such as
`probe_*`, `health_*`, `epg_*`, `http_*`, latency, timestamps and automatic
failure state are rejected if they are added to `audit.json`.

## Keeping the manual file compact

Run:

```bash
python tools/compact_audit.py
python tools/compact_audit.py --write
```

The compactor preserves manual facts, modernizes safe legacy aliases, removes
reconstructable build context (`protocol`, generated language/source aliases,
feed membership), and omits explicit representations of defaults such as
`decision: "auto"`, `exclude_from_playlist: false`, and `not_tested` device
statuses.

`tools/migrate_audit.py --write` also applies the same compaction contract so a
legacy migration cannot re-inflate the file.
'''

(ROOT / "iptv/audit_storage.py").write_text(AUDIT_STORAGE, encoding="utf-8")
(ROOT / "tools/compact_audit.py").write_text(COMPACT_TOOL, encoding="utf-8")
(ROOT / "tests/test_audit_storage.py").write_text(TESTS, encoding="utf-8")
(ROOT / "docs/audit-data-model.md").write_text(DOC, encoding="utf-8")

# Runtime validation: reject accidental machine observations in manual audit.
replace_exact(
    "iptv/audit.py",
    "from iptv.playback_status import normalize_test_status\nfrom iptv.source_loader import SOURCE_FLAG_RE\n",
    "from iptv.playback_status import normalize_test_status\nfrom iptv.audit_storage import machine_telemetry_fields\nfrom iptv.source_loader import SOURCE_FLAG_RE\n",
)
replace_exact(
    "iptv/audit.py",
    "        if channel:\n            label += f\" ({channel})\"\n\n        if not channel:\n",
    "        if channel:\n            label += f\" ({channel})\"\n\n        telemetry_fields = machine_telemetry_fields(item)\n        if telemetry_fields:\n            errors.append(\n                f\"{label}: Machine telemetry fields do not belong in audit.json: \"\n                f\"{', '.join(telemetry_fields)}. Keep automated probe/health/EPG \"\n                \"observations in generated Pages JSON instead.\"\n            )\n\n        if not channel:\n",
)

# Migration must not re-add generated fields and always writes compact schema.
replace_exact(
    "tools/migrate_audit.py",
    "from country_language import (\n    country_code_from_tvg_id,\n    country_language_defaults,\n    normalize_country_code,\n    normalize_language_codes,\n)\n",
    "from country_language import (\n    country_code_from_tvg_id,\n    country_language_defaults,\n    normalize_country_code,\n    normalize_language_codes,\n)\nfrom iptv.audit_storage import compact_manual_audit_payload\n",
)
replace_exact(
    "tools/migrate_audit.py",
    "    language_codes = normalize_language_codes(\n        item.get(\"language_codes\")\n    )\n    if not language_codes or scope_changed_to_current:\n        language_codes = list(observed or expected)\n\n",
    "",
)
replace_exact(
    "tools/migrate_audit.py",
    "        \"language_codes\": language_codes,\n",
    "",
)
replace_exact(
    "tools/migrate_audit.py",
    "            if (\n                not str(item.get(\"protocol\") or \"\").strip()\n                and str(candidate.get(\"protocol\") or \"\").strip()\n            ):\n                item[\"protocol\"] = candidate[\"protocol\"].strip()\n\n",
    "",
)
replace_exact(
    "tools/migrate_audit.py",
    "    if write and (migrated or modernized):\n        audit_path.write_text(\n            json.dumps(\n                payload,\n                ensure_ascii=False,\n                indent=2,\n            ) + \"\\n\",\n            encoding=\"utf-8\",\n        )\n",
    "    if write:\n        payload = compact_manual_audit_payload(payload)\n        audit_path.write_text(\n            json.dumps(\n                payload,\n                ensure_ascii=False,\n                indent=2,\n            ) + \"\\n\",\n            encoding=\"utf-8\",\n        )\n",
)

# Repository-specific test now checks the modern compact representation.
replace_exact(
    "tests/test_health_audit_followup.py",
    "        self.assertEqual(item[\"language_code\"], \"CZ\")\n",
    "        self.assertNotIn(\"language_code\", item)\n",
)
replace_exact(
    "tests/test_health_audit_followup.py",
    "        self.assertFalse(item[\"exclude_from_playlist\"])\n",
    "        self.assertFalse(item.get(\"exclude_from_playlist\", False))\n",
)

# Rewrite the current file once using the same production compactor.
import importlib
importlib.invalidate_caches()
from iptv.audit_storage import compact_manual_audit_payload

audit_path = ROOT / "audit.json"
raw = audit_path.read_text(encoding="utf-8-sig")
payload = json.loads(raw)
compacted = compact_manual_audit_payload(payload)
rendered = json.dumps(compacted, indent=2, ensure_ascii=False) + "\n"
audit_path.write_text(rendered, encoding="utf-8")
print(f"audit.json compacted: {len(raw.encode('utf-8')):,} -> {len(rendered.encode('utf-8')):,} bytes")
