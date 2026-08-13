#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_exact(path: str, old: str, new: str, expected: int = 1) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != expected:
        raise SystemExit(
            f"{path}: expected {expected} occurrence(s), found {count}\nMARKER:\n{old}"
        )
    target.write_text(text.replace(old, new), encoding="utf-8")


LOGO_QUALITY = r'''#!/usr/bin/env python3
"""Canonical channel-logo mappings and stable logical-channel coverage reports.

No image discovery or scraping happens here. Human-reviewed overrides are stored
in ``data/logo_overrides.json``; existing upstream ``tvg-logo`` values remain a
compatibility fallback until a canonical mapping is reviewed.
"""
from __future__ import annotations

import csv
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

from country_language import normalize_country_code
from iptv.channel_identity import logical_channel_key


SCHEMA_VERSION = 1
QUALITY_CANONICAL = "Canonical"
QUALITY_SOURCE = "Source fallback"
QUALITY_MISSING = "Missing"
QUALITY_CATEGORIES = (QUALITY_CANONICAL, QUALITY_SOURCE, QUALITY_MISSING)


def _normalize_name(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = re.sub(r"[^\w]+", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


def _country(entry: dict) -> str:
    return (
        normalize_country_code(
            str(entry.get("country_code") or entry.get("language_code") or "")
        )
        or "UNKNOWN"
    )


def _channel_name(entry: dict) -> str:
    return str(
        entry.get("channel_name")
        or entry.get("tvg_name")
        or entry.get("display_name")
        or "Unnamed channel"
    ).strip()


def _normalize_match(match_type: str, match: dict) -> dict[str, str]:
    if match_type == "canonical_id":
        return {"canonical_id": str(match.get("canonical_id") or "").strip().casefold()}
    if match_type == "country_tvg_id":
        return {
            "country_code": str(match.get("country_code") or "").strip().upper(),
            "tvg_id": str(match.get("tvg_id") or "").strip().casefold(),
        }
    if match_type == "country_channel":
        return {
            "country_code": str(match.get("country_code") or "").strip().upper(),
            "channel": _normalize_name(match.get("channel")),
        }
    raise AssertionError(match_type)


class LogoRegistry:
    """Resolve one reviewed logo override for a logical channel."""

    _MATCH_SHAPES = {
        frozenset({"canonical_id"}): (300, "canonical_id"),
        frozenset({"country_code", "tvg_id"}): (200, "country_tvg_id"),
        frozenset({"country_code", "channel"}): (100, "country_channel"),
    }

    def __init__(self, payload: dict | None = None):
        payload = payload or {"schema_version": SCHEMA_VERSION, "entries": []}
        if not isinstance(payload, dict):
            raise RuntimeError("logo_overrides.json must contain a JSON object.")
        if payload.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
            raise RuntimeError(
                f"Unsupported logo_overrides schema_version: {payload.get('schema_version')!r}"
            )
        raw_entries = payload.get("entries") or []
        if not isinstance(raw_entries, list):
            raise RuntimeError("logo_overrides entries must be a list.")

        self.entries: list[dict] = []
        seen: set[tuple] = set()
        for index, raw in enumerate(raw_entries, start=1):
            if not isinstance(raw, dict):
                raise RuntimeError(f"Logo override #{index} must be an object.")
            unknown = set(raw) - {"match", "logo", "source", "note"}
            if unknown:
                raise RuntimeError(
                    f"Logo override #{index} has unsupported fields: "
                    + ", ".join(sorted(unknown))
                )
            match = raw.get("match")
            if not isinstance(match, dict):
                raise RuntimeError(f"Logo override #{index} requires a match object.")
            shape_info = self._MATCH_SHAPES.get(frozenset(match))
            if not shape_info:
                raise RuntimeError(
                    f"Logo override #{index} has unsupported match fields. Allowed: "
                    "canonical_id; country_code+tvg_id; country_code+channel."
                )
            priority, match_type = shape_info
            normalized = _normalize_match(match_type, match)
            if not all(normalized.values()):
                raise RuntimeError(f"Logo override #{index} has an empty selector value.")

            logo = str(raw.get("logo") or "").strip()
            parsed = urlparse(logo)
            if parsed.scheme.casefold() != "https" or not parsed.netloc:
                raise RuntimeError(
                    f"Logo override #{index} must use an absolute HTTPS logo URL."
                )
            source = str(raw.get("source") or "").strip()
            if not source:
                raise RuntimeError(
                    f"Logo override #{index} requires source provenance; do not add unreviewed scraped logos."
                )

            selector_key = (match_type, tuple(sorted(normalized.items())))
            if selector_key in seen:
                raise RuntimeError(f"Duplicate logo override selector at entry #{index}.")
            seen.add(selector_key)
            self.entries.append({
                "match": normalized,
                "match_type": match_type,
                "priority": priority,
                "logo": logo,
                "source": source,
                "note": str(raw.get("note") or "").strip(),
                "index": index,
            })

    def resolve(self, entry: dict) -> dict | None:
        evidence = {
            "canonical_id": str(entry.get("canonical_id") or "").strip().casefold(),
            "country_code": _country(entry),
            "tvg_id": str(entry.get("tvg_id") or "").strip().casefold(),
            "channel": _normalize_name(_channel_name(entry)),
        }
        matches = [
            item for item in self.entries
            if all(evidence.get(key, "") == value for key, value in item["match"].items())
        ]
        if not matches:
            return None
        highest = max(item["priority"] for item in matches)
        winners = [item for item in matches if item["priority"] == highest]
        logos = {item["logo"] for item in winners}
        if len(logos) != 1:
            raise RuntimeError(
                f"Ambiguous logo overrides for {_channel_name(entry)!r}: equally strong mappings disagree."
            )
        return dict(winners[0])


def load_logo_registry(path: Path) -> LogoRegistry:
    if not path.is_file():
        raise RuntimeError(f"Configured logo override file not found: {path}")
    return LogoRegistry(json.loads(path.read_text(encoding="utf-8")))


def apply_channel_logos(entries: list[dict], registry: LogoRegistry) -> list[dict]:
    """Give every feed of one logical channel one consistent logo decision."""
    copied: list[dict] = []
    groups: dict[str, list[dict]] = defaultdict(list)
    for raw in entries:
        entry = dict(raw)
        entry["lines"] = list(raw.get("lines") or [])
        copied.append(entry)
        groups[logical_channel_key(entry)].append(entry)

    for key, group in groups.items():
        overrides = [registry.resolve(entry) for entry in group]
        overrides = [item for item in overrides if item is not None]
        if overrides:
            urls = {item["logo"] for item in overrides}
            if len(urls) != 1:
                raise RuntimeError(
                    f"Logical channel {key!r} resolves to conflicting canonical logo URLs."
                )
            chosen = max(overrides, key=lambda item: int(item["priority"]))
            for entry in group:
                entry["logo"] = chosen["logo"]
                entry["logo_quality"] = QUALITY_CANONICAL
                entry["logo_match_type"] = chosen["match_type"]
                entry["logo_provenance"] = chosen["source"]
                entry["logo_note"] = chosen["note"]
            continue

        source_candidates = sorted(
            (
                entry for entry in group
                if str(entry.get("logo") or "").strip()
            ),
            key=lambda entry: int(entry.get("_source_order") or 0),
        )
        if source_candidates:
            chosen_entry = source_candidates[0]
            chosen_logo = str(chosen_entry.get("logo") or "").strip()
            provenance = str(chosen_entry.get("source") or "upstream source").strip()
            for entry in group:
                entry["logo"] = chosen_logo
                entry["logo_quality"] = QUALITY_SOURCE
                entry["logo_match_type"] = "source_tvg_logo"
                entry["logo_provenance"] = provenance
                entry["logo_note"] = ""
        else:
            for entry in group:
                entry["logo"] = ""
                entry["logo_quality"] = QUALITY_MISSING
                entry["logo_match_type"] = ""
                entry["logo_provenance"] = ""
                entry["logo_note"] = ""
    return copied


def _summary(rows: list[dict]) -> dict:
    canonical = sum(1 for row in rows if row.get("quality_category") == QUALITY_CANONICAL)
    source = sum(1 for row in rows if row.get("quality_category") == QUALITY_SOURCE)
    missing = sum(1 for row in rows if row.get("quality_category") == QUALITY_MISSING)
    total = len(rows)
    available = canonical + source
    return {
        "stable_logical_channels": total,
        "with_logo": available,
        "canonical_logo": canonical,
        "source_fallback": source,
        "missing_logo": missing,
        "logo_availability_percent": round(100.0 * available / total if total else 0.0, 1),
        "canonical_logo_coverage_percent": round(100.0 * canonical / total if total else 0.0, 1),
    }


def build_logo_quality(
    published_entries: list[dict],
    *,
    generated_at: str = "",
    registry_path: str = "",
) -> dict:
    """Measure logo quality once per stable logical channel, not per feed URL."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for entry in published_entries:
        groups[logical_channel_key(entry)].append(entry)

    rows: list[dict] = []
    for key, group in groups.items():
        representative = group[0]
        qualities = {str(entry.get("logo_quality") or QUALITY_MISSING) for entry in group}
        if QUALITY_CANONICAL in qualities:
            quality = QUALITY_CANONICAL
        elif QUALITY_SOURCE in qualities:
            quality = QUALITY_SOURCE
        else:
            quality = QUALITY_MISSING
        logo = next((str(entry.get("logo") or "").strip() for entry in group if str(entry.get("logo") or "").strip()), "")
        rows.append({
            "key": key,
            "country_code": _country(representative),
            "channel": _channel_name(representative),
            "canonical_id": str(representative.get("canonical_id") or ""),
            "tvg_id": str(representative.get("tvg_id") or ""),
            "logo": logo,
            "quality_category": quality,
            "match_type": str(representative.get("logo_match_type") or ""),
            "provenance": str(representative.get("logo_provenance") or ""),
            "note": str(representative.get("logo_note") or ""),
            "feed_count": len(group),
        })
    rows.sort(key=lambda row: (row["country_code"], _normalize_name(row["channel"])))

    countries: dict[str, dict] = {}
    for country in sorted({row["country_code"] for row in rows}):
        countries[country] = _summary([row for row in rows if row["country_code"] == country])

    return {
        "schema_version": 1,
        "generated_at": generated_at,
        "registry_path": registry_path,
        "metric": {
            "name": "Channel logo coverage",
            "definition": (
                "Stable logical channels with a logo URL divided by all stable logical channels. "
                "Canonical coverage counts only reviewed logo_overrides mappings."
            ),
        },
        "summary": _summary(rows),
        "countries": countries,
        "channels": rows,
        "missing_channels": [row for row in rows if row["quality_category"] == QUALITY_MISSING],
    }


def write_logo_quality_outputs(
    data: dict,
    *,
    output_path: Path,
    missing_csv_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with missing_csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = ["country_code", "channel", "tvg_id", "canonical_id", "key"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in data.get("missing_channels") or []:
            writer.writerow({field: row.get(field, "") for field in fieldnames})
'''

