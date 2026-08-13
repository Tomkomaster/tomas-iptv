import unittest
from pathlib import Path
import build
from iptv import feed_selection

class FeedSelectionRefactorTests(unittest.TestCase):
    def test_build_reexports_feed_selection(self):
        self.assertIs(build.select_playlist_candidates, feed_selection.select_playlist_candidates)
        self.assertIs(build.make_test_playlist_candidates, feed_selection.make_test_playlist_candidates)
    def test_core_no_longer_defines_selection(self):
        text=Path("iptv/build_core.py").read_text(encoding="utf-8")
        self.assertNotIn("def select_playlist_candidates(",text)
        self.assertNotIn("def make_test_playlist_candidates(",text)
    def test_test_candidates_keep_all_current_streams(self):
        rows=[{"stream_url":"https://example.test/a.m3u8","decision":"Rejected","exclude_from_playlist":True}]
        entries=[{"url":"https://example.test/a.m3u8","channel_name":"A"}]
        out=feed_selection.make_test_playlist_candidates(entries,rows)
        self.assertEqual(len(out),1)
        self.assertEqual(out[0]["_decision"],"Rejected")

if __name__ == "__main__": unittest.main()
