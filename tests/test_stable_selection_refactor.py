import unittest
from pathlib import Path
import build
from iptv import stable_selection

class StableSelectionRefactorTests(unittest.TestCase):
    def test_block_reason_is_owned_by_module(self):
        self.assertIs(build.stable_block_reason, stable_selection.stable_block_reason)
        self.assertNotIn("def stable_block_reason(", Path("iptv/build_core.py").read_text(encoding="utf-8"))

    def test_core_keeps_only_compatibility_wrapper(self):
        text=Path("iptv/build_core.py").read_text(encoding="utf-8")
        self.assertEqual(text.count("def select_stable_playlist_candidates("),1)
        self.assertIn("score_quality=score_feed_quality",text)
        self.assertIn("build_quality_context=build_feed_quality_context",text)

    def test_live_score_monkeypatch_reaches_extracted_selector(self):
        old=build.score_feed_quality
        calls=[]
        def fake(entry,cfg,context=None):
            calls.append(entry.get("url")); return {"score":1,"summary":"fake"}
        try:
            build.score_feed_quality=fake
            rows=[{"stream_url":"https://example.test/a.m3u8","decision":"Verified","exclude_from_playlist":False,"vlc":"works","samsung":"works"}]
            entries=[{"url":"https://example.test/a.m3u8","channel_name":"A","country_code":"HU","channel_key":"HU:id:a","source_flags":[]}]
            cfg={"country_outputs":{"HU":"hu.m3u"},"stable_playlist":{"allowed_decisions":["Verified"]}}
            selected,_=build.select_stable_playlist_candidates(entries,rows,cfg)
            self.assertEqual(len(selected),1)
            self.assertEqual(calls,["https://example.test/a.m3u8"])
        finally:
            build.score_feed_quality=old

if __name__ == "__main__": unittest.main()
