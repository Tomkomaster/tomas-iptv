#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import socket
import ssl
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse


ATTR_RE = re.compile(r'([A-Za-z0-9_-]+)="([^"]*)"')
STATUS_PREFIX_RE = re.compile(
    r"^\[(?P<country>[A-Z]{2,3})\s+(?P<status>OK|TV|PC|\?|X)\]\s*",
    re.IGNORECASE,
)
FEED_SUFFIX_RE = re.compile(r"\s+\[Feed\s+\d+/\d+\]\s*$", re.IGNORECASE)
URI_ATTR_RE = re.compile(r'(?:^|,)URI="([^"]+)"', re.IGNORECASE)

SUCCESS_STATUSES = {
    "Online",
    "Redirected",
    "Slow startup",
    "TLS certificate warning",
}
FAILURE_STATUSES = {
    "HTTP error",
    "Manifest unavailable",
    "No playable segments",
    "Timeout",
}


class ProbeFailure(RuntimeError):
    def __init__(
        self,
        status: str,
        detail: str,
        *,
        http_status: int | None = None,
    ) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.http_status = http_status


def canonical_stream_url(url: str) -> str:
    value = (url or "").strip()
    if not value:
        return ""

    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc or parsed.hostname is None:
        return value

    scheme = parsed.scheme.lower()
    hostname = parsed.hostname.lower()
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"

    try:
        port = parsed.port
    except ValueError:
        return value

    if (scheme == "https" and port == 443) or (scheme == "http" and port == 80):
        port = None

    userinfo = ""
    if "@" in parsed.netloc:
        userinfo = parsed.netloc.rsplit("@", 1)[0] + "@"

    netloc = f"{userinfo}{hostname}"
    if port is not None:
        netloc += f":{port}"

    return urlunparse((
        scheme,
        netloc,
        parsed.path or "/",
        parsed.params,
        parsed.query,
        "",
    ))


def split_extinf(line: str) -> tuple[str, str]:
    in_quotes = False
    for index, char in enumerate(line):
        if char == '"':
            in_quotes = not in_quotes
        elif char == "," and not in_quotes:
            return line[:index], line[index + 1 :].strip()
    return line, ""


def manual_status_from_name(display_name: str) -> tuple[str, str]:
    value = (display_name or "").strip()
    match = STATUS_PREFIX_RE.match(value)
    token = ""
    if match:
        token = match.group("status").upper()
        value = value[match.end() :].strip()

    value = FEED_SUFFIX_RE.sub("", value).strip()

    labels = {
        "OK": "Samsung + VLC",
        "TV": "Samsung",
        "PC": "VLC only",
        "?": "Needs review",
        "X": "Rejected",
    }
    return value or display_name or "Unnamed channel", labels.get(token, "Unknown")


def read_playlist(path: Path) -> list[dict]:
    rows: list[dict] = []
    pending: dict | None = None

    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line:
            continue

        if line.startswith("#EXTINF:"):
            metadata, display_name = split_extinf(line)
            attrs = {key.lower(): value for key, value in ATTR_RE.findall(metadata)}
            channel, manual_status = manual_status_from_name(
                display_name or attrs.get("tvg-name", "")
            )
            pending = {
                "channel": channel,
                "playlist_name": display_name,
                "manual_status": manual_status,
                "tvg_id": attrs.get("tvg-id", ""),
                "group_title": attrs.get("group-title", ""),
                "stream_url": "",
            }
            continue

        if pending is not None and not line.startswith("#"):
            pending["stream_url"] = line
            rows.append(pending)
            pending = None

    return [row for row in rows if row.get("stream_url")]


def timeout_like(exc: BaseException) -> bool:
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return True
    if isinstance(exc, urllib.error.URLError):
        return isinstance(exc.reason, (socket.timeout, TimeoutError))
    return False


def certificate_verification_error_like(exc: BaseException) -> bool:
    """Return True only for TLS certificate-validation failures.

    urllib normally wraps SSL exceptions in URLError. Walk that wrapper and
    chained exceptions so certificate failures can be distinguished from
    other TLS/network errors without broadly disabling verification.
    """
    current: BaseException | None = exc
    seen: set[int] = set()

    while current is not None and id(current) not in seen:
        seen.add(id(current))

        if isinstance(current, (ssl.SSLCertVerificationError, ssl.CertificateError)):
            return True

        if isinstance(current, ssl.SSLError):
            text = str(current).casefold()
            if (
                "certificate_verify_failed" in text
                or "certificate verify failed" in text
            ):
                return True

        if isinstance(current, urllib.error.URLError):
            reason = current.reason
            if isinstance(reason, BaseException):
                current = reason
                continue

        current = current.__cause__ or current.__context__

    return False


