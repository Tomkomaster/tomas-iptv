from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "build-and-publish.yml"


class EpgBuilderPinTests(unittest.TestCase):
    def test_epg_builder_uses_full_commit_sha(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        match = re.search(
            r'IPTV_ORG_EPG_REV:\s*["\']?([0-9a-f]{40})["\']?',
            text,
        )
        self.assertIsNotNone(match)

    def test_epg_builder_does_not_clone_moving_master(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertNotIn("--branch master", text)
        self.assertIn('git -C .epg-builder fetch --depth 1 origin "$IPTV_ORG_EPG_REV"', text)
        self.assertIn('git -C .epg-builder checkout --detach FETCH_HEAD', text)

    def test_checked_out_revision_is_verified(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn('git -C .epg-builder rev-parse HEAD', text)
        self.assertIn('EPG_ACTUAL_REV', text)
        self.assertIn('IPTV_ORG_EPG_REV', text)


if __name__ == "__main__":
    unittest.main()
