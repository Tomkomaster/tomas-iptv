import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from healthcheck import (
    apply_history,
    build_report,
    probe_stream,
    read_playlist,
)


class HealthHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def do_GET(self):
        if self.path == "/media.m3u8":
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.apple.mpegurl")
            self.end_headers()
            self.wfile.write(
                b"#EXTM3U\n#EXT-X-TARGETDURATION:6\n#EXTINF:6,\nseg.ts\n"
            )
            return

        if self.path == "/master.m3u8":
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.apple.mpegurl")
            self.end_headers()
            self.wfile.write(
                b"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000000\nvariant.m3u8\n"
            )
            return

        if self.path == "/variant.m3u8":
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.apple.mpegurl")
            self.end_headers()
            self.wfile.write(
                b"#EXTM3U\n#EXT-X-TARGETDURATION:6\n#EXTINF:6,\nseg.ts\n"
            )
            return

        if self.path == "/empty.m3u8":
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.apple.mpegurl")
            self.end_headers()
            self.wfile.write(b"#EXTM3U\n#EXT-X-TARGETDURATION:6\n")
            return

        if self.path == "/redirect.m3u8":
            self.send_response(302)
            self.send_header("Location", "/media.m3u8")
            self.end_headers()
            return

        if self.path == "/slow.m3u8":
            time.sleep(0.05)
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.apple.mpegurl")
            self.end_headers()
            self.wfile.write(
                b"#EXTM3U\n#EXT-X-TARGETDURATION:6\n#EXTINF:6,\nseg.ts\n"
            )
            return

        if self.path == "/direct.bin":
            self.send_response(200)
            self.send_header("Content-Type", "video/mp2t")
            self.end_headers()
            self.wfile.write(b"A" * 4096)
            return

        if self.path == "/seg.ts":
            self.send_response(206 if self.headers.get("Range") else 200)
            self.send_header("Content-Type", "video/mp2t")
            self.end_headers()
            self.wfile.write(b"G" * 8192)
            return

        self.send_response(404)
        self.end_headers()


class HealthcheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), HealthHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        host, port = cls.server.server_address
        cls.base = f"http://{host}:{port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def entry(self, path):
        return {
            "channel": "Example",
            "playlist_name": "[HU OK] Example",
            "manual_status": "Samsung + VLC",
            "tvg_id": "Example.hu@SD",
            "group_title": "Hungary | General",
            "stream_url": self.base + path,
        }

    def test_media_playlist_fetches_real_segment(self):
        result = probe_stream(self.entry("/media.m3u8"), timeout=1, slow_start_seconds=1)
        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "Online")
        self.assertEqual(result["probe_type"], "HLS")
        self.assertGreaterEqual(result["request_count"], 2)

    def test_master_playlist_resolves_variant_and_segment(self):
        result = probe_stream(self.entry("/master.m3u8"), timeout=1, slow_start_seconds=1)
        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "Online")
        self.assertGreaterEqual(result["request_count"], 3)

    def test_redirect_is_playable_warning_not_failure(self):
        result = probe_stream(self.entry("/redirect.m3u8"), timeout=1, slow_start_seconds=1)
        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "Redirected")
        self.assertTrue(result["redirected"])

    def test_slow_startup_is_playable_warning_not_failure(self):
        result = probe_stream(self.entry("/slow.m3u8"), timeout=1, slow_start_seconds=0.01)
        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "Slow startup")

    def test_empty_hls_manifest_reports_no_segments(self):
        result = probe_stream(self.entry("/empty.m3u8"), timeout=1, slow_start_seconds=1)
        self.assertFalse(result["success"])
        self.assertEqual(result["status"], "No playable segments")

    def test_direct_stream_only_needs_bytes(self):
        result = probe_stream(self.entry("/direct.bin"), timeout=1, slow_start_seconds=1)
        self.assertTrue(result["success"])
        self.assertEqual(result["probe_type"], "Direct")

    def test_three_failures_recommend_manual_retest_and_success_resets(self):
        entry = self.entry("/missing.m3u8")
        failed_probe = {
            "status": "HTTP error",
            "success": False,
            "startup_seconds": 0.1,
            "probe_type": "HLS",
            "redirected": False,
            "final_url": entry["stream_url"],
            "http_status": 404,
            "request_count": 0,
            "detail": "HTTP 404",
        }
        previous = {"consecutive_failures": 2, "last_success_at": "earlier"}
        failed = apply_history(entry, failed_probe, previous, "now")
        self.assertEqual(failed["consecutive_failures"], 3)
        self.assertTrue(failed["manual_retest_recommended"])
        self.assertEqual(failed["attention"], "needs_manual_retest")

        success_probe = dict(failed_probe)
        success_probe.update({"status": "Online", "success": True})
        recovered = apply_history(entry, success_probe, failed, "later")
        self.assertEqual(recovered["consecutive_failures"], 0)
        self.assertFalse(recovered["manual_retest_recommended"])

    def test_playlist_manual_status_and_report_summary(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            playlist = Path(temp_dir) / "tv.m3u"
            playlist.write_text(
                "#EXTM3U\n"
                f'#EXTINF:-1 tvg-id="One.hu@SD" group-title="Hungary | General",[HU OK] One\n{self.base}/media.m3u8\n'
                f'#EXTINF:-1 tvg-id="Two.hu@SD" group-title="Hungary | General",[HU TV] Two\n{self.base}/empty.m3u8\n',
                encoding="utf-8",
            )

            rows = read_playlist(playlist)
            self.assertEqual(rows[0]["manual_status"], "Samsung + VLC")
            self.assertEqual(rows[1]["manual_status"], "Samsung")

            report = build_report(
                playlist,
                previous=None,
                workers=2,
                timeout=1,
                slow_start_seconds=1,
                max_segment_tries=1,
            )
            self.assertEqual(report["summary"]["total"], 2)
            self.assertEqual(report["summary"]["playable"], 1)
            self.assertEqual(report["summary"]["failed"], 1)
            self.assertFalse(report["policy"]["automatic_rejection"])


if __name__ == "__main__":
    unittest.main()