TESTS = r'''from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from iptv.logo_quality import (
    LogoRegistry,
    QUALITY_CANONICAL,
    QUALITY_MISSING,
    QUALITY_SOURCE,
    apply_channel_logos,
    build_logo_quality,
    write_logo_quality_outputs,
)
from iptv.publication import prepare_published_entries


ROOT = Path(__file__).resolve().parents[1]


def entry(name: str, *, country: str = "HU", tvg_id: str = "", canonical_id: str = "", logo: str = "", source: str = "One", order: int = 1) -> dict:
    attrs = []
    if tvg_id:
        attrs.append(f'tvg-id="{tvg_id}"')
    if logo:
        attrs.append(f'tvg-logo="{logo}"')
    return {
        "channel_name": name,
        "display_name": name,
        "tvg_name": name,
        "tvg_id": tvg_id,
        "canonical_id": canonical_id,
        "country_code": country,
        "language_code": country,
        "language_codes": ["hun"],
        "url": f"https://stream.test/{source}/{order}.m3u8",
        "source": source,
        "classification": "Base channel",
        "_source_order": order,
        "_decision": "Verified",
        "lines": [f'#EXTINF:-1 {" ".join(attrs)},{name}', f"https://stream.test/{source}/{order}.m3u8"],
    }


class LogoQualityTests(unittest.TestCase):
    def test_canonical_override_precedence_and_provenance(self):
        registry = LogoRegistry({
            "schema_version": 1,
            "entries": [
                {"match": {"country_code": "HU", "tvg_id": "One.hu"}, "logo": "https://logos.test/tvg.png", "source": "reviewed tvg-id source"},
                {"match": {"canonical_id": "one"}, "logo": "https://logos.test/canonical.png", "source": "official broadcaster"},
            ],
        })
        resolved = registry.resolve(entry("One", tvg_id="One.hu", canonical_id="one"))
        self.assertEqual(resolved["logo"], "https://logos.test/canonical.png")
        self.assertEqual(resolved["match_type"], "canonical_id")
        self.assertEqual(resolved["source"], "official broadcaster")

    def test_registry_rejects_unreviewed_or_insecure_logo(self):
        with self.assertRaisesRegex(RuntimeError, "source provenance"):
            LogoRegistry({"entries": [{"match": {"canonical_id": "one"}, "logo": "https://logos.test/one.png"}]})
        with self.assertRaisesRegex(RuntimeError, "HTTPS"):
            LogoRegistry({"entries": [{"match": {"canonical_id": "one"}, "logo": "http://logos.test/one.png", "source": "official"}]})

    def test_override_is_consistent_across_alternative_feeds_and_rewrites_extinf(self):
        registry = LogoRegistry({"entries": [
            {"match": {"canonical_id": "one"}, "logo": "https://logos.test/one.png", "source": "official broadcaster"},
        ]})
        feeds = [
            entry("One", canonical_id="one", logo="https://old.test/a.png", source="A", order=1),
            entry("One", canonical_id="one", logo="https://old.test/b.png", source="B", order=2),
        ]
        applied = apply_channel_logos(feeds, registry)
        self.assertTrue(all(row["logo"] == "https://logos.test/one.png" for row in applied))
        self.assertTrue(all(row["logo_quality"] == QUALITY_CANONICAL for row in applied))
        published = prepare_published_entries(applied, {"default_country_code": "HU", "country_names": {"HU": "Hungary"}})
        self.assertTrue(all('tvg-logo="https://logos.test/one.png"' in row["lines"][0] for row in published))

    def test_source_fallback_is_unified_without_becoming_canonical(self):
        feeds = [
            entry("One", canonical_id="one", source="A", order=1),
            entry("One", canonical_id="one", logo="https://source.test/one.png", source="B", order=2),
        ]
        applied = apply_channel_logos(feeds, LogoRegistry())
        self.assertTrue(all(row["logo"] == "https://source.test/one.png" for row in applied))
        self.assertTrue(all(row["logo_quality"] == QUALITY_SOURCE for row in applied))
        self.assertTrue(all(row["logo_match_type"] == "source_tvg_logo" for row in applied))

    def test_quality_report_counts_logical_channels_not_feeds(self):
        registry = LogoRegistry({"entries": [
            {"match": {"canonical_id": "one"}, "logo": "https://logos.test/one.png", "source": "official"},
        ]})
        rows = apply_channel_logos([
            entry("One", canonical_id="one", source="A", order=1),
            entry("One", canonical_id="one", source="B", order=2),
            entry("Two", tvg_id="Two.hu", logo="https://source.test/two.png", source="C", order=3),
            entry("Three", tvg_id="Three.hu", source="D", order=4),
        ], registry)
        report = build_logo_quality(rows)
        self.assertEqual(report["summary"]["stable_logical_channels"], 3)
        self.assertEqual(report["summary"]["canonical_logo"], 1)
        self.assertEqual(report["summary"]["source_fallback"], 1)
        self.assertEqual(report["summary"]["missing_logo"], 1)
        self.assertAlmostEqual(report["summary"]["logo_availability_percent"], 66.7)
        self.assertAlmostEqual(report["summary"]["canonical_logo_coverage_percent"], 33.3)
        self.assertEqual(report["missing_channels"][0]["quality_category"], QUALITY_MISSING)

    def test_outputs_and_repository_contract(self):
        report = build_logo_quality(apply_channel_logos([entry("Missing")], LogoRegistry()))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_logo_quality_outputs(report, output_path=root / "logo-quality.json", missing_csv_path=root / "missing-logos.csv")
            self.assertTrue((root / "logo-quality.json").is_file())
            self.assertIn("Missing", (root / "missing-logos.csv").read_text(encoding="utf-8-sig"))

        config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(config.get("logo_overrides_path"), "data/logo_overrides.json")
        registry_payload = json.loads((ROOT / "data" / "logo_overrides.json").read_text(encoding="utf-8"))
        self.assertEqual(registry_payload.get("schema_version"), 1)
        self.assertIsInstance(registry_payload.get("entries"), list)

        template = (ROOT / "templates" / "dashboard.html").read_text(encoding="utf-8")
        script = (ROOT / "static" / "dashboard.js").read_text(encoding="utf-8")
        self.assertIn("Channel logo quality", template)
        self.assertIn("Canonical logo coverage", template + script)
        self.assertIn("Source fallback", template + script)
        self.assertIn("logo-quality.json", script)
        self.assertIn("missing-logos.csv", template)


if __name__ == "__main__":
    unittest.main()
'''

