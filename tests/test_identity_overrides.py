import json
import unittest
from pathlib import Path

from build import channel_key, parse_entries
from identity_overrides import IdentityRegistry, load_identity_registry


class IdentityRegistryTests(unittest.TestCase):
    def registry(self):
        return IdentityRegistry({
            "schema_version": 1,
            "identities": {
                "sk:exact": {"channel_name": "Exact TV", "language_code": "SK"},
                "sk:tvg": {"channel_name": "TVG TV", "language_code": "SK"},
                "sk:name": {"channel_name": "Name TV", "language_code": "SK"},
                "sk:manual": {"channel_name": "Manual TV", "language_code": "SK"},
            },
            "selectors": [
                {
                    "match": {"url": "https://example.test/live.m3u8"},
                    "canonical_id": "sk:exact",
                },
                {
                    "match": {"source": "Provider A", "tvg_id": "Wrong.id"},
                    "canonical_id": "sk:tvg",
                },
                {
                    "match": {
                        "source": "Provider A",
                        "normalized_name": "Wrong Upstream Name",
                    },
                    "canonical_id": "sk:name",
                },
            ],
        })

    def test_exact_url_has_highest_precedence(self):
        result = self.registry().resolve(
            {
                "url": "https://EXAMPLE.test:443/live.m3u8#ignored",
                "tvg_id": "Wrong.id",
            },
            source="Provider A",
            normalized_name="Wrong Upstream Name",
        )
        self.assertEqual(result["canonical_id"], "sk:exact")
        self.assertEqual(result["match_type"], "exact_url")

    def test_source_tvg_id_beats_source_normalized_name(self):
        result = self.registry().resolve(
            {
                "url": "https://other.test/live.m3u8",
                "tvg_id": "WRONG.ID",
            },
            source=" provider   a ",
            normalized_name="Wrong Upstream Name",
        )
        self.assertEqual(result["canonical_id"], "sk:tvg")
        self.assertEqual(result["match_type"], "source_tvg_id")

    def test_source_normalized_name_is_supported(self):
        result = self.registry().resolve(
            {
                "url": "https://other.test/live.m3u8",
                "tvg_id": "",
            },
            source="Provider A",
            normalized_name="Wrong — Upstream   Name",
        )
        self.assertEqual(result["canonical_id"], "sk:name")
        self.assertEqual(result["match_type"], "source_normalized_name")

    def test_manual_canonical_id_is_lowest_precedence_fallback(self):
        result = self.registry().resolve(
            {
                "url": "https://other.test/manual.m3u8",
                "canonical_id": "sk:manual",
            },
            source="Other",
            normalized_name="Anything",
        )
        self.assertEqual(result["canonical_id"], "sk:manual")
        self.assertEqual(result["match_type"], "canonical_id")

    def test_duplicate_selector_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "Duplicate identity selector"):
            IdentityRegistry({
                "schema_version": 1,
                "identities": {
                    "one": {"channel_name": "One"},
                    "two": {"channel_name": "Two"},
                },
                "selectors": [
                    {
                        "match": {"url": "https://example.test/live.m3u8"},
                        "canonical_id": "one",
                    },
                    {
                        "match": {"url": "https://EXAMPLE.test:443/live.m3u8"},
                        "canonical_id": "two",
                    },
                ],
            })

    def test_unknown_canonical_id_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "unknown canonical_id"):
            IdentityRegistry({
                "schema_version": 1,
                "identities": {"one": {"channel_name": "One"}},
                "selectors": [
                    {
                        "match": {"url": "https://example.test/live.m3u8"},
                        "canonical_id": "missing",
                    }
                ],
            })


class BuildIdentityIntegrationTests(unittest.TestCase):
    def test_channel_key_prefers_explicit_canonical_id(self):
        self.assertEqual(
            channel_key({
                "canonical_id": "sk:kanal1",
                "tvg_id": "Wrong.id",
                "tvg_name": "Wrong Name",
                "display_name": "Wrong Name",
            }),
            "canonical:sk:kanal1",
        )

    def test_parser_preserves_manual_canonical_id_attribute(self):
        entries = parse_entries(
            '#EXTM3U\n'
            '#EXTINF:-1 canonical-id="sk:manual" tvg-name="Manual TV",Manual TV\n'
            'https://example.test/manual.m3u8\n'
        )
        self.assertEqual(entries[0]["canonical_id"], "sk:manual")

    def test_kanal1_moved_out_of_config_into_identity_file(self):
        cfg = json.loads(Path("config.json").read_text(encoding="utf-8"))
        self.assertNotIn("stream_overrides", cfg)
        self.assertEqual(cfg["identity_overrides_path"], "identity_overrides.json")

        registry = load_identity_registry(Path(cfg["identity_overrides_path"]))
        result = registry.resolve({
            "url": "https://dash.antik.sk/live/test_upnetwork/playlist.m3u8",
            "tvg_id": "garbage",
        }, source="Any upstream source", normalized_name="Wrong")
        self.assertEqual(result["canonical_id"], "sk:kanal1")
        self.assertEqual(result["identity"]["channel_name"], "Kanal1")
        self.assertEqual(result["identity"]["language_code"], "SK")


if __name__ == "__main__":
    unittest.main()
