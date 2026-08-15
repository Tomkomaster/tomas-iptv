import json
import tempfile
import unittest
from pathlib import Path

from build import (
    build_language_catalog_entries,
    entries_for_spoken_language,
    write_m3u_playlist,
)
from country_language import configured_language_codes


ROOT = Path(__file__).resolve().parents[1]


class LanguagePlaylistTests(unittest.TestCase):
    def test_config_exposes_configured_language_outputs(self):
        cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(
            cfg["language_outputs"],
            {
                "hun": "public/by-language/hun.m3u",
                "slk": "public/by-language/slk.m3u",
                "ces": "public/by-language/ces.m3u",
                "ron": "public/by-language/ron.m3u",
                "deu": "public/by-language/deu.m3u",
                "srp": "public/by-language/srp.m3u",
            },
        )
        supported = configured_language_codes(cfg)
        for code in ("hun", "slk", "ces", "ron", "deu", "srp"):
            self.assertIn(code, supported)

    def test_serbian_hungarian_entry_remains_rs_in_hungarian_catalog(self):
        country_entry = {
            "url": "https://example.test/hu.m3u8",
            "country_code": "HU",
            "language_code": "HU",
            "language_codes": ["hun"],
            "channel_name": "Hungary One",
            "display_name": "Hungary One",
            "published_name": "[HU OK] Hungary One",
            "group_title": "Hungary | General",
            "lines": [
                '#EXTINF:-1 tvg-id="HungaryOne.hu@SD" group-title="Hungary | General",[HU OK] Hungary One',
                "https://example.test/hu.m3u8",
            ],
        }
        serbian_entry = {
            "url": "https://example.test/rs-hun.m3u8",
            "country_code": "RS",
            "language_code": "RS",
            "language_codes": ["hun"],
            "channel_name": "Pannon RTV",
            "display_name": "Pannon RTV",
            "published_name": "[RS OK] Pannon RTV",
            "group_title": "Serbia | General",
            "lines": [
                '#EXTINF:-1 tvg-id="PannonRTV.rs@SD" group-title="Serbia | General",[RS OK] Pannon RTV',
                "https://example.test/rs-hun.m3u8",
            ],
        }

        catalog = build_language_catalog_entries([country_entry], [serbian_entry])
        hungarian = entries_for_spoken_language(catalog, "hun")
        self.assertEqual({e["country_code"] for e in hungarian}, {"HU", "RS"})

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "hun.m3u"
            write_m3u_playlist(
                output,
                {"epg": {"enabled": False}},
                hungarian,
                "2026-08-12 00:00:00 UTC",
                "Stable Hungarian spoken-language playlist",
                name_style="country",
            )
            text = output.read_text(encoding="utf-8")
            self.assertIn("[HU] Hungary One", text)
            self.assertIn("[RS] Pannon RTV", text)

    def test_exact_country_url_keeps_geography_but_merges_language_metadata(self):
        country_entry = {
            "url": "https://example.test/shared.m3u8",
            "country_code": "HU",
            "language_code": "HU",
            "language_codes": ["hun"],
        }
        derived_duplicate = {
            "url": "https://example.test/shared.m3u8",
            "country_code": "RS",
            "language_code": "RS",
            "language_codes": ["srp", "hun"],
        }
        catalog = build_language_catalog_entries(
            [country_entry],
            [derived_duplicate],
        )
        self.assertEqual(len(catalog), 1)
        self.assertEqual(catalog[0]["country_code"], "HU")
        self.assertEqual(catalog[0]["language_codes"], ["hun", "srp"])

    def test_multilingual_entry_can_appear_in_multiple_language_playlists(self):
        entry = {
            "url": "https://example.test/multi.m3u8",
            "country_code": "RS",
            "language_codes": ["srp", "hun"],
        }
        catalog = build_language_catalog_entries([], [entry])
        self.assertEqual(len(entries_for_spoken_language(catalog, "hun")), 1)
        self.assertEqual(len(entries_for_spoken_language(catalog, "srp")), 1)


if __name__ == "__main__":
    unittest.main()
