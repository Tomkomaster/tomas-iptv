import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

from epg_merge import (
    channel_name_key,
    merge_guides,
)


class EpgMergeTests(unittest.TestCase):
    def write_playlist(
        self,
        path: Path,
    ) -> None:
        path.write_text(
            "#EXTM3U\n"
            '#EXTINF:-1 tvg-id="Duna.hu@SD",[HU OK] Duna (1080p)\n'
            "https://example.test/duna.m3u8\n"
            '#EXTINF:-1 tvg-id="DisneyChannel.hu@SD",[HU OK] Disney Channel\n'
            "https://example.test/disney.m3u8\n"
            '#EXTINF:-1 tvg-id="FEM3.hu@SD",[HU OK] FEM3\n'
            "https://example.test/fem3.m3u8\n",
            encoding="utf-8",
        )

    def write_iptv(
        self,
        guide_path: Path,
        coverage_path: Path,
    ) -> None:
        guide_path.write_text(
            """<?xml version="1.0" encoding="UTF-8"?>
<tv>
  <channel id="Duna.hu@SD"><display-name>Duna</display-name></channel>
  <channel id="FEM3.hu@SD"><display-name>FEM3</display-name></channel>
  <programme start="20260811060000 +0200" stop="20260811070000 +0200" channel="Duna.hu@SD"><title>Duna current</title></programme>
  <programme start="20260811080000 +0200" stop="20260811090000 +0200" channel="FEM3.hu@SD"><title>FEM3 current</title></programme>
</tv>
""",
            encoding="utf-8",
        )
        coverage_path.write_text(
            json.dumps({
                "playlist_tvg_ids": 3,
                "matched_tvg_ids": 2,
                "matched": [
                    {
                        "tvg_id": "Duna.hu@SD",
                        "provider": "mediaklikk.hu",
                        "provider_xmltv_id": "Duna.hu@SD",
                        "match_type": "exact",
                    },
                    {
                        "tvg_id": "FEM3.hu@SD",
                        "provider": "horizon.tv",
                        "provider_xmltv_id": "FEM3.hu@SD",
                        "match_type": "exact",
                    },
                ],
            }),
            encoding="utf-8",
        )

    def write_external(
        self,
        path: Path,
        programme_date: str = "20260811",
    ) -> None:
        path.write_text(
            f"""<?xml version="1.0" encoding="UTF-8"?>
<tv>
  <channel id="Duna.TV.hu"><display-name>Duna</display-name></channel>
  <channel id="Disney.Channel.hu"><display-name>Disney Channel</display-name></channel>
  <channel id="FEM3.hu"><display-name>FEM3</display-name></channel>
  <programme start="{programme_date}060000 +0200" stop="{programme_date}070000 +0200" channel="Duna.TV.hu"><title>External Duna</title></programme>
  <programme start="{programme_date}080000 +0200" stop="{programme_date}090000 +0200" channel="Disney.Channel.hu"><title>External Disney</title></programme>
  <programme start="{programme_date}100000 +0200" stop="{programme_date}110000 +0200" channel="FEM3.hu"><title>External FEM3</title></programme>
</tv>
""",
            encoding="utf-8",
        )

    def test_known_playlist_metadata_is_removed_without_fuzzy_matching(self):
        self.assertEqual(
            channel_name_key(
                "[HU OK] Apostol TV (576p) [Not 24/7]"
            ),
            "apostol tv",
        )
        self.assertEqual(
            channel_name_key("National Geographic HD"),
            "national geographic",
        )
        self.assertNotEqual(
            channel_name_key("RTL Ketto"),
            channel_name_key("RTL Gold"),
        )

    def test_external_fills_channels_but_mediaklikk_keeps_priority(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            playlist = root / "tv.m3u"
            iptv_guide = root / "iptv.xml"
            iptv_coverage = root / "iptv.json"
            external = root / "external.xml"
            output = root / "guide.xml"
            report = root / "coverage.json"

            self.write_playlist(playlist)
            self.write_iptv(iptv_guide, iptv_coverage)
            self.write_external(external)

            result = merge_guides(
                playlist_path=playlist,
                iptv_guide_path=iptv_guide,
                iptv_coverage_path=iptv_coverage,
                external_path=external,
                output_path=output,
                report_path=report,
                reference_date=date(2026, 8, 11),
            )

            providers = {
                item["tvg_id"]: item["provider"]
                for item in result["matched"]
            }
            self.assertEqual(
                providers["Duna.hu@SD"],
                "mediaklikk.hu",
            )
            self.assertEqual(
                providers["DisneyChannel.hu@SD"],
                "epgshare01.online",
            )
            self.assertEqual(
                providers["FEM3.hu@SD"],
                "epgshare01.online",
            )

            xml_root = ET.parse(output).getroot()
            programme_titles = {
                (
                    programme.get("channel"),
                    programme.findtext("title"),
                )
                for programme in xml_root.findall("programme")
            }
            self.assertIn(
                ("Duna.hu@SD", "Duna current"),
                programme_titles,
            )
            self.assertNotIn(
                ("Duna.hu@SD", "External Duna"),
                programme_titles,
            )
            self.assertIn(
                (
                    "DisneyChannel.hu@SD",
                    "External Disney",
                ),
                programme_titles,
            )

    def test_stale_external_is_ignored_and_horizon_fallback_survives(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            playlist = root / "tv.m3u"
            iptv_guide = root / "iptv.xml"
            iptv_coverage = root / "iptv.json"
            external = root / "external.xml"
            output = root / "guide.xml"
            report = root / "coverage.json"

            self.write_playlist(playlist)
            self.write_iptv(iptv_guide, iptv_coverage)
            self.write_external(
                external,
                programme_date="20260720",
            )

            result = merge_guides(
                playlist_path=playlist,
                iptv_guide_path=iptv_guide,
                iptv_coverage_path=iptv_coverage,
                external_path=external,
                output_path=output,
                report_path=report,
                reference_date=date(2026, 8, 11),
            )

            providers = {
                item["tvg_id"]: item["provider"]
                for item in result["matched"]
            }
            self.assertEqual(
                providers["Duna.hu@SD"],
                "mediaklikk.hu",
            )
            self.assertEqual(
                providers["FEM3.hu@SD"],
                "horizon.tv",
            )
            self.assertNotIn(
                "DisneyChannel.hu@SD",
                providers,
            )
            self.assertFalse(
                result["external"]["fresh"]
            )


if __name__ == "__main__":
    unittest.main()