def unverified_tls_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def probe_failure_for_exception(url: str, exc: BaseException) -> ProbeFailure:
    if isinstance(exc, urllib.error.HTTPError):
        return ProbeFailure(
            "HTTP error",
            f"HTTP {exc.code} for {url}",
            http_status=int(exc.code),
        )
    if timeout_like(exc):
        return ProbeFailure("Timeout", f"Timed out requesting {url}")
    return ProbeFailure("HTTP error", f"Request failed for {url}: {exc}")


def request_bytes(
    url: str,
    *,
    timeout: float,
    max_bytes: int,
    range_request: bool = False,
) -> dict:
    headers = {
        "User-Agent": "Mozilla/5.0 Tomas-IPTV-Healthcheck/1.0",
        "Accept": "application/vnd.apple.mpegurl, application/x-mpegURL, video/*, audio/*, */*",
        "Cache-Control": "no-cache",
        "Connection": "close",
    }
    if range_request:
        headers["Range"] = f"bytes=0-{max(max_bytes - 1, 0)}"

    def fetch_once(context: ssl.SSLContext | None = None) -> dict:
        request = urllib.request.Request(url, headers=headers, method="GET")
        started = time.monotonic()
        kwargs = {"timeout": timeout}
        if context is not None:
            kwargs["context"] = context

        with urllib.request.urlopen(request, **kwargs) as response:
            data = response.read(max_bytes)
            elapsed = time.monotonic() - started
            return {
                "data": data,
                "final_url": response.geturl(),
                "status": int(getattr(response, "status", 200) or 200),
                "content_type": str(response.headers.get("Content-Type") or ""),
                "elapsed": elapsed,
                "request_count": 1,
                "tls_certificate_warning": False,
                "tls_certificate_detail": "",
            }

    try:
        return fetch_once()
    except Exception as exc:
        if certificate_verification_error_like(exc):
            tls_detail = f"TLS certificate verification failed for {url}: {exc}"
            try:
                retried = fetch_once(unverified_tls_context())
            except Exception as retry_exc:
                failure = probe_failure_for_exception(url, retry_exc)
                failure.detail = (
                    f"{failure.detail} Advisory retry without TLS certificate "
                    f"verification also failed after: {exc}"
                )
                raise failure from retry_exc

            retried["request_count"] = 2
            retried["tls_certificate_warning"] = True
            retried["tls_certificate_detail"] = tls_detail
            return retried

        raise probe_failure_for_exception(url, exc) from exc


def decode_manifest(data: bytes) -> str:
    return data.decode("utf-8-sig", errors="replace")


def looks_like_hls(url: str, data: bytes, content_type: str) -> bool:
    path = urlparse(url).path.casefold()
    if path.endswith(".m3u8"):
        return True
    lowered_type = (content_type or "").casefold()
    if "mpegurl" in lowered_type or "m3u" in lowered_type:
        return True
    return decode_manifest(data).lstrip().startswith("#EXTM3U")


def manifest_uris(text: str) -> tuple[list[str], list[str]]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    variants: list[str] = []
    segments: list[str] = []

    expect_variant = False
    for line in lines:
        upper = line.upper()
        if upper.startswith("#EXT-X-STREAM-INF:"):
            expect_variant = True
            continue

        if expect_variant:
            if not line.startswith("#"):
                variants.append(line)
                expect_variant = False
                continue
            if upper.startswith("#EXT-X-STREAM-INF:"):
                continue

        if upper.startswith("#EXT-X-PART:"):
            match = URI_ATTR_RE.search(line.split(":", 1)[-1])
            if match:
                segments.append(match.group(1))
            continue

        if not line.startswith("#"):
            segments.append(line)

    return variants, segments


def is_html_payload(data: bytes) -> bool:
    prefix = data[:256].lstrip().lower()
    return prefix.startswith(b"<!doctype html") or prefix.startswith(b"<html")