DOCS = r'''# Canonical channel logos

Channel logos are a presentation-quality dimension for the stable family playlist.
The build **does not scrape or discover logos automatically**.

## Manual authority

Reviewed logo mappings live in `data/logo_overrides.json`. Each entry must contain:

- exactly one supported selector;
- an absolute HTTPS `logo` URL;
- non-empty `source` provenance explaining where the image came from;
- an optional `note`.

Supported selectors, in descending precedence, are:

1. `canonical_id`
2. `country_code` + `tvg_id`
3. `country_code` + `channel`

Example:

```json
{
  "match": {"country_code": "HU", "tvg_id": "M1.hu"},
  "logo": "https://example.invalid/m1.png",
  "source": "official broadcaster asset",
  "note": "Reviewed manually"
}
```

Do not add a mapping merely because an image search found something plausible.
The provenance requirement is deliberate.

## Source fallback

Existing upstream `tvg-logo` metadata remains usable so current playlists do not
lose artwork. When no reviewed override exists, all feeds of the same logical
channel are normalized to one existing source logo and classified as **Source
fallback**. Source fallback is not counted as canonical coverage.

The stable dashboard uses three mutually exclusive states:

- **Canonical** — reviewed override from `logo_overrides.json`;
- **Source fallback** — existing upstream `tvg-logo`, normalized across feeds;
- **Missing** — no usable logo URL.

## Generated quality report

Every build writes:

- `public/logo-quality.json`
- `public/missing-logos.csv`

`logo_availability_percent` counts Canonical + Source fallback channels.
`canonical_logo_coverage_percent` counts only reviewed canonical mappings.
Both metrics use stable logical channels rather than stream URLs, so alternate
feeds do not inflate coverage.

The report measures mapping availability, not whether the remote image server is
currently reachable. A future logo-health probe can be added separately without
changing the manual mapping authority.
'''

