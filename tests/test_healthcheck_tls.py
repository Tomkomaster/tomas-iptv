import ssl
import unittest
import urllib.error
from datetime import date
from unittest.mock import patch

import healthcheck
from attention import build_attention
from healthcheck import (
    ProbeFailure,
    apply_history,
    certificate_verification_error_like,
    probe_stream,
    request_bytes,
)


class FakeResponse:
    def __init__(
        self,
        data=b"payload",
        url="https://example.invalid/live",
        status=200,
        content_type="video/mp2t",
    ):
        self._data = data
        self._url = url
        self.status = status
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, max_bytes):
        return self._data[:max_bytes]

    def geturl(self):
        return self._url


class TLSHealthcheckTests(unittest.TestCase):
    def entry(self, url="https://example.invalid/live.bin"):
        return {
            "channel": "Example",
            "playlist_name": "[HU OK] Example",
            "manual_status": "Samsung + VLC",
            "tvg_id": "Example.hu@SD",
            "group_title": "Hungary | General",
            "stream_url": url,
        }

    def test_certificate_verification_detection_is_specific(self):
        cert_error = ssl.SSLCertVerificationError(
            1,
            "certificate verify failed",
        )
        self.assertTrue(certificate_verification_error_like(cert_error))
        self.assertTrue(
            certificate_verification_error_like(
                urllib.error.URLError(cert_error)
            )
        )
        self.assertFalse(
            certificate_verification_error_like(
                urllib.error.URLError(
                    ssl.SSLError("TLS handshake failed")
                )
            )
        )

    def test_request_retries_certificate_failure_without_verification(self):
        cert_error = urllib.error.URLError(
            ssl.SSLCertVerificationError(
                1,
                "certificate verify failed",
            )
        )
        response = FakeResponse()

        with patch.object(
            healthcheck.urllib.request,
            "urlopen",
            side_effect=[cert_error, response],
        ) as urlopen:
            result = request_bytes(
                "https://example.invalid/live.bin",
                timeout=1,
                max_bytes=1024,
            )

        self.assertEqual(urlopen.call_count, 2)
        self.assertTrue(result["tls_certificate_warning"])
        self.assertEqual(result["request_count"], 2)
        self.assertIn(
            "certificate verification failed",
            result["tls_certificate_detail"],
        )
        retry_context = urlopen.call_args_list[1].kwargs.get("context")
        self.assertIsInstance(retry_context, ssl.SSLContext)
        self.assertEqual(retry_context.verify_mode, ssl.CERT_NONE)
        self.assertFalse(retry_context.check_hostname)

    def test_generic_ssl_failure_is_not_retried(self):
        generic_ssl = urllib.error.URLError(
            ssl.SSLError("TLS handshake failed")
        )

        with patch.object(
            healthcheck.urllib.request,
            "urlopen",
            side_effect=generic_ssl,
        ) as urlopen:
            with self.assertRaises(ProbeFailure) as caught:
                request_bytes(
                    "https://example.invalid/live.bin",
                    timeout=1,
                    max_bytes=1024,
                )

        self.assertEqual(urlopen.call_count, 1)
        self.assertEqual(caught.exception.status, "HTTP error")

    def test_successful_tls_retry_is_playable_warning_and_resets_streak(self):
        tls_response = {
            "data": b"A" * 4096,
            "final_url": "https://example.invalid/live.bin",
            "status": 200,
            "content_type": "video/mp2t",
            "elapsed": 0.1,
            "request_count": 2,
            "tls_certificate_warning": True,
            "tls_certificate_detail": (
                "TLS certificate verification failed for test"
            ),
        }
        entry = self.entry()

        with patch.object(
            healthcheck,
            "request_bytes",
            return_value=tls_response,
        ):
            probe = probe_stream(
                entry,
                timeout=1,
                slow_start_seconds=1,
            )

        self.assertTrue(probe["success"])
        self.assertEqual(probe["status"], "TLS certificate warning")
        self.assertTrue(probe["tls_certificate_warning"])
        self.assertIn("Playable after an advisory retry", probe["detail"])

        previous = {
            "consecutive_failures": 2,
            "checked_at": "2026-08-10 04:23:00 UTC",
            "last_success_at": "2026-08-08 04:23:00 UTC",
        }
        result = apply_history(
            entry,
            probe,
            previous,
            "2026-08-11 04:23:00 UTC",
        )
        self.assertEqual(result["consecutive_failures"], 0)
        self.assertFalse(result["manual_retest_recommended"])
        self.assertEqual(result["attention"], "warning")
        self.assertTrue(result["tls_certificate_warning"])

    def test_tls_playable_warning_does_not_create_stream_failure_attention(self):
        row = {
            "channel": "Example",
            "tvg_id": "Example.hu@SD",
            "stream_url": "https://example.invalid/live.bin",
            "source": "Example source",
            "decision": "Verified",
            "tested_on": "2026-08-10",
            "in_playlist": True,
            "in_stable_playlist": True,
        }
        result = build_attention(
            {
                "generated_at": "2026-08-11 08:00:00 UTC",
                "audit": {"channels": [row]},
            },
            health={
                "streams": [
                    {
                        "channel": row["channel"],
                        "tvg_id": row["tvg_id"],
                        "stream_url": row["stream_url"],
                        "success": True,
                        "status": "TLS certificate warning",
                        "consecutive_failures": 0,
                        "manual_retest_recommended": False,
                        "detail": "Playable after advisory TLS retry.",
                    }
                ]
            },
            epg_coverage={
                "matched": [{"tvg_id": row["tvg_id"]}],
                "unmatched_tvg_ids": [],
            },
            epg_health={"mapped_without_programmes": []},
            reference_date=date(2026, 8, 11),
        )

        self.assertEqual(result["summary"]["items"], 0)
        self.assertEqual(result["status"], "healthy")


if __name__ == "__main__":
    unittest.main()
