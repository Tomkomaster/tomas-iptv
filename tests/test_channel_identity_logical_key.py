import unittest
from pathlib import Path

import build
from iptv import channel_identity


class LogicalChannelKeyRefactorTests(unittest.TestCase):
    def test_logical_key_is_owned_by_channel_identity(self):
        self.assertIs(build.logical_channel_key, channel_identity.logical_channel_key)
        core = Path("iptv/build_core.py").read_text(encoding="utf-8")
        self.assertNotIn("def logical_channel_key(", core)

    def test_country_scopes_same_channel_identity(self):
        entry = {"country_code": "SK", "canonical_id": "Demo.Channel"}
        self.assertEqual(
            channel_identity.logical_channel_key(entry),
            "SK:canonical:demo.channel",
        )


if __name__ == "__main__":
    unittest.main()
