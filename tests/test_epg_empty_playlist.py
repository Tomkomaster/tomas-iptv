import tempfile
import unittest
from pathlib import Path

from epg_prepare import prepare_epg_channels


class EmptyEpgPlaylistTests(unittest.TestCase):
    def test_empty_playlist_produces_zero_coverage_instead_of_failing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            playlist = root / "empty.m3u"
            playlist.write_text("#EXTM3U\n", encoding="utf-8")

            site_dir = root / "epg" / "sites" / "example.test"
            site_dir.mkdir(parents=True)
            (site_dir / "example.test.channels.xml").write_text(
                "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
                "<channels>\n"
                "<channel site=\"example.test\" lang=\"en\" "
                "xmltv_id=\"Example.test\" site_id=\"example\">Example</channel>\n"
                "</channels>\n",
                encoding="utf-8",
            )

            output = root / "channels.xml"
            report_path = root / "coverage.json"
            report = prepare_epg_channels(
                playlist_path=playlist,
                epg_root=root / "epg",
                sites=["example.test"],
                output_path=output,
                report_path=report_path,
            )

            self.assertEqual(report["playlist_tvg_ids"], 0)
            self.assertEqual(report["matched_tvg_ids"], 0)
            self.assertEqual(report["mapping_coverage_percent"], 0.0)
            self.assertTrue(output.is_file())
            self.assertTrue(report_path.is_file())


if __name__ == "__main__":
    unittest.main()