def probe_hls(
    url: str,
    first_response: dict,
    *,
    timeout: float,
    max_segment_tries: int,
) -> dict:
    request_count = int(first_response.get("request_count") or 1)
    redirected = first_response["final_url"] != url
    tls_certificate_warning = bool(first_response.get("tls_certificate_warning"))
    tls_certificate_detail = str(first_response.get("tls_certificate_detail") or "")
    manifest_url = first_response["final_url"]
    manifest_text = decode_manifest(first_response["data"])

    if not manifest_text.lstrip().startswith("#EXTM3U"):
        raise ProbeFailure(
            "Manifest unavailable",
            "Response did not contain an HLS #EXTM3U manifest.",
        )

    # Follow master playlists until a media playlist is reached.
    for _depth in range(3):
        variants, segments = manifest_uris(manifest_text)
        if segments:
            break
        if not variants:
            raise ProbeFailure(
                "No playable segments",
                "HLS manifest contained no media segments or variant playlists.",
            )

        variant_errors: list[str] = []
        next_manifest = None
        for variant in variants[:4]:
            variant_url = urljoin(manifest_url, variant)
            try:
                response = request_bytes(
                    variant_url,
                    timeout=timeout,
                    max_bytes=512 * 1024,
                )
                request_count += int(response.get("request_count") or 1)
                if response.get("tls_certificate_warning"):
                    tls_certificate_warning = True
                    tls_certificate_detail = (
                        tls_certificate_detail
                        or str(response.get("tls_certificate_detail") or "")
                    )
                candidate = decode_manifest(response["data"])
                if candidate.lstrip().startswith("#EXTM3U"):
                    redirected = redirected or response["final_url"] != variant_url
                    next_manifest = (response["final_url"], candidate)
                    break
                variant_errors.append(f"{variant_url}: not an HLS manifest")
            except ProbeFailure as exc:
                variant_errors.append(exc.detail)

        if next_manifest is None:
            raise ProbeFailure(
                "Manifest unavailable",
                "No master-playlist variant could be loaded: "
                + "; ".join(variant_errors[:3]),
            )

        manifest_url, manifest_text = next_manifest
    else:
        raise ProbeFailure(
            "Manifest unavailable",
            "HLS master playlist nesting exceeded the supported depth.",
        )

    _variants, segments = manifest_uris(manifest_text)
    if not segments:
        raise ProbeFailure(
            "No playable segments",
            "HLS media playlist contained no segment URIs.",
        )

    failures: list[str] = []
    tried = 0
    # Prefer the newest live segments; older live-window segments expire first.
    for segment in reversed(segments):
        if tried >= max(1, max_segment_tries):
            break
        tried += 1
        segment_url = urljoin(manifest_url, segment)
        try:
            response = request_bytes(
                segment_url,
                timeout=timeout,
                max_bytes=64 * 1024,
                range_request=True,
            )
            request_count += int(response.get("request_count") or 1)
            if response.get("tls_certificate_warning"):
                tls_certificate_warning = True
                tls_certificate_detail = (
                    tls_certificate_detail
                    or str(response.get("tls_certificate_detail") or "")
                )
            redirected = redirected or response["final_url"] != segment_url
            if response["data"] and not is_html_payload(response["data"]):
                return {
                    "playable": True,
                    "redirected": redirected,
                    "request_count": request_count,
                    "probe_type": "HLS",
                    "detail": "HLS manifest and media segment loaded successfully.",
                    "final_url": first_response["final_url"],
                    "http_status": first_response["status"],
                    "tls_certificate_warning": tls_certificate_warning,
                    "tls_certificate_detail": tls_certificate_detail,
                }
            failures.append(f"{segment_url}: empty/HTML payload")
        except ProbeFailure as exc:
            if exc.status == "Timeout":
                failures.append(f"{segment_url}: timeout")
            else:
                failures.append(exc.detail)

    raise ProbeFailure(
        "No playable segments",
        "HLS manifest loaded, but no tested media segment returned playable bytes: "
        + "; ".join(failures[:3]),
    )


