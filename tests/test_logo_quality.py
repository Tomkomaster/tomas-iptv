from __future__ import annotations

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
        "logo": logo,
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
        self.assertIn("priority-coverage.json", script)
        self.assertIn("P1 / P2 logo completeness", template)
        self.assertIn('id="priorityLogoSummary"', template)
        self.assertIn("P1/P2 canonical coverage", script)
        self.assertIn("missing-logos.csv", template)


if __name__ == "__main__":
    unittest.main()
