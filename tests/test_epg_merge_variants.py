import unittest
import xml.etree.ElementTree as ET

from epg_merge import build_external_mapping


EXTERNAL_XML = """<tv>
  <channel id="National.Geographic.HD.hu">
    <display-name>National Geographic HD</display-name>
  </channel>
  <channel id="National.Geographic.hu">
    <display-name>National Geographic</display-name>
  </channel>
</tv>"""


class EpgMergeVariantTests(unittest.TestCase):
    def test_sd_playlist_prefers_non_hd_external_variant(self):
        mapping, ambiguous = build_external_mapping(
            [("NationalGeographic.hu@SD", "[HU OK] National Geographic")],
            ET.fromstring(EXTERNAL_XML),
        )

        self.assertEqual(ambiguous, [])
        self.assertIn("National.Geographic.hu", mapping)
        self.assertNotIn("National.Geographic.HD.hu", mapping)
        self.assertEqual(
            mapping["National.Geographic.hu"]["tvg_id"],
            "NationalGeographic.hu@SD",
        )

    def test_hd_playlist_prefers_hd_external_variant(self):
        mapping, ambiguous = build_external_mapping(
            [("NationalGeographic.hu@HD", "[HU OK] National Geographic HD")],
            ET.fromstring(EXTERNAL_XML),
        )

        self.assertEqual(ambiguous, [])
        self.assertIn("National.Geographic.HD.hu", mapping)
        self.assertNotIn("National.Geographic.hu", mapping)
        self.assertEqual(
            mapping["National.Geographic.HD.hu"]["tvg_id"],
            "NationalGeographic.hu@HD",
        )


if __name__ == "__main__":
    unittest.main()