(ROOT / "iptv/logo_quality.py").write_text(LOGO_QUALITY, encoding="utf-8")
(ROOT / "tests/test_logo_quality.py").write_text(TESTS, encoding="utf-8")
(ROOT / "docs/logo-quality.md").write_text(DOCS, encoding="utf-8")
(ROOT / "data/logo_overrides.json").write_text(
    json.dumps({"schema_version": 1, "entries": []}, indent=2) + "\n",
    encoding="utf-8",
)

# config: explicit canonical logo registry path.
replace_exact(
    "config.json",
    '  "identity_overrides_path": "data/identity_overrides.json",\n',
    '  "identity_overrides_path": "data/identity_overrides.json",\n  "logo_overrides_path": "data/logo_overrides.json",\n',
)

# Publication: rewrite the actual tvg-logo metadata in generated M3U entries.
replace_exact(
    "iptv/publication.py",
    'def rewrite_extinf_line(line: str, new_name: str, group_title: str) -> str:\n    metadata, _old_name = split_extinf(line)\n    safe_group = (group_title or "").replace(\'"\', "\'")\n',
    'def rewrite_extinf_line(\n    line: str,\n    new_name: str,\n    group_title: str,\n    logo: str | None = None,\n) -> str:\n    metadata, _old_name = split_extinf(line)\n    if logo is not None:\n        safe_logo = str(logo or "").replace(\'"\', "%22").strip()\n        if re.search(r\'\\s+tvg-logo="[^\"]*"\', metadata, flags=re.IGNORECASE):\n            if safe_logo:\n                metadata = re.sub(\n                    r\'\\s+tvg-logo="[^\"]*"\',\n                    f\' tvg-logo="{safe_logo}"\',\n                    metadata,\n                    count=1,\n                    flags=re.IGNORECASE,\n                )\n            else:\n                metadata = re.sub(\n                    r\'\\s+tvg-logo="[^\"]*"\',\n                    "",\n                    metadata,\n                    count=1,\n                    flags=re.IGNORECASE,\n                )\n        elif safe_logo:\n            metadata += f\' tvg-logo="{safe_logo}"\'\n\n    safe_group = (group_title or "").replace(\'"\', "\'")\n',
)
replace_exact(
    "iptv/publication.py",
    'def rewrite_entry_lines(lines: list[str], new_name: str, group_title: str) -> list[str]:\n    updated = list(lines)\n    for i, line in enumerate(updated):\n        if line.strip().startswith("#EXTINF:"):\n            updated[i] = rewrite_extinf_line(line, new_name, group_title)\n            break\n    return updated\n',
    'def rewrite_entry_lines(\n    lines: list[str],\n    new_name: str,\n    group_title: str,\n    logo: str | None = None,\n) -> list[str]:\n    updated = list(lines)\n    for i, line in enumerate(updated):\n        if line.strip().startswith("#EXTINF:"):\n            updated[i] = rewrite_extinf_line(line, new_name, group_title, logo)\n            break\n    return updated\n',
)
replace_exact(
    "iptv/publication.py",
    '                    published_name,\n                    group_title,\n                )\n',
    '                    published_name,\n                    group_title,\n                    str(published.get("logo") or ""),\n                )\n',
)

