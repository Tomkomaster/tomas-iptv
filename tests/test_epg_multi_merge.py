import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

from epg_multi_merge import merge_country_guides


class EpgMultiMergeTests(unittest.TestCase):
    def write_playlist(self, path: Path, code: str, tvg_id: str, name: str) -> None:
        path.write_text(
            "#EXTM3U\n"
            f'#EXTINF:-1 tvg-id="{tvg_id}",{name}\n'
            f"https://example.test/{code.lower()}.m3u8\n",
            encoding="utf-8",
        )

    def write_external(self, path: Path, external_id: str, name: str, title: str) -> None:
        path.write_text(
            f'''<?xml version="1.0" encoding="UTF-8"?>
<tv>
  <channel id="{external_id}"><display-name>{name}</display-name></channel>
  <programme start="20260811060000 +0200" stop="20260811070000 +0200" channel="{external_id}"><title>{title}</title></programme>
</tv>
''',
            encoding="utf-8",
        )

    def test_external_guides_are_scoped_by_country_before_recombining(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            public = root / "public"
            public.mkdir()
            external_dir = root / "external"
            external_dir.mkdir()

            ids = {
                "HU": "HungaryDemo.hu@SD",
                "SK": "SlovakDemo.sk@SD",
                "CZ": "CzechDemo.cz@SD",
            }
            names = {
                "HU": "Shared Demo",
                "SK": "Shared Demo",
                "CZ": "Czech Demo",
            }
            for code in ids:
                self.write_playlist(
                    public / f"{code.lower()}.m3u",
                    code,
                    ids[code],
                    names[code],
                )

            self.write_external(
                external_dir / "HU.xml",
                "External.HU",
                "Shared Demo",
                "Hungarian programme",
            )
            self.write_external(
                external_dir / "SK.xml",
                "External.SK",
                "Shared Demo",
                "Slovak programme",
            )
            self.write_external(
                external_dir / "CZ.xml",
                "External.CZ",
                "Czech Demo",
                "Czech programme",
            )

            config = {
                "country_outputs": {
                    "HU": "public/hu.m3u",
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
                        for code in ids
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
                        code: {
                            "playlist_tvg_ids": 1,
                            "matched_tvg_ids": 0,
                            "sites": ["example.test"],
                        }
                        for code in ids
                    },
                    "tvg_id_countries": {
                        ids[code]: code
                        for code in ids
                    },
                }),
                encoding="utf-8",
            )

            output = root / "guide.xml"
            report_path = root / "coverage.json"
            result = merge_country_guides(
                config_path=config_path,
                iptv_guide_path=iptv_guide,
                iptv_coverage_path=iptv_coverage,
                external_dir=external_dir,
                aliases_path=None,
                reference_date=date(2026, 8, 11),
                output_path=output,
                report_path=report_path,
            )

            self.assertEqual(result["playlist_tvg_ids"], 3)
            self.assertEqual(result["matched_tvg_ids"], 3)
            self.assertEqual(
                result["tvg_id_countries"],
                {ids[code]: code for code in ids},
            )
            for code in ids:
                self.assertEqual(result["countries"][code]["matched_tvg_ids"], 1)
                self.assertTrue(result["external"]["countries"][code]["fresh"])
                self.assertTrue(result["external"]["countries"][code]["downloaded"])

            guide = ET.parse(output).getroot()
            titles = {
                programme.get("channel"): programme.findtext("title")
                for programme in guide.findall("programme")
            }
            self.assertEqual(titles[ids["HU"]], "Hungarian programme")
            self.assertEqual(titles[ids["SK"]], "Slovak programme")
            self.assertEqual(titles[ids["CZ"]], "Czech programme")


if __name__ == "__main__":
    unittest.main()
