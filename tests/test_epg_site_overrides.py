import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from epg_prepare import prepare_epg_channels


class EpgSiteOverrideTests(unittest.TestCase):
    def test_local_override_adds_missing_exact_provider_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            playlist = root / "ro.m3u"
            playlist.write_text(
                "\n".join([
                    "#EXTM3U",
                    '#EXTINF:-1 tvg-id="Antena3CNN.ro",Antena 3 CNN',
                    "https://example.test/antena3",
                    "",
                ]),
                encoding="utf-8",
            )

            provider_dir = root / "epg" / "sites" / "programetv.ro"
            provider_dir.mkdir(parents=True)
            (provider_dir / "programetv.ro.channels.xml").write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
<channels>
  <channel site="programetv.ro" lang="ro" xmltv_id="" site_id="antena-3-cnn">Antena 3 CNN</channel>
  <channel site="programetv.ro" lang="ro" xmltv_id="" site_id="antena-3-cnn-hd">Antena 3 CNN HD</channel>
</channels>
""",
                encoding="utf-8",
            )

            override_dir = root / "overrides" / "programetv.ro"
            override_dir.mkdir(parents=True)
            (override_dir / "programetv.ro.tomas.channels.xml").write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
<channels>
  <channel site="programetv.ro" lang="ro" xmltv_id="Antena3CNN.ro" site_id="antena-3-cnn">Antena 3 CNN</channel>
</channels>
""",
                encoding="utf-8",
            )

            output = root / "channels.xml"
            report = prepare_epg_channels(
                playlist_path=playlist,
                epg_root=root / "epg",
                sites=["programetv.ro"],
                output_path=output,
                report_path=root / "coverage.json",
                site_override_root=root / "overrides",
            )

            self.assertEqual(report["matched_tvg_ids"], 1)
            self.assertEqual(report["match_types"], {"exact": 1})
            item = report["matched"][0]
            self.assertEqual(item["provider"], "programetv.ro")
            self.assertEqual(item["provider_xmltv_id"], "Antena3CNN.ro")
            self.assertEqual(item["provider_name"], "Antena 3 CNN")

            channel = ET.parse(output).getroot().find("channel")
            self.assertIsNotNone(channel)
            self.assertEqual(channel.get("xmltv_id"), "Antena3CNN.ro")
            self.assertEqual(channel.get("site_id"), "antena-3-cnn")

    def test_pinned_upstream_exact_mapping_keeps_priority(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            playlist = root / "ro.m3u"
            playlist.write_text(
                "#EXTM3U\n"
                '#EXTINF:-1 tvg-id="Example.ro@SD",Example\n'
                "https://example.test/example\n",
                encoding="utf-8",
            )

            provider_dir = root / "epg" / "sites" / "programetv.ro"
            provider_dir.mkdir(parents=True)
            (provider_dir / "programetv.ro.channels.xml").write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
<channels>
  <channel site="programetv.ro" lang="ro" xmltv_id="Example.ro@SD" site_id="upstream">Example</channel>
</channels>
""",
                encoding="utf-8",
            )

            override_dir = root / "overrides" / "programetv.ro"
            override_dir.mkdir(parents=True)
            (override_dir / "programetv.ro.tomas.channels.xml").write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
<channels>
  <channel site="programetv.ro" lang="ro" xmltv_id="Example.ro@SD" site_id="override">Example</channel>
</channels>
""",
                encoding="utf-8",
            )

            output = root / "channels.xml"
            prepare_epg_channels(
                playlist_path=playlist,
                epg_root=root / "epg",
                sites=["programetv.ro"],
                output_path=output,
                report_path=root / "coverage.json",
                site_override_root=root / "overrides",
            )

            channel = ET.parse(output).getroot().find("channel")
            self.assertIsNotNone(channel)
            self.assertEqual(channel.get("site_id"), "upstream")


if __name__ == "__main__":
    unittest.main()
