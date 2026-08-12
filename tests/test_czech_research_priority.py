import json
import unittest
from pathlib import Path

from research_priority import (
    compile_research_priority_policy,
    resolve_research_priority,
)


class CzechResearchPriorityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        payload = json.loads(
            Path("research_priority.json").read_text(encoding="utf-8")
        )
        cls.policy = compile_research_priority_policy(payload)

    def assert_priority(self, channel, expected):
        result = resolve_research_priority(
            {
                "country": "CZ",
                "channel": channel,
                "tvg_id": "",
            },
            self.policy,
        )
        self.assertEqual(result["priority"], expected, channel)
        self.assertEqual(result["matched_by"], "channel", channel)

    def test_core_czech_family_channels_are_p1(self):
        for channel in [
            "ČT 1",
            "ČT 2",
            "ČT24",
            "ČT Sport",
            "Nova",
            "Prima",
            "CNN Prima News",
        ]:
            with self.subTest(channel=channel):
                self.assert_priority(channel, "P1")

    def test_major_czech_secondary_channels_are_explicit_p2(self):
        for channel in [
            "ČT:D/ČT art",
            "Nova Action",
            "Nova Cinema",
            "Nova Fun",
            "Nova Krimi",
            "Nova Lady",
            "Prima Cool",
            "Prima Krimi",
            "Prima Love",
            "Prima MAX",
            "Prima Show",
            "Prima Star",
            "Prima Zoom",
            "Televize Seznam",
            "TV Barrandov",
            "A11",
            "Warner TV",
            "BBC Earth Czechia",
            "History",
            "History2",
            "Nickelodeon",
            "Nicktoons",
            "JOJ Family",
            "AXN CEE Czech Republic",
            "AXN Black Czech Republic",
            "AXN White CzechRepublic",
            "Viasat Epic Drama",
            "Sporty TV",
            "Golf Channel",
            "CS Mystery",
        ]:
            with self.subTest(channel=channel):
                self.assert_priority(channel, "P2")

    def test_regional_czech_channel_still_uses_default_p3(self):
        result = resolve_research_priority(
            {
                "country": "CZ",
                "channel": "Praha TV",
                "tvg_id": "PrahaTV.cz@SD",
            },
            self.policy,
        )
        self.assertEqual(result["priority"], "P3")
        self.assertEqual(result["matched_by"], "default")


if __name__ == "__main__":
    unittest.main()
