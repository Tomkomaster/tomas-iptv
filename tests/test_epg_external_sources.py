import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

from epg_external_sources import _load_xml, prepare_external_guide


class EpgExternalSourcesTests(unittest.TestCase):
    def write_guide(self, path: Path, channels: list[tuple[str, str, str]]) -> None:
        root = ET.Element("tv")
        for channel_id, name, title in channels:
            channel = ET.SubElement(root, "channel", {"id": channel_id})
            ET.SubElement(channel, "display-name").text = name
            programme = ET.SubElement(
                root,
                "programme",
                {
                    "start": "20260814060000 +0200",
                    "stop": "20260814070000 +0200",
                    "channel": channel_id,
                },
            )
            ET.SubElement(programme, "title").text = title
        path.write_bytes(ET.tostring(root, encoding="utf-8", xml_declaration=True))

    def test_fallback_adds_unique_channels_without_overriding_primary(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            primary = root / "RO.xml"
            fallback = root / "RO.fallback1.xml.gz"
            self.write_guide(
                primary,
                [("RO1.KanalD", "Kanal D", "Primary Kanal D")],
            )
            self.write_guide(
                fallback,
                [
                    ("RO2.KanalD", "Kanal D (HD)", "Fallback duplicate"),
                    ("RO2.KanalD2", "Kanal D2 (HD)", "Kanal D2 programme"),
                    ("RO2.AXNWhite", "AXN White", "AXN White programme"),
                ],
            )

            combined_path, stats = prepare_external_guide(
                primary_path=primary,
                external_dir=root,
                country_code="RO",
                external_cfg={
                    "fallback_urls": ["https://example.test/RO2.xml.gz"],
                },
            )

            self.assertIsNotNone(combined_path)
            guide = _load_xml(combined_path)
            ids = {channel.get("id") for channel in guide.findall("channel")}
            self.assertEqual(ids, {"RO1.KanalD", "RO2.KanalD2", "RO2.AXNWhite"})
            self.assertEqual(stats["fallback_sources_available"], 1)
            self.assertEqual(stats["fallback_channels_added"], 2)
            self.assertEqual(stats["fallback_programmes_added"], 2)

    def test_project_config_declares_romanian_ro2_fallback(self):
        config_path = Path("config.json")
        if not config_path.is_file():
            self.skipTest("project config not present in isolated helper test")
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
        external = cfg["epg"]["countries"]["RO"]["external"]
        self.assertIn(
            "https://epgshare01.online/epgshare01/epg_ripper_RO2.xml.gz",
            external["fallback_urls"],
        )


if __name__ == "__main__":
    unittest.main()
