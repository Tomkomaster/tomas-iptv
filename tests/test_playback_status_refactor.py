import unittest
from pathlib import Path

import build
from iptv import playback_status


EXTRACTED_NAMES = ('normalize_test_status', 'is_tested_status')


class PlaybackStatusRefactorTests(unittest.TestCase):
    def test_build_reexports_status_api(self):
        for name in EXTRACTED_NAMES:
            self.assertIs(getattr(build, name), getattr(playback_status, name), name)

    def test_build_core_no_longer_defines_status_helpers(self):
        text = Path("iptv/build_core.py").read_text(encoding="utf-8")
        for name in EXTRACTED_NAMES:
            self.assertNotIn(f"def {name}(", text, name)

    def test_normalization_and_tested_state_match_existing_contract(self):
        self.assertEqual(playback_status.normalize_test_status("Works with warning"), "works_with_warning")
        self.assertEqual(playback_status.normalize_test_status("MRL error"), "mrl_error")
        self.assertTrue(playback_status.is_tested_status("works"))
        self.assertTrue(playback_status.is_tested_status("format_error"))
        self.assertFalse(playback_status.is_tested_status("not_tested"))
        self.assertFalse(playback_status.is_tested_status(""))


if __name__ == "__main__":
    unittest.main()
