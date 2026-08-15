import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

from epg_cross_country_alias import apply_cross_country_aliases
from epg_multi_merge import merge_country_guides


class CrossCountryEpgAliasTests(unittest.TestCase):
    def write_playlist(self, path: Path, tvg_id: str, name: str) -> None:
        path.write_text(
            "#EXTM3U\n"
            f'#EXTINF:-1 tvg-id="{tvg_id}",{name}\n'
            "https://example.test/stream.m3u8\n",
            encoding="utf-8",
        )

    def write_external(
        self,
        path: Path,
        channels: list[tuple[str, str, str, str]],
    ) -> None:
        root = ET.Element("tv")
        for channel_id, name, start, title in channels:
            channel = ET.SubElement(root, "channel", {"id": channel_id})
            display = ET.SubElement(channel, "display-name")
            display.text = name
            programme = ET.SubElement(
                root,
                "programme",
                {
                    "start": start,
                    "stop": start[:8] + "070000 +0200",
                    "channel": channel_id,
                },
            )
            title_node = ET.SubElement(programme, "title")
            title_node.text = title
        ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)

    def base_fixture(self, root: Path) -> tuple[Path, Path, Path, Path]:
        public = root / "public"
        public.mkdir()
        external = root / "external"
        external.mkdir()

        self.write_playlist(public / "sk.m3u", "Local.sk@SD", "Cross Demo")
        self.write_playlist(public / "cz.m3u", "Czech.cz@SD", "Czech Demo")
        self.write_external(
            external / "SK.xml",
            [("Other.SK", "Other Slovak", "20260811060000 +0200", "SK programme")],
        )
        self.write_external(
            external / "CZ.xml",
            [
                ("Cross.CZ", "Cross Demo", "20260811060000 +0200", "Cross programme"),
                ("Czech.CZ", "Czech Demo", "20260811060000 +0200", "Czech programme"),
            ],
        )

        config = {
            "country_outputs": {
                "SK": "public/sk.m3u",
                "CZ": "public/cz.m3u",
            },
            "epg": {
                "countries": {
                    code: {
                        "sites": ["example.test"],
                        "external": {
                            "provider": "epgshare01.online",
                            "url": f"https://example.test/{code}.xml.gz",
                        },
                    }
                    for code in ("SK", "CZ")
                }
            },
        }
        config_path = root / "config.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")

        iptv_guide = root / "iptv.xml"
        iptv_guide.write_text("<tv />\n", encoding="utf-8")
        iptv_coverage = root / "iptv.json"
        iptv_coverage.write_text(
            json.dumps({
                "matched": [],
                "countries": {
                    "SK": {"playlist_tvg_ids": 1, "matched_tvg_ids": 0},
                    "CZ": {"playlist_tvg_ids": 1, "matched_tvg_ids": 0},
                },
                "tvg_id_countries": {
                    "Local.sk@SD": "SK",
                    "Czech.cz@SD": "CZ",
                },
            }),
            encoding="utf-8",
        )
        return config_path, iptv_guide, iptv_coverage, external

    def run_merge(self, root: Path, aliases_path: Path | None) -> dict:
        config, guide, coverage, external = self.base_fixture(root)
        return merge_country_guides(
            config_path=config,
            iptv_guide_path=guide,
            iptv_coverage_path=coverage,
            external_dir=external,
            aliases_path=aliases_path,
            reference_date=date(2026, 8, 11),
            future_days=7,
            output_path=root / "guide.xml",
            report_path=root / "coverage.json",
        )

    def test_other_country_same_name_is_not_automatic(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            result = self.run_merge(root, None)
            self.assertIn("Local.sk@SD", result["unmatched_tvg_ids"])
            self.assertEqual(result["countries"]["SK"]["matched_tvg_ids"], 0)

    def test_explicit_cross_country_alias_maps_fresh_programmes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            aliases_path = root / "aliases.json"
            aliases_path.write_text(
                json.dumps({
                    "provider": "epgshare01.online",
                    "aliases": {},
                    "cross_country_aliases": {
                        "Local.sk@SD": {
                            "playlist_country_code": "SK",
                            "external_country_code": "CZ",
                            "external_id": "Cross.CZ",
                        }
                    },
                }),
                encoding="utf-8",
            )
            result = self.run_merge(root, aliases_path)

            self.assertNotIn("Local.sk@SD", result["unmatched_tvg_ids"])
            self.assertEqual(result["countries"]["SK"]["matched_tvg_ids"], 1)
            item = next(
                item
                for item in result["matched"]
                if item.get("tvg_id") == "Local.sk@SD"
            )
            self.assertEqual(
                item["match_type"],
                "external_explicit_cross_country_alias",
            )
            self.assertEqual(item["external_country_code"], "CZ")
            self.assertGreater(int(item["fresh_programmes"]), 0)
            self.assertEqual(result["external"]["cross_country_aliases_configured"], 1)
            self.assertEqual(len(result["external"]["cross_country_aliases_used"]), 1)

            guide = ET.parse(root / "guide.xml").getroot()
            titles = {
                programme.get("channel"): programme.findtext("title")
                for programme in guide.findall("programme")
            }
            self.assertEqual(titles["Local.sk@SD"], "Cross programme")

    def test_cross_country_alias_recovers_mapped_but_empty_target(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            playlist = root / "sk.m3u"
            external = root / "external"
            external.mkdir()
            self.write_playlist(playlist, "Local.sk@SD", "Cross Demo")
            self.write_external(
                external / "CZ.xml",
                [("Cross.CZ", "Cross Demo", "20260811060000 +0200", "Cross programme")],
            )

            country_root = ET.Element("tv")
            stale_channel = ET.SubElement(country_root, "channel", {"id": "Local.sk@SD"})
            ET.SubElement(stale_channel, "display-name").text = "Cross Demo"
            country_report = {
                "playlist_tvg_ids": 1,
                "matched": [{
                    "tvg_id": "Local.sk@SD",
                    "provider": "webtv.sk",
                    "provider_xmltv_id": "",
                    "match_type": "name",
                    "fresh_programmes": 0,
                }],
                "unmatched_tvg_ids": [],
                "providers": {"webtv.sk": 1},
                "fresh_channels_by_provider": {},
                "reference_date": "2026-08-11",
            }

            result = apply_cross_country_aliases(
                country_code="SK",
                playlist_path=playlist,
                country_root=country_root,
                country_report=country_report,
                aliases={
                    "Local.sk@SD": {
                        "playlist_country_code": "SK",
                        "external_country_code": "CZ",
                        "external_id": "Cross.CZ",
                    }
                },
                alias_provider="epgshare01.online",
                countries_cfg={
                    "CZ": {
                        "external": {
                            "provider": "epgshare01.online",
                        }
                    }
                },
                external_dir=external,
                external_cache={},
                reference_date=date(2026, 8, 11),
                future_days=7,
            )

            self.assertEqual(len(result["used"]), 1)
            self.assertEqual(result["used"][0]["replaced_provider"], "webtv.sk")
            self.assertEqual(country_report["providers"], {"epgshare01.online": 1})
            item = country_report["matched"][0]
            self.assertEqual(item["provider"], "epgshare01.online")
            self.assertEqual(
                item["match_type"],
                "external_explicit_cross_country_alias",
            )
            self.assertGreater(int(item["fresh_programmes"]), 0)

            channels = country_root.findall("channel")
            self.assertEqual(len(channels), 1)
            self.assertEqual(channels[0].get("id"), "Local.sk@SD")
            programmes = country_root.findall("programme")
            self.assertEqual(len(programmes), 1)
            self.assertEqual(programmes[0].get("channel"), "Local.sk@SD")
            self.assertEqual(programmes[0].findtext("title"), "Cross programme")

    def test_cross_country_alias_keeps_fresh_local_mapping(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            playlist = root / "sk.m3u"
            external = root / "external"
            external.mkdir()
            self.write_playlist(playlist, "Local.sk@SD", "Cross Demo")
            self.write_external(
                external / "CZ.xml",
                [("Cross.CZ", "Cross Demo", "20260811060000 +0200", "Cross programme")],
            )

            country_root = ET.Element("tv")
            local_channel = ET.SubElement(country_root, "channel", {"id": "Local.sk@SD"})
            ET.SubElement(local_channel, "display-name").text = "Cross Demo"
            country_report = {
                "playlist_tvg_ids": 1,
                "matched": [{
                    "tvg_id": "Local.sk@SD",
                    "provider": "webtv.sk",
                    "provider_xmltv_id": "",
                    "match_type": "name",
                    "fresh_programmes": 12,
                }],
                "unmatched_tvg_ids": [],
                "providers": {"webtv.sk": 1},
                "fresh_channels_by_provider": {"webtv.sk": 1},
                "reference_date": "2026-08-11",
            }

            result = apply_cross_country_aliases(
                country_code="SK",
                playlist_path=playlist,
                country_root=country_root,
                country_report=country_report,
                aliases={
                    "Local.sk@SD": {
                        "playlist_country_code": "SK",
                        "external_country_code": "CZ",
                        "external_id": "Cross.CZ",
                    }
                },
                alias_provider="epgshare01.online",
                countries_cfg={
                    "CZ": {
                        "external": {
                            "provider": "epgshare01.online",
                        }
                    }
                },
                external_dir=external,
                external_cache={},
                reference_date=date(2026, 8, 11),
                future_days=7,
            )

            self.assertEqual(result["used"], [])
            self.assertEqual(country_report["providers"], {"webtv.sk": 1})
            self.assertEqual(country_report["matched"][0]["provider"], "webtv.sk")
            self.assertEqual(len(country_root.findall("channel")), 1)

    def test_cross_country_alias_without_fresh_programmes_stays_unmapped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config, guide, coverage, external = self.base_fixture(root)
            self.write_external(
                external / "CZ.xml",
                [
                    ("Cross.CZ", "Cross Demo", "20260701060000 +0200", "Old programme"),
                    ("Czech.CZ", "Czech Demo", "20260811060000 +0200", "Czech programme"),
                ],
            )
            aliases_path = root / "aliases.json"
            aliases_path.write_text(
                json.dumps({
                    "provider": "epgshare01.online",
                    "cross_country_aliases": {
                        "Local.sk@SD": {
                            "playlist_country_code": "SK",
                            "external_country_code": "CZ",
                            "external_id": "Cross.CZ",
                        }
                    },
                }),
                encoding="utf-8",
            )
            result = merge_country_guides(
                config_path=config,
                iptv_guide_path=guide,
                iptv_coverage_path=coverage,
                external_dir=external,
                aliases_path=aliases_path,
                reference_date=date(2026, 8, 11),
                future_days=7,
                output_path=root / "guide.xml",
                report_path=root / "coverage.json",
            )
            self.assertIn("Local.sk@SD", result["unmatched_tvg_ids"])
            self.assertEqual(len(result["external"]["cross_country_aliases_used"]), 0)
            skipped = result["external"]["cross_country_aliases_skipped"]
            self.assertEqual(skipped[0]["reason"], "no current/future programme data")


if __name__ == "__main__":
    unittest.main()