# Build orchestration: load/apply the canonical layer and publish a generated coverage report.
replace_exact(
    "iptv/build_core.py",
    'from iptv.channel_identity import logical_channel_key\n',
    'from iptv.channel_identity import logical_channel_key\nfrom iptv.logo_quality import (\n    LogoRegistry,\n    load_logo_registry,\n    apply_channel_logos,\n    build_logo_quality,\n    write_logo_quality_outputs,\n)\n',
)
replace_exact(
    "iptv/build_core.py",
    '    final_entries, language_only_entries, duplicate_rows, source_stats = collect_source_entries(\n',
    '    raw_logo_path = str(cfg.get("logo_overrides_path") or "").strip()\n    if raw_logo_path:\n        logo_registry = load_logo_registry(ROOT / raw_logo_path)\n    else:\n        logo_registry = LogoRegistry()\n\n    final_entries, language_only_entries, duplicate_rows, source_stats = collect_source_entries(\n',
)
replace_exact(
    "iptv/build_core.py",
    '    test_entries = (\n        prepare_published_entries(\n            test_candidates,\n            cfg,\n        )\n    )\n',
    '    test_candidates = apply_channel_logos(test_candidates, logo_registry)\n    stable_candidates = apply_channel_logos(stable_candidates, logo_registry)\n    language_stable_candidates = apply_channel_logos(\n        language_stable_candidates, logo_registry\n    )\n\n    test_entries = (\n        prepare_published_entries(\n            test_candidates,\n            cfg,\n        )\n    )\n',
)
replace_exact(
    "iptv/build_core.py",
    '    source_concentration = build_source_concentration(\n',
    '    logo_quality = build_logo_quality(\n        published_entries,\n        generated_at=generated,\n        registry_path=raw_logo_path,\n    )\n    write_logo_quality_outputs(\n        logo_quality,\n        output_path=public_dir / "logo-quality.json",\n        missing_csv_path=public_dir / "missing-logos.csv",\n    )\n\n    source_concentration = build_source_concentration(\n',
)