def probe_stream(
    entry: dict,
    *,
    timeout: float = 8.0,
    slow_start_seconds: float = 6.0,
    max_segment_tries: int = 2,
) -> dict:
    url = str(entry.get("stream_url") or "").strip()
    started = time.monotonic()

    try:
        first = request_bytes(
            url,
            timeout=timeout,
            max_bytes=512 * 1024,
        )

        if not first["data"]:
            raise ProbeFailure("HTTP error", "Initial request returned no bytes.")

        if looks_like_hls(url, first["data"], first["content_type"]):
            result = probe_hls(
                url,
                first,
                timeout=timeout,
                max_segment_tries=max_segment_tries,
            )
        else:
            result = {
                "playable": True,
                "redirected": first["final_url"] != url,
                "request_count": int(first.get("request_count") or 1),
                "probe_type": "Direct",
                "detail": "Direct stream returned bytes successfully.",
                "final_url": first["final_url"],
                "http_status": first["status"],
                "tls_certificate_warning": bool(first.get("tls_certificate_warning")),
                "tls_certificate_detail": str(first.get("tls_certificate_detail") or ""),
            }

        startup_seconds = round(time.monotonic() - started, 3)
        if result.get("tls_certificate_warning"):
            status = "TLS certificate warning"
            tls_detail = str(result.get("tls_certificate_detail") or "").strip()
            playable_detail = str(result.get("detail") or "").strip()
            result["detail"] = (
                "Playable after an advisory retry without TLS certificate "
                "verification. "
                + playable_detail
                + (f" Original TLS error: {tls_detail}" if tls_detail else "")
            ).strip()
        elif startup_seconds >= slow_start_seconds:
            status = "Slow startup"
        elif result["redirected"]:
            status = "Redirected"
        else:
            status = "Online"

        result.update({
            "status": status,
            "success": True,
            "startup_seconds": startup_seconds,
        })
        return result

    except ProbeFailure as exc:
        return {
            "status": exc.status,
            "success": False,
            "startup_seconds": round(time.monotonic() - started, 3),
            "redirected": False,
            "request_count": 0,
            "probe_type": "HLS" if urlparse(url).path.casefold().endswith(".m3u8") else "Unknown",
            "detail": exc.detail,
            "final_url": url,
            "http_status": exc.http_status,
            "tls_certificate_warning": False,
            "tls_certificate_detail": "",
        }


def load_json_url(url: str, timeout: float = 5.0) -> dict | None:
    if not url:
        return None
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 Tomas-IPTV-Healthcheck/1.0",
            "Cache-Control": "no-cache",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8-sig"))
    except Exception as exc:
        print(f"WARNING: previous health state unavailable: {exc}")
        return None


def previous_by_url(previous: dict | None) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for item in (previous or {}).get("streams", []) or []:
        if not isinstance(item, dict):
            continue
        url = canonical_stream_url(str(item.get("stream_url") or ""))
        if url:
            result[url] = item
    return result


def apply_history(
    entry: dict,
    probe: dict,
    previous: dict | None,
    checked_at: str,
) -> dict:
    prior_failures = int((previous or {}).get("consecutive_failures") or 0)
    success = bool(probe.get("success"))
    previous_checked_at = str((previous or {}).get("checked_at") or "")
    same_check_day = (
        len(previous_checked_at) >= 10
        and len(checked_at) >= 10
        and previous_checked_at[:10] == checked_at[:10]
    )

    if success:
        consecutive_failures = 0
    elif same_check_day:
        # A normal build can run several times after code changes. Do not
        # turn several same-day builds into several "nightly" failures.
        consecutive_failures = max(prior_failures, 1)
    else:
        consecutive_failures = prior_failures + 1

    if success:
        attention = "healthy" if probe.get("status") == "Online" else "warning"
    elif consecutive_failures >= 3:
        attention = "needs_manual_retest"
    else:
        attention = "warning"

    return {
        "channel": entry.get("channel", ""),
        "playlist_name": entry.get("playlist_name", ""),
        "tvg_id": entry.get("tvg_id", ""),
        "group_title": entry.get("group_title", ""),
        "stream_url": entry.get("stream_url", ""),
        "manual_status": entry.get("manual_status", "Unknown"),
        "status": probe.get("status", "HTTP error"),
        "success": success,
        "attention": attention,
        "consecutive_failures": consecutive_failures,
        "manual_retest_recommended": consecutive_failures >= 3,
        "startup_seconds": probe.get("startup_seconds"),
        "probe_type": probe.get("probe_type", "Unknown"),
        "redirected": bool(probe.get("redirected")),
        "final_url": probe.get("final_url", entry.get("stream_url", "")),
        "http_status": probe.get("http_status"),
        "request_count": int(probe.get("request_count") or 0),
        "detail": probe.get("detail", ""),
        "tls_certificate_warning": bool(probe.get("tls_certificate_warning")),
        "tls_certificate_detail": str(probe.get("tls_certificate_detail") or ""),
        "checked_at": checked_at,
        "last_success_at": (
            checked_at if success else (previous or {}).get("last_success_at")
        ),
        "last_failure_at": (
            checked_at if not success else (previous or {}).get("last_failure_at")
        ),
    }


