import unittest

from health_policy import compile_health_policy, resolve_health_policy


class HealthPolicyTests(unittest.TestCase):
    def policy(self):
        return {
            "schema_version": 1,
            "default": "normal",
            "entries": [
                {
                    "name": "Event TV",
                    "tvg_id": "EventTV.hu@SD",
                    "health_policy": "event_based",
                    "reason": "Only broadcasts during events.",
                },
                {
                    "name": "URL-specific event",
                    "stream_url": "HTTPS://Example.Test:443/live.m3u8#fragment",
                    "health_policy": "event_based",
                    "reason": "Exact stream override.",
                },
            ],
        }

    def test_exact_tvg_id_match(self):
        default, indexes = compile_health_policy(self.policy())
        result = resolve_health_policy(
            {
                "channel": "Renamed Event Channel",
                "tvg_id": "eventtv.hu@sd",
                "stream_url": "https://other.test/live.m3u8",
            },
            default=default,
            indexes=indexes,
        )
        self.assertEqual(result["health_policy"], "event_based")
        self.assertEqual(result["matched_by"], "tvg_id")

    def test_stream_url_has_highest_precedence(self):
        payload = self.policy()
        payload["entries"].append(
            {
                "name": "Normal by tvg",
                "tvg_id": "Conflict.hu@SD",
                "health_policy": "normal",
            }
        )
        default, indexes = compile_health_policy(payload)
        result = resolve_health_policy(
            {
                "channel": "Conflict",
                "tvg_id": "Conflict.hu@SD",
                "stream_url": "https://example.test/live.m3u8",
            },
            default=default,
            indexes=indexes,
        )
        self.assertEqual(result["health_policy"], "event_based")
        self.assertEqual(result["matched_by"], "stream_url")

    def test_default_is_normal(self):
        default, indexes = compile_health_policy(self.policy())
        result = resolve_health_policy(
            {
                "channel": "Ordinary TV",
                "tvg_id": "Ordinary.hu@SD",
                "stream_url": "https://ordinary.test/live.m3u8",
            },
            default=default,
            indexes=indexes,
        )
        self.assertEqual(result["health_policy"], "normal")
        self.assertEqual(result["matched_by"], "default")

    def test_invalid_policy_and_duplicate_selector_are_rejected(self):
        with self.assertRaises(ValueError):
            compile_health_policy({"default": "sometimes"})

        payload = self.policy()
        payload["entries"].append(dict(payload["entries"][0]))
        with self.assertRaises(ValueError):
            compile_health_policy(payload)

        with self.assertRaises(ValueError):
            compile_health_policy(
                {
                    "entries": [
                        {
                            "channel": "Bad",
                            "tvg_id": "Bad.hu@SD",
                            "health_policy": "event_based",
                        }
                    ]
                }
            )


if __name__ == "__main__":
    unittest.main()