# Reports: expose provenance next to the existing logo URL.
replace_exact(
    "iptv/reports.py",
    '            "tvg_id": entry.get("tvg_id", ""),\n            "feed_quality_score": int(\n',
    '            "tvg_id": entry.get("tvg_id", ""),\n            "logo": entry.get("logo", ""),\n            "logo_quality": entry.get("logo_quality", ""),\n            "logo_match_type": entry.get("logo_match_type", ""),\n            "logo_provenance": entry.get("logo_provenance", ""),\n            "feed_quality_score": int(\n',
)
replace_exact(
    "iptv/reports.py",
    '            "logo": e.get("logo", ""),\n',
    '            "logo": e.get("logo", ""),\n            "logo_quality": e.get("logo_quality", ""),\n            "logo_match_type": e.get("logo_match_type", ""),\n            "logo_provenance": e.get("logo_provenance", ""),\n',
)
replace_exact(
    "iptv/reports.py",
    '            "logo",\n        ],\n',
    '            "logo",\n            "logo_quality",\n            "logo_match_type",\n            "logo_provenance",\n        ],\n',
)

# Dashboard HTML: add links and a dedicated logo-quality section after EPG quality.
replace_exact(
    "templates/dashboard.html",
    '    <a href="source-concentration.json">Source concentration reliability (JSON)</a>\n',
    '    <a href="source-concentration.json">Source concentration reliability (JSON)</a>\n    <a href="logo-quality.json">Channel logo quality (JSON)</a>\n    <a href="missing-logos.csv">Missing channel logos (CSV)</a>\n',
)
EPG_END = '''  <h2>Candidate streams to test</h2>\n'''
LOGO_SECTION = '''  <h2>Channel logo quality</h2>\n  <p class="muted">\n    Logos are measured per stable logical channel, not per stream URL. Canonical\n    logos come only from the reviewed data/logo_overrides.json registry. Existing\n    upstream tvg-logo metadata remains a Source fallback until reviewed; the build\n    never scrapes or auto-promotes random images.\n  </p>\n  <div id="logoQualitySummary" class="audit-summary">\n    <div class="card"><div class="value">…</div><div class="label">Loading logo coverage</div></div>\n  </div>\n  <h3>Logo coverage by country</h3>\n  <div id="logoCountrySummary" class="audit-summary">\n    <div class="card"><div class="value">…</div><div class="label">Loading country logo coverage</div></div>\n  </div>\n  <div class="controls">\n    <input id="logoQualitySearch" type="search" placeholder="Search channel logos...">\n    <select id="logoQualityFilter">\n      <option value="">All logo states</option>\n      <option value="Canonical">Canonical</option>\n      <option value="Source fallback">Source fallback</option>\n      <option value="Missing">Missing</option>\n    </select>\n  </div>\n  <p id="logoQualityVisibleCount" class="muted">Loading logo-quality.json…</p>\n  <div class="table-wrap">\n    <table id="logoQualityTable">\n      <thead><tr><th>Country</th><th>Channel</th><th>Status</th><th>Logo</th><th>Mapping</th><th>Provenance</th></tr></thead>\n      <tbody><tr><td colspan="6" class="muted">Loading channel logo quality…</td></tr></tbody>\n    </table>\n  </div>\n  <p class="muted">Canonical logo coverage is the stricter quality score. Overall availability also includes source fallbacks. Missing channels are exported in <a href="missing-logos.csv">missing-logos.csv</a>.</p>\n\n'''
replace_exact("templates/dashboard.html", EPG_END, LOGO_SECTION + EPG_END)