def build_report(
    playlist: Path,
    *,
    previous: dict | None = None,
    workers: int = 8,
    timeout: float = 8.0,
    slow_start_seconds: float = 6.0,
    max_segment_tries: int = 2,
    limit: int = 0,
) -> dict:
    entries = read_playlist(playlist)
    if limit > 0:
        entries = entries[:limit]

    checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    prior_index = previous_by_url(previous)
    results: list[dict | None] = [None] * len(entries)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {
            executor.submit(
                probe_stream,
                entry,
                timeout=timeout,
                slow_start_seconds=slow_start_seconds,
                max_segment_tries=max_segment_tries,
            ): index
            for index, entry in enumerate(entries)
        }

        for future in as_completed(futures):
            index = futures[future]
            entry = entries[index]
            try:
                probe = future.result()
            except Exception as exc:
                probe = {
                    "status": "HTTP error",
                    "success": False,
                    "startup_seconds": None,
                    "probe_type": "Unknown",
                    "redirected": False,
                    "final_url": entry.get("stream_url", ""),
                    "http_status": None,
                    "request_count": 0,
                    "detail": f"Unexpected checker error: {exc}",
                    "tls_certificate_warning": False,
                    "tls_certificate_detail": "",
                }

            prior = prior_index.get(
                canonical_stream_url(str(entry.get("stream_url") or ""))
            )
            results[index] = apply_history(entry, probe, prior, checked_at)

    streams = [item for item in results if item is not None]
    status_counts = Counter(item["status"] for item in streams)
    failed = sum(1 for item in streams if not item["success"])
    playable = len(streams) - failed
    manual_retest = sum(1 for item in streams if item["manual_retest_recommended"])
    warnings = sum(1 for item in streams if item["attention"] == "warning")

    return {
        "schema_version": 1,
        "generated_at": checked_at,
        "advisory_only": True,
        "manual_testing_authority": (
            "Automated results never replace VLC + Samsung verification and never "
            "change audit.json or stable-playlist decisions automatically."
        ),
        "policy": {
            "failure_1": "warning",
            "failure_2": "warning",
            "failure_3_plus": "needs manual retest",
            "automatic_rejection": False,
            "tls_certificate_retry": (
                "Certificate-verification failures may be retried without certificate "
                "verification only to classify advisory playability; a successful retry "
                "is reported as TLS certificate warning and is never manual verification."
            ),
        },
        "settings": {
            "workers": max(1, workers),
            "timeout_seconds": timeout,
            "slow_start_seconds": slow_start_seconds,
            "max_segment_tries": max_segment_tries,
        },
        "summary": {
            "total": len(streams),
            "playable": playable,
            "failed": failed,
            "warnings": warnings,
            "needs_manual_retest": manual_retest,
            "status_counts": dict(sorted(status_counts.items())),
        },
        "streams": streams,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Advisory health checker for stable IPTV streams. HLS checks fetch "
            "the manifest, resolve a media playlist, and read bytes from a real segment."
        )
    )
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    parser.add_argument("--playlist", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--previous-url")
    parser.add_argument("--workers", type=int)
    parser.add_argument("--timeout", type=float)
    parser.add_argument("--slow-start", type=float)
    parser.add_argument("--max-segment-tries", type=int)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--no-previous", action="store_true")
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    health_cfg = config.get("health") or {}

    if health_cfg.get("enabled") is False:
        print("Automated stream health checking is disabled in config.json.")
        return

    playlist = args.playlist or Path(
        str(config.get("output") or "public/tv.m3u")
    )
    output = args.output or Path(
        str(health_cfg.get("output") or "public/health.json")
    )
    previous_url = (
        args.previous_url
        if args.previous_url is not None
        else str(health_cfg.get("previous_url") or "")
    )
    workers = args.workers or int(health_cfg.get("workers") or 8)
    timeout = args.timeout or float(health_cfg.get("timeout_seconds") or 8)
    slow_start = args.slow_start or float(health_cfg.get("slow_start_seconds") or 6)
    max_segment_tries = args.max_segment_tries or int(
        health_cfg.get("max_segment_tries") or 2
    )

    previous = None if args.no_previous else load_json_url(previous_url)
    report = build_report(
        playlist,
        previous=previous,
        workers=workers,
        timeout=timeout,
        slow_start_seconds=slow_start,
        max_segment_tries=max_segment_tries,
        limit=max(0, args.limit),
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    summary = report["summary"]
    print(
        "Stream health: "
        f"{summary['playable']}/{summary['total']} playable, "
        f"{summary['failed']} failed, "
        f"{summary['needs_manual_retest']} need manual retest."
    )
    for status, count in summary["status_counts"].items():
        print(f"- {status}: {count}")


if __name__ == "__main__":
    main()
