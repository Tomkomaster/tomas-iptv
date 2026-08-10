import tempfile
import unittest
import xml.etree.ElementTree as ET

from pathlib import Path

import epg_prepare


class EpgPrepareTests(
    unittest.TestCase
):

    def test_custom_epg_mapping(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            playlist = (
                root
                / "tv.m3u"
            )

            playlist.write_text(
                "\n".join([
                    "#EXTM3U",
                    (
                        '#EXTINF:-1 '
                        'tvg-id="M1.hu@HD",'
                        "M1"
                    ),
                    "https://example.test/m1",
                    (
                        '#EXTINF:-1 '
                        'tvg-id="ATV.hu@SD",'
                        "ATV"
                    ),
                    "https://example.test/atv",
                    (
                        '#EXTINF:-1 '
                        'tvg-id="Unknown.hu@SD",'
                        "Unknown"
                    ),
                    "https://example.test/unknown",
                    "",
                ]),
                encoding="utf-8",
            )

            official_dir = (
                root
                / "epg"
                / "sites"
                / "official.test"
            )

            official_dir.mkdir(
                parents=True
            )

            (
                official_dir
                / "official.test.channels.xml"
            ).write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
<channels>
  <channel site="official.test" lang="hu" xmltv_id="M1.hu@SD" site_id="1">M1</channel>
</channels>
""",
                encoding="utf-8",
            )

            broad_dir = (
                root
                / "epg"
                / "sites"
                / "broad.test"
            )

            broad_dir.mkdir(
                parents=True
            )

            (
                broad_dir
                / "broad.test.channels.xml"
            ).write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
<channels>
  <channel site="broad.test" lang="hu" xmltv_id="M1.hu@SD" site_id="m1">M1 alternate</channel>
  <channel site="broad.test" lang="hu" xmltv_id="ATV.hu@SD" site_id="atv">ATV</channel>
</channels>
""",
                encoding="utf-8",
            )

            output = (
                root
                / "channels.xml"
            )

            report_path = (
                root
                / "coverage.json"
            )

            report = (
                epg_prepare
                .prepare_epg_channels(
                    playlist_path=playlist,
                    epg_root=(
                        root
                        / "epg"
                    ),
                    sites=[
                        "official.test",
                        "broad.test",
                    ],
                    output_path=output,
                    report_path=(
                        report_path
                    ),
                )
            )

            tree = ET.parse(
                output
            )

            channels = (
                tree.getroot()
                .findall("channel")
            )

            self.assertEqual(
                [
                    channel.get(
                        "xmltv_id"
                    )
                    for channel
                    in channels
                ],
                [
                    "M1.hu@HD",
                    "ATV.hu@SD",
                ],
            )

            # M1 @HD should be matched to the
            # official provider's @SD schedule.
            self.assertEqual(
                channels[0].get(
                    "site"
                ),
                "official.test",
            )

            self.assertEqual(
                channels[0].get(
                    "site_id"
                ),
                "1",
            )

            # ATV should come from the broader
            # fallback provider.
            self.assertEqual(
                channels[1].get(
                    "site"
                ),
                "broad.test",
            )

            self.assertEqual(
                report[
                    "playlist_tvg_ids"
                ],
                3,
            )

            self.assertEqual(
                report[
                    "matched_tvg_ids"
                ],
                2,
            )

            self.assertEqual(
                report[
                    "unmatched_tvg_ids"
                ],
                [
                    "Unknown.hu@SD"
                ],
            )

            self.assertTrue(
                report_path.is_file()
            )


if __name__ == "__main__":
    unittest.main()
