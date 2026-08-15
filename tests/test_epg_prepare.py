import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import epg_prepare


class EpgPrepareTests(unittest.TestCase):
    def test_custom_epg_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            playlist = root / "tv.m3u"
            playlist.write_text(
                "\n".join([
                    "#EXTM3U",
                    '#EXTINF:-1 tvg-id="M1.hu@HD",M1',
                    "https://example.test/m1",
                    '#EXTINF:-1 tvg-id="ATV.hu@SD",ATV',
                    "https://example.test/atv",
                    '#EXTINF:-1 tvg-id="JOJSport2.sk@HD",JOJ Sport 2 HD',
                    "https://example.test/joj-sport-2",
                    '#EXTINF:-1 tvg-id="Unknown.hu@SD",Unknown',
                    "https://example.test/unknown",
                    "",
                ]),
                encoding="utf-8",
            )

            official_dir = root / "epg" / "sites" / "official.test"
            official_dir.mkdir(parents=True)
            (official_dir / "official.test.channels.xml").write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
<channels>
  <channel site="official.test" lang="hu" xmltv_id="M1.hu@SD" site_id="1">M1</channel>
</channels>
""",
                encoding="utf-8",
            )

            broad_dir = root / "epg" / "sites" / "broad.test"
            broad_dir.mkdir(parents=True)
            (broad_dir / "broad.test.channels.xml").write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
<channels>
  <channel site="broad.test" lang="hu" xmltv_id="M1.hu@SD" site_id="m1">M1 alternate</channel>
  <channel site="broad.test" lang="hu" xmltv_id="ATV.hu@SD" site_id="atv">ATV</channel>
  <channel site="broad.test" lang="sk" xmltv_id="" site_id="joj_sport_2">JOJ Šport 2</channel>
</channels>
""",
                encoding="utf-8",
            )

            output = root / "channels.xml"
            report_path = root / "coverage.json"
            report = epg_prepare.prepare_epg_channels(
                playlist_path=playlist,
                epg_root=root / "epg",
                sites=["official.test", "broad.test"],
                output_path=output,
                report_path=report_path,
            )

            channels = ET.parse(output).getroot().findall("channel")
            self.assertEqual(
                [channel.get("xmltv_id") for channel in channels],
                ["M1.hu@HD", "ATV.hu@SD", "JOJSport2.sk@HD"],
            )
            self.assertEqual(channels[0].get("site"), "official.test")
            self.assertEqual(channels[0].get("site_id"), "1")
            self.assertEqual(channels[1].get("site"), "broad.test")
            self.assertEqual(channels[2].get("site_id"), "joj_sport_2")

            self.assertEqual(report["playlist_tvg_ids"], 4)
            self.assertEqual(report["matched_tvg_ids"], 3)
            self.assertEqual(report["unmatched_tvg_ids"], ["Unknown.hu@SD"])
            self.assertEqual(
                report["match_types"],
                {"exact": 1, "name": 1, "quality_variant": 1},
            )
            name_match = next(
                item for item in report["matched"] if item["match_type"] == "name"
            )
            self.assertEqual(name_match["provider_xmltv_id"], "")
            self.assertEqual(name_match["provider_name"], "JOJ Šport 2")
            self.assertTrue(report_path.is_file())

    def test_name_fallback_requires_unique_provider_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            playlist = root / "tv.m3u"
            playlist.write_text(
                "\n".join([
                    "#EXTM3U",
                    '#EXTINF:-1 tvg-id="RegionalTV.at@HD",Regional TV HD',
                    "https://example.test/regional",
                    "",
                ]),
                encoding="utf-8",
            )

            for site, site_id in (("one.test", "one"), ("two.test", "two")):
                site_dir = root / "epg" / "sites" / site
                site_dir.mkdir(parents=True)
                (site_dir / f"{site}.channels.xml").write_text(
                    f"""<?xml version="1.0" encoding="UTF-8"?>
<channels>
  <channel site="{site}" lang="de" xmltv_id="" site_id="{site_id}">Regional TV</channel>
</channels>
""",
                    encoding="utf-8",
                )

            with self.assertRaisesRegex(
                RuntimeError,
                "No playlist tvg-id values matched the configured EPG sites",
            ):
                epg_prepare.prepare_epg_channels(
                    playlist_path=playlist,
                    epg_root=root / "epg",
                    sites=["one.test", "two.test"],
                    output_path=root / "channels.xml",
                    report_path=root / "coverage.json",
                )

    def test_name_fallback_does_not_override_conflicting_provider_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            playlist = root / "tv.m3u"
            playlist.write_text(
                "\n".join([
                    "#EXTM3U",
                    '#EXTINF:-1 tvg-id="NovaInternational.cz@HD",Nova',
                    "https://example.test/nova",
                    "",
                ]),
                encoding="utf-8",
            )

            site_dir = root / "epg" / "sites" / "provider.test"
            site_dir.mkdir(parents=True)
            (site_dir / "provider.test.channels.xml").write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
<channels>
  <channel site="provider.test" lang="cs" xmltv_id="Nova.cz@SD" site_id="nova">Nova</channel>
</channels>
""",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                RuntimeError,
                "No playlist tvg-id values matched the configured EPG sites",
            ):
                epg_prepare.prepare_epg_channels(
                    playlist_path=playlist,
                    epg_root=root / "epg",
                    sites=["provider.test"],
                    output_path=root / "channels.xml",
                    report_path=root / "coverage.json",
                )

    def test_extinf_name_parser_ignores_commas_inside_attributes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tv.m3u"
            path.write_text(
                "\n".join([
                    "#EXTM3U",
                    '#EXTINF:-1 tvg-id="Example.at" tvg-name="Example, Austria",Example TV',
                    "https://example.test/live",
                    "",
                ]),
                encoding="utf-8",
            )
            self.assertEqual(
                epg_prepare.read_playlist_channels(path),
                [("Example.at", "Example TV")],
            )

    def test_site_selector_can_target_one_channels_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            playlist = root / "tv.m3u"
            playlist.write_text(
                "\n".join([
                    "#EXTM3U",
                    '#EXTINF:-1 tvg-id="DachChannel.at",DACH Channel',
                    "https://example.test/dach",
                    "",
                ]),
                encoding="utf-8",
            )

            site_dir = root / "epg" / "sites" / "pluto.test"
            site_dir.mkdir(parents=True)
            (site_dir / "pluto.test_de.channels.xml").write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
<channels>
  <channel site="pluto.test" lang="de" xmltv_id="" site_id="de-id">DACH Channel</channel>
</channels>
""",
                encoding="utf-8",
            )
            (site_dir / "pluto.test_us.channels.xml").write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
<channels>
  <channel site="pluto.test" lang="en" xmltv_id="" site_id="us-id">DACH Channel</channel>
</channels>
""",
                encoding="utf-8",
            )

            report = epg_prepare.prepare_epg_channels(
                playlist_path=playlist,
                epg_root=root / "epg",
                sites=["pluto.test/pluto.test_de.channels.xml"],
                output_path=root / "channels.xml",
                report_path=root / "coverage.json",
            )

            self.assertEqual(report["matched_tvg_ids"], 1)
            channel = ET.parse(root / "channels.xml").getroot().find("channel")
            self.assertIsNotNone(channel)
            self.assertEqual(channel.get("site"), "pluto.test")
            self.assertEqual(channel.get("site_id"), "de-id")


if __name__ == "__main__":
    unittest.main()