# Dashboard JS: country-aware logo summary/table.
replace_exact(
    "static/dashboard.js",
    '  renderEpgQuality();\n  applyEpgQualityFilters();\n',
    '  renderEpgQuality();\n  applyEpgQualityFilters();\n  renderLogoQuality();\n  applyLogoQualityFilters();\n',
)
JS_MARKER = '''function manualBadgeClass(status) {\n'''
JS_LOGO = r'''const logoQualitySummary = document.getElementById('logoQualitySummary');
const logoCountrySummary = document.getElementById('logoCountrySummary');
const logoQualitySearch = document.getElementById('logoQualitySearch');
const logoQualityFilter = document.getElementById('logoQualityFilter');
const logoQualityVisibleCount = document.getElementById('logoQualityVisibleCount');
const logoQualityTableBody = document.querySelector('#logoQualityTable tbody');
let logoQualityData = null;
let logoQualityRows = [];

function logoBadgeClass(category) {
  if (category === 'Canonical') return 'verified';
  if (category === 'Source fallback') return 'tv';
  if (category === 'Missing') return 'rejected';
  return 'base';
}

function logoSummaryForRows(rows) {
  const canonical = rows.filter(row => row.quality_category === 'Canonical').length;
  const source = rows.filter(row => row.quality_category === 'Source fallback').length;
  const missing = rows.filter(row => row.quality_category === 'Missing').length;
  const total = rows.length;
  return {
    total,
    canonical,
    source,
    missing,
    available: canonical + source,
    availability: total ? 100 * (canonical + source) / total : 0,
    canonicalCoverage: total ? 100 * canonical / total : 0,
  };
}

function renderLogoQuality() {
  if (!logoQualityData) return;
  const channels = Array.isArray(logoQualityData.channels) ? logoQualityData.channels : [];
  const rows = channels.filter(row => countryMatches(row.country_code));
  const summary = logoSummaryForRows(rows);
  if (logoQualitySummary) {
    logoQualitySummary.innerHTML = `
      <div class="card"><div class="value">${summary.availability.toFixed(1)}%</div><div class="label">Logo availability (${summary.available}/${summary.total})</div></div>
      <div class="card"><div class="value">${summary.canonicalCoverage.toFixed(1)}%</div><div class="label">Canonical logo coverage (${summary.canonical}/${summary.total})</div></div>
      <div class="card"><div class="value">${summary.canonical}</div><div class="label">Canonical</div></div>
      <div class="card"><div class="value">${summary.source}</div><div class="label">Source fallback</div></div>
      <div class="card"><div class="value">${summary.missing}</div><div class="label">Missing logos</div></div>`;
  }
  if (logoCountrySummary) {
    const countries = logoQualityData.countries || {};
    const codes = SUPPORTED_COUNTRIES.filter(code => countries[code]).filter(countryMatches);
    logoCountrySummary.innerHTML = codes.length ? codes.map(code => {
      const info = countries[code] || {};
      return `<div class="card" data-country="${esc(code)}">
        <div class="value">${Number(info.logo_availability_percent || 0).toFixed(1)}%</div>
        <div class="label">${esc(code)} logo availability (${Number(info.with_logo || 0)}/${Number(info.stable_logical_channels || 0)})</div>
        <div class="detail">Canonical ${Number(info.canonical_logo || 0)} · Source fallback ${Number(info.source_fallback || 0)} · Missing ${Number(info.missing_logo || 0)} · Canonical coverage ${Number(info.canonical_logo_coverage_percent || 0).toFixed(1)}%</div>
      </div>`;
    }).join('') : '<div class="card"><div class="value">—</div><div class="label">Country logo coverage unavailable</div></div>';
  }
}

function renderLogoQualityTable() {
  if (!logoQualityTableBody || !logoQualityData) return;
  const channels = Array.isArray(logoQualityData.channels) ? logoQualityData.channels : [];
  logoQualityTableBody.innerHTML = channels.length ? channels.map(row => {
    const logo = String(row.logo || '').trim();
    const preview = logo.startsWith('https://')
      ? `<img src="${esc(logo)}" alt="" loading="lazy" style="max-width:80px;max-height:38px;object-fit:contain;vertical-align:middle">`
      : '';
    const link = logo ? `<div><a href="${esc(logo)}" target="_blank" rel="noopener">logo URL</a></div>` : '—';
    return `<tr data-country="${esc(row.country_code || 'UNKNOWN')}" data-logo-quality="${esc(row.quality_category || '')}">
      <td>${esc(row.country_code || 'UNKNOWN')}</td><td class="channel">${esc(row.channel || 'Unnamed')}</td>
      <td><span class="badge ${logoBadgeClass(row.quality_category)}">${esc(row.quality_category || 'Unknown')}</span></td>
      <td>${preview}${link}</td><td>${esc(row.match_type || '—')}<div class="detail">${esc(row.tvg_id || row.canonical_id || '')}</div></td>
      <td>${esc(row.provenance || '—')}<div class="detail">${esc(row.note || '')}</div></td>
    </tr>`;
  }).join('') : '<tr><td colspan="6">No stable logical channels were reported.</td></tr>';
  logoQualityRows = Array.from(document.querySelectorAll('#logoQualityTable tbody tr[data-logo-quality]'));
  applyLogoQualityFilters();
}

function applyLogoQualityFilters() {
  if (!logoQualitySearch || !logoQualityFilter) return;
  const query = logoQualitySearch.value.trim().toLowerCase();
  const category = logoQualityFilter.value;
  let shown = 0;
  for (const row of logoQualityRows) {
    const matchesText = !query || row.innerText.toLowerCase().includes(query);
    const matchesCategory = !category || row.dataset.logoQuality === category;
    const show = countryMatches(row.dataset.country) && matchesText && matchesCategory;
    row.style.display = show ? '' : 'none';
    if (show) shown++;
  }
  if (logoQualityVisibleCount) {
    logoQualityVisibleCount.textContent = `Showing ${shown} of ${logoQualityRows.length} stable logical channels`;
  }
}

fetch('logo-quality.json', { cache: 'no-store' })
  .then(response => { if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.json(); })
  .then(data => {
    logoQualityData = data;
    renderLogoQuality();
    renderLogoQualityTable();
  })
  .catch(error => {
    if (logoQualitySummary) logoQualitySummary.innerHTML = `<div class="card"><div class="value">—</div><div class="label">Logo quality unavailable: ${esc(error.message)}</div></div>`;
    if (logoCountrySummary) logoCountrySummary.innerHTML = '<div class="card"><div class="value">—</div><div class="label">Country logo coverage unavailable</div></div>';
    if (logoQualityTableBody) logoQualityTableBody.innerHTML = `<tr><td colspan="6">logo-quality.json could not be loaded: ${esc(error.message)}</td></tr>`;
  });
if (logoQualitySearch) logoQualitySearch.addEventListener('input', applyLogoQualityFilters);
if (logoQualityFilter) logoQualityFilter.addEventListener('change', applyLogoQualityFilters);

'''
replace_exact("static/dashboard.js", JS_MARKER, JS_LOGO + JS_MARKER)

print("Canonical logo registry, publication rewrite, quality reporting and dashboard added.")
