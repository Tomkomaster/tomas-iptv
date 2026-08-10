#!/usr/bin/env python3
from __future__ import annotations

import csv
import html
import json
import re
import sys
import unicodedata
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent

ATTR_RE = re.compile(r'([A-Za-z0-9_-]+)="([^"]*)"')
QUALITY_SUFFIX_RE = re.compile(
    r"""
    \s*
    (?:
        \((?:2160p|1440p|1080p|720p|576p|540p|480p|360p|240p|4K|UHD|FHD|HD|SD)\)
        |
        \[(?:2160p|1440p|1080p|720p|576p|540p|480p|360p|240p|4K|UHD|FHD|HD|SD)\]
        |
        \[(?:Geo[- ]?blocked|Not\s*24/7|Offline)\]
    )
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)
TVG_VARIANT_SUFFIX_RE = re.compile(r'@(SD|HD|FHD|UHD|4K|\d{3,4}P)$', re.IGNORECASE)
SOURCE_FLAG_RE = re.compile(r'\[(Geo[- ]?blocked|Not\s*24/7|Offline)\]', re.IGNORECASE)
CUSTOM_PREFIX_RE = re.compile(r'^\[[A-Z]{2,3}(?:\s+(?:OK|TV|PC|\?|X))?\]\s*', re.IGNORECASE)


def http_get_text(url: str, timeout: int = 45) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 Tomas-IPTV-Playlist-Builder/2.0",
            "Accept": "*/*",
            "Cache-Control": "no-cache",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        data = response.read()
    return data.decode("utf-8-sig", errors="replace")


def download_m3u(url: str) -> str:
    text = http_get_text(url)
    if "#EXTM3U" not in text[:1000]:
        raise RuntimeError(f"Source did not look like an M3U playlist: {url}")
    return text


def read_local(path: str) -> str:
    p = ROOT / path
    if not p.is_file():
        raise RuntimeError(f"Required local source {path} not found")
    return p.read_text(encoding="utf-8-sig")


def split_extinf(line: str) -> tuple[str, str]:
    """Split an #EXTINF line at the first comma outside double quotes."""
    in_quotes = False
    for i, ch in enumerate(line):
        if ch == '"':
            in_quotes = not in_quotes
        elif ch == "," and not in_quotes:
            return line[:i], line[i + 1 :].strip()
    return line, ""


def parse_entries(text: str) -> list[dict]:
    """Parse M3U entries while preserving their original lines."""
    entries: list[dict] = []
    current: dict | None = None

    for raw in text.splitlines():
        raw = raw.rstrip("\r")
        line = raw.strip()

        if not line or line.startswith("#EXTM3U"):
            continue

        if line.startswith("#EXTINF:"):
            if current and current.get("url"):
                entries.append(current)

            metadata_part, display_name = split_extinf(line)
            attrs = {k.lower(): v for k, v in ATTR_RE.findall(metadata_part)}
            current = {
                "lines": [raw],
                "url": None,
                "display_name": display_name or attrs.get("tvg-name", "") or "Unnamed channel",
                "tvg_id": attrs.get("tvg-id", ""),
                "tvg_name": attrs.get("tvg-name", ""),
                "logo": attrs.get("tvg-logo", ""),
                "group_title": attrs.get("group-title", ""),
            }
            continue

        if current is None:
            continue

        current["lines"].append(raw)

        if not line.startswith("#"):
            current["url"] = line
            entries.append(current)
            current = None

    if current and current.get("url"):
        entries.append(current)

    return entries


def strip_display_annotations(name: str) -> str:
    value = " ".join((name or "").split()).strip()
    old = None
    while value and value != old:
        old = value
        value = QUALITY_SUFFIX_RE.sub("", value).strip()
    return value or "Unnamed channel"


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").casefold()
    value = re.sub(r"[^\w]+", " ", value, flags=re.UNICODE)
    return " ".join(value.split())


def normalized_tvg_id(tvg_id: str) -> str:
    value = (tvg_id or "").strip()
    value = TVG_VARIANT_SUFFIX_RE.sub("", value)
    return value.casefold()


def channel_key(entry: dict) -> str:
    """
    Identify a logical channel.

    Priority:
      1. tvg-id, with @SD/@HD-style variants collapsed
      2. tvg-name
      3. cleaned display name
    """
    tvg_id = normalized_tvg_id(entry.get("tvg_id", ""))
    if tvg_id:
        return f"id:{tvg_id}"

    tvg_name = normalize_text(entry.get("tvg_name", ""))
    if tvg_name:
        return f"name:{tvg_name}"

    return f"name:{normalize_text(strip_display_annotations(entry.get('display_name', '')))}"



def extract_source_flags(name: str) -> list[str]:
    flags: list[str] = []
    for match in SOURCE_FLAG_RE.finditer(name or ""):
        value = match.group(1).casefold()
        if "geo" in value:
            label = "Geo-blocked"
        elif "24/7" in value:
            label = "Not 24/7"
        else:
            label = "Offline"
        if label not in flags:
            flags.append(label)
    return flags


def strip_custom_prefix(name: str) -> str:
    return CUSTOM_PREFIX_RE.sub("", (name or "").strip()).strip()


def rewrite_extinf_line(line: str, new_name: str, group_title: str) -> str:
    metadata, _old_name = split_extinf(line)
    safe_group = (group_title or "").replace('"', "'")
    if re.search(r'\s+group-title="[^"]*"', metadata, flags=re.IGNORECASE):
        metadata = re.sub(
            r'\s+group-title="[^"]*"',
            f' group-title="{safe_group}"',
            metadata,
            count=1,
            flags=re.IGNORECASE,
        )
    else:
        metadata += f' group-title="{safe_group}"'
    return f"{metadata},{new_name}"


def rewrite_entry_lines(lines: list[str], new_name: str, group_title: str) -> list[str]:
    updated = list(lines)
    for i, line in enumerate(updated):
        if line.strip().startswith("#EXTINF:"):
            updated[i] = rewrite_extinf_line(line, new_name, group_title)
            break
    return updated


def playlist_status_suffix(decision: str) -> str:
    return {
        "Verified": "OK",
        "TV verified": "TV",
        "PC only": "PC",
        "Rejected": "X",
    }.get(decision, "?")



def source_spec(item, default_name: str, kind: str) -> dict:
    """Accept both old plain-string config entries and v2 objects."""
    if isinstance(item, str):
        key = "url" if item.startswith(("http://", "https://")) else "path"
        return {"name": default_name, "kind": kind, key: item}

    if isinstance(item, dict):
        result = dict(item)
        result.setdefault("name", default_name)
        result.setdefault("kind", kind)
        return result

    raise TypeError(f"Unsupported source definition: {item!r}")


def load_previous_report(url: str | None) -> dict | None:
    if not url:
        return None

    try:
        text = http_get_text(url, timeout=15)
        data = json.loads(text)
        if isinstance(data, dict) and isinstance(data.get("channels"), list):
            return data
    except Exception as exc:
        print(f"Previous report unavailable: {exc}")

    return None


def safe_csv_value(value: str) -> str:
    return value.replace("\r", " ").replace("\n", " ").strip()


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: safe_csv_value(str(row.get(k, ""))) for k in fieldnames})



def load_audit(path: str | None) -> list[dict]:
    if not path:
        return []

    p = ROOT / path
    if not p.exists():
        print(f"Audit file not found: {path}")
        return []

    data = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("channels", [])

    if not isinstance(data, list):
        raise RuntimeError("audit.json must contain a list or an object with a 'channels' list.")

    return [dict(item) for item in data if isinstance(item, dict)]


def normalize_test_status(value: str) -> str:
    raw = (value or "").strip()
    value = raw.casefold().replace(" ", "_")

    canonical = {
        "works", "works_with_warning", "loads", "mrl_error",
        "format_error", "generic_error", "wrong_language",
        "not_tested", "needs_review"
    }
    if value in canonical:
        return value

    aliases = {
        "ok": "works",
        "working": "works",
        "pass": "works",
        "passed": "works",
        "yes": "works",
        "just_loads": "loads",
        "pending": "not_tested",
        "untested": "not_tested",
        "not-tested": "not_tested",
        "": "not_tested",
    }
    if value in aliases:
        return aliases[value]

    lower = raw.casefold()
    if "unable to open the mrl" in lower:
        return "mrl_error"
    if "player_error_not_supported_file" in lower:
        return "format_error"
    if "player_error_generic" in lower:
        return "generic_error"
    if (
        "czech language" in lower
        or "german language" in lower
        or "russian language" in lower
        or "english language" in lower
    ):
        return "wrong_language"
    if "certificate" in lower and ("work" in lower or "play" in lower or "ok" in lower):
        return "works_with_warning"
    if "just loads" in lower:
        return "loads"
    if lower.startswith("ok"):
        return "works"

    return "needs_review"

def is_tested_status(value: str) -> bool:
    """
    Return True when a device has an actual recorded test result.

    Any normalized status except 'not_tested' means the stream was tested,
    even if playback failed, kept loading, had a warning, used the wrong
    language, or still needs review.
    """
    return normalize_test_status(value) != "not_tested"
	
def calculate_audit_decision(item: dict) -> tuple[str, str]:
    """
    Playback/device status for our playlist, not a legal certification.
    """
    explicit = (item.get("decision") or "auto").strip().casefold().replace(" ", "_")
    if explicit in {"verified", "tv_verified", "pc_only", "needs_review", "rejected"}:
        label = {
            "verified": "Verified",
            "tv_verified": "TV verified",
            "pc_only": "PC only",
            "needs_review": "Needs review",
            "rejected": "Rejected",
        }[explicit]
        return label, str(item.get("reason") or "").strip()

    if bool(item.get("exclude_from_playlist")):
        return "Rejected", str(item.get("reason") or "Excluded from this language playlist.").strip()

    vlc = normalize_test_status(str(item.get("vlc", "")))
    samsung = normalize_test_status(str(item.get("samsung", "")))
    language = (item.get("language") or "Unknown").strip().casefold()

    wrong_languages = {
        "english", "czech", "german", "russian",
        "wrong", "wrong language", "not hungarian",
        "non-hungarian", "not_hungarian"
    }
    if language in wrong_languages or vlc == "wrong_language" or samsung == "wrong_language":
        return "Rejected", "Observed language does not match this Hungarian playlist."

    pc_good = vlc in {"works", "works_with_warning"}
    tv_good = samsung == "works"

    if pc_good and tv_good:
        return "Verified", ""

    if tv_good and not pc_good:
        return "TV verified", "Works on Samsung; VLC needs another look."

    if pc_good and samsung in {"format_error", "generic_error", "loads"}:
        return "PC only", "Works in VLC but not on Samsung in the current test."

    return "Needs review", str(item.get("reason") or "").strip()


def infer_protocol(url: str) -> str:
    value = (url or "").strip().lower()
    if value.startswith("rtmp://"):
        return "RTMP"
    if ".m3u8" in value:
        return "HLS"
    if value.startswith("https://"):
        return "HTTPS"
    if value.startswith("http://"):
        return "HTTP"
    return ""


def audit_match_key(item: dict) -> tuple[str, str]:
    url = str(item.get("stream_url") or item.get("url") or "").strip()
    if url:
        return ("url", url)

    tvg_id = normalized_tvg_id(str(item.get("tvg_id") or ""))
    if tvg_id:
        return ("tvg_id", tvg_id)

    name = normalize_text(str(item.get("channel") or item.get("channel_name") or ""))
    return ("name", name)


def prepare_audit_rows(audit_items: list[dict], final_entries: list[dict]) -> list[dict]:
    """
    Create one audit row PER STREAM URL.

    Important V8 behavior:
    - If a channel has multiple stream URLs, each one gets Feed 1/2, Feed 2/2, etc.
    - A saved audit result with an exact stream_url applies only to that stream.
    - Older channel-level audit results (no stream_url) apply only to Feed 1.
      Other feeds remain untested until they are tested separately.
    """
    def canonical_name(value: str) -> str:
        return normalize_text(strip_display_annotations(value or ""))

    # Assign stable feed numbers in current source order.
    counts: dict[str, int] = {}
    for entry in final_entries:
        key = entry.get("channel_key") or channel_key(entry)
        counts[key] = counts.get(key, 0) + 1

    seen_feed: dict[str, int] = {}
    for entry in final_entries:
        key = entry.get("channel_key") or channel_key(entry)
        seen_feed[key] = seen_feed.get(key, 0) + 1
        entry["variant_index"] = seen_feed[key]
        entry["variant_count"] = counts[key]

    manual_by_url: dict[str, dict] = {}
    manual_by_tvg_id: dict[str, dict] = {}
    manual_by_name: dict[str, dict] = {}

    for raw in audit_items:
        item = dict(raw)
        url = str(item.get("stream_url") or "").strip()
        tvg_id = normalized_tvg_id(str(item.get("tvg_id") or ""))
        name = canonical_name(str(item.get("channel") or ""))

        if url:
            manual_by_url[url] = item
        if tvg_id and not url:
            manual_by_tvg_id[tvg_id] = item
        if name and not url:
            manual_by_name[name] = item

    used_manual_keys: set[tuple[str, str]] = set()
    rows: list[dict] = []

    for entry in final_entries:
        url = str(entry.get("url") or "").strip()
        tvg_id = str(entry.get("tvg_id") or "").strip()
        clean_name = str(
            entry.get("channel_name")
            or entry.get("display_name")
            or "Unnamed channel"
        ).strip()
        feed_index = int(entry.get("variant_index") or 1)
        feed_count = int(entry.get("variant_count") or 1)

        manual = None
        manual_key = None

        # Exact URL is always authoritative.
        if url and url in manual_by_url:
            manual = manual_by_url[url]
            manual_key = ("url", url)

        # Legacy channel-level results only apply to Feed 1.
        elif feed_index == 1:
            tid = normalized_tvg_id(tvg_id)
            cname = canonical_name(clean_name)

            if tid and tid in manual_by_tvg_id:
                manual = manual_by_tvg_id[tid]
                manual_key = ("tvg", tid)
            elif cname and cname in manual_by_name:
                manual = manual_by_name[cname]
                manual_key = ("name", cname)

        item = {
            "channel": clean_name,
            "tvg_id": tvg_id,
            "source": str(entry.get("source") or ""),
            "discovery": str(entry.get("source") or "Current playlist"),
            "stream_url": url,
            "protocol": infer_protocol(url),
            "language": "Unknown",
            "language_code": str(entry.get("language_code") or "HU"),
            "provenance": (
                "Our curated/test extra"
                if entry.get("source_kind") == "extras"
                else "IPTV-org source (manual playback review)"
            ),
            "source_flags": list(entry.get("source_flags") or []),
            "vlc": "not_tested",
            "samsung": "not_tested",
            "vlc_note": "",
            "samsung_note": "",
            "decision": "auto",
            "reason": "",
            "notes": (
                "Auto-added from current tv.m3u for manual testing."
                if feed_count == 1
                else f"Alternative stream Feed {feed_index}/{feed_count}; test this URL separately."
            ),
            "exclude_from_playlist": False,
            "tested_on": "",
        }

        if manual is not None:
            if manual_key:
                used_manual_keys.add(manual_key)
            for key, value in manual.items():
                if value not in ("", None):
                    item[key] = value

        flags: list[str] = []
        for flag in list(entry.get("source_flags") or []) + list(item.get("source_flags") or []):
            if flag and flag not in flags:
                flags.append(flag)
        item["source_flags"] = flags

        decision, auto_reason = calculate_audit_decision(item)

        rows.append({
            "channel": str(item.get("channel") or clean_name).strip(),
            "tvg_id": str(item.get("tvg_id") or tvg_id).strip(),
            "source": str(item.get("source") or entry.get("source") or "").strip(),
            "discovery": str(item.get("discovery") or entry.get("source") or "").strip(),
            "stream_url": str(item.get("stream_url") or url).strip(),
            "protocol": str(item.get("protocol") or infer_protocol(url)).strip(),
            "language": str(item.get("language") or "Unknown").strip(),
            "language_code": str(
                item.get("language_code")
                or entry.get("language_code")
                or "HU"
            ).strip().upper(),
            "provenance": str(item.get("provenance") or "").strip(),
            "source_flags": flags,
            "vlc": normalize_test_status(str(item.get("vlc") or "")),
            "samsung": normalize_test_status(str(item.get("samsung") or "")),
            "vlc_note": str(item.get("vlc_note") or "").strip(),
            "samsung_note": str(item.get("samsung_note") or "").strip(),
            "decision": decision,
            "reason": str(item.get("reason") or auto_reason or "").strip(),
            "notes": str(item.get("notes") or "").strip(),
            "exclude_from_playlist": bool(item.get("exclude_from_playlist")),
            "tested_on": str(item.get("tested_on") or "").strip(),
            "in_playlist": True,
            "feed_index": feed_index,
            "feed_count": feed_count,
            "feed_label": (
                f"Feed {feed_index}/{feed_count}"
                if feed_count > 1 else "Single"
            ),
        })

    current_urls = {
        (e.get("url") or "").strip()
        for e in final_entries if e.get("url")
    }
    current_names = {
        canonical_name(str(e.get("channel_name") or e.get("display_name") or ""))
        for e in final_entries
    }

    # Keep manually tracked candidates/rejections that are not currently in tv.m3u.
    for raw in audit_items:
        item = dict(raw)
        url = str(item.get("stream_url") or "").strip()
        tid = normalized_tvg_id(str(item.get("tvg_id") or ""))
        cname = canonical_name(str(item.get("channel") or ""))

        if url:
            manual_key = ("url", url)
        elif tid:
            manual_key = ("tvg", tid)
        else:
            manual_key = ("name", cname)

        if manual_key in used_manual_keys:
            continue
        if url and url in current_urls:
            continue
        if not url and cname in current_names:
            # A legacy channel-level row has already been represented by Feed 1.
            continue

        decision, auto_reason = calculate_audit_decision(item)
        rows.append({
            "channel": str(item.get("channel") or "Unnamed channel").strip(),
            "tvg_id": str(item.get("tvg_id") or "").strip(),
            "source": str(item.get("source") or "").strip(),
            "discovery": str(item.get("discovery") or "").strip(),
            "stream_url": url,
            "protocol": str(item.get("protocol") or infer_protocol(url)).strip(),
            "language": str(item.get("language") or "Unknown").strip(),
            "language_code": str(item.get("language_code") or "HU").strip().upper(),
            "provenance": str(item.get("provenance") or "Unknown").strip(),
            "source_flags": list(item.get("source_flags") or []),
            "vlc": normalize_test_status(str(item.get("vlc") or "")),
            "samsung": normalize_test_status(str(item.get("samsung") or "")),
            "vlc_note": str(item.get("vlc_note") or "").strip(),
            "samsung_note": str(item.get("samsung_note") or "").strip(),
            "decision": decision,
            "reason": str(item.get("reason") or auto_reason or "").strip(),
            "notes": str(item.get("notes") or "").strip(),
            "exclude_from_playlist": bool(item.get("exclude_from_playlist")),
            "tested_on": str(item.get("tested_on") or "").strip(),
            "in_playlist": False,
            "feed_index": 1,
            "feed_count": 1,
            "feed_label": "Candidate",
        })

    priority = {
        "Needs review": 0,
        "TV verified": 1,
        "PC only": 2,
        "Verified": 3,
        "Rejected": 4,
    }

    return sorted(
        rows,
        key=lambda x: (
            priority.get(x["decision"], 9),
            0 if x["in_playlist"] else 1,
            normalize_text(x["channel"]),
            int(x.get("feed_index") or 1),
        ),
    )


def make_dashboard(
    cfg: dict,
    generated: str,
    final_entries: list[dict],
    unique_channels: list[dict],
    source_stats: list[dict],
    duplicate_rows: list[dict],
    changes: dict,
    audit_rows: list[dict],
) -> str:
    title = str(cfg.get("site_title") or "Tomas IPTV")
    total_streams = len(final_entries)
    total_channels = len(unique_channels)
    total_duplicates = len(duplicate_rows)
    total_alternatives = sum(1 for e in final_entries if e["classification"] == "Alternative stream")
    added_from_nonbase = sum(1 for e in final_entries if e["classification"] == "Added channel")
    audit_verified = sum(1 for e in audit_rows if e["decision"] == "Verified")
    audit_tv_verified = sum(1 for e in audit_rows if e["decision"] == "TV verified")
    audit_pc_only = sum(1 for e in audit_rows if e["decision"] == "PC only")
    audit_review = sum(1 for e in audit_rows if e["decision"] == "Needs review")
    audit_rejected = sum(1 for e in audit_rows if e["decision"] == "Rejected")
    audit_current = [e for e in audit_rows if e["in_playlist"]]
    audit_both_tested = sum(
        1 for e in audit_current
        if is_tested_status(e["vlc"]) and is_tested_status(e["samsung"])
    )
    audit_vlc_pending = sum(
        1 for e in audit_current
        if not is_tested_status(e["vlc"])
    )
    audit_samsung_pending = sum(
        1 for e in audit_current
        if not is_tested_status(e["samsung"])
    )

    def esc(v) -> str:
        return html.escape(str(v or ""))

    source_options = "\n".join(
        f'<option value="{esc(s["name"])}">{esc(s["name"])}</option>'
        for s in source_stats
    )

    source_rows = "\n".join(
        f"""
        <tr>
          <td>{esc(s["name"])}</td>
          <td>{s["raw_entries"]}</td>
          <td>{s["unique_channels_in_source"]}</td>
          <td>{s["kept_stream_urls"]}</td>
          <td>{s["new_channels_contributed"]}</td>
          <td>{s["alternative_streams"]}</td>
          <td>{s["duplicate_urls_ignored"]}</td>
        </tr>
        """
        for s in source_stats
    )

    channel_rows = []
    for e in final_entries:
        classification = e["classification"]
        badge_class = {
            "Base channel": "base",
            "Added channel": "added",
            "Alternative stream": "alt",
        }.get(classification, "base")

        channel_rows.append(
            f"""
            <tr data-source="{esc(e["source"])}" data-status="{esc(classification)}">
              <td class="channel">{esc(e["channel_name"])}</td>
              <td>{esc(e.get("tvg_id", ""))}</td>
              <td>{esc(e.get("group_title", ""))}</td>
              <td>{esc(e["source"])}</td>
              <td><span class="badge {badge_class}">{esc(classification)}</span></td>
              <td class="url"><a href="{esc(e["url"])}" target="_blank" rel="noopener">stream</a></td>
            </tr>
            """
        )

    def test_badge(value: str) -> str:
        labels = {
            "works": ("✓ Works", "verified"),
            "works_with_warning": ("✓ Works*", "pc"),
            "loads": ("… Loads", "review"),
            "mrl_error": ("MRL error", "rejected"),
            "format_error": ("Format error", "rejected"),
            "generic_error": ("Player error", "rejected"),
            "wrong_language": ("Wrong language", "rejected"),
            "not_tested": ("? Not tested", "review"),
            "needs_review": ("? Review", "review"),
            "n/a": ("N/A", "base"),
        }
        label, css = labels.get(value, (value or "?", "review"))
        return f'<span class="badge {css}">{esc(label)}</span>'

    audit_table_rows = []
    for a in audit_rows:
        decision_css = {
            "Verified": "verified",
            "TV verified": "tv",
            "PC only": "pc",
            "Needs review": "review",
            "Rejected": "rejected",
        }.get(a["decision"], "review")

        in_playlist = (
            '<span class="badge verified">Yes</span>'
            if a["in_playlist"]
            else '<span class="badge base">No</span>'
        )

        reason_notes = " — ".join(
            part for part in [a.get("reason", ""), a.get("notes", "")] if part
        )

        stream_link = (
            f'<a href="{esc(a["stream_url"])}" target="_blank" rel="noopener">stream</a>'
            if a.get("stream_url")
            else "—"
        )

        audit_table_rows.append(
            f"""
            <tr data-audit-decision="{esc(a["decision"])}" data-audit-vlc="{esc(a["vlc"])}" data-audit-samsung="{esc(a["samsung"])}">
              <td class="channel">{esc(a["channel"])}</td>
              <td>{esc(a.get("feed_label", "Single"))}</td>
              <td>{esc(a.get("tvg_id", "") or "—")}</td>
              <td>{esc(a.get("source", "") or "—")}</td>
              <td>{esc(a["discovery"])}</td>
              <td>{esc(a["protocol"] or "—")}</td>
              <td>{esc(a["language"])}</td>
              <td>{esc(a["provenance"])}</td>
              <td>{esc(", ".join(a.get("source_flags") or []) or "—")}</td>
              <td>{test_badge(a["vlc"])}<div class="detail">{esc(a.get("vlc_note", ""))}</div></td>
              <td>{test_badge(a["samsung"])}<div class="detail">{esc(a.get("samsung_note", ""))}</div></td>
              <td><span class="badge {decision_css}">{esc(a["decision"])}</span></td>
              <td>{in_playlist}</td>
              <td>{esc(reason_notes or "—")}</td>
              <td class="url">{stream_link}</td>
            </tr>
            """
        )

    previous = changes.get("previous_generated_at")
    if previous:
        added_names = changes.get("added_channels", [])
        removed_names = changes.get("removed_channels", [])

        def list_items(values: list[str], empty_text: str) -> str:
            if not values:
                return f"<li>{esc(empty_text)}</li>"
            return "".join(f"<li>{esc(v)}</li>" for v in values)

        change_html = f"""
        <div class="change-grid">
          <div class="panel">
            <h3>Added since previous build <span class="count positive">+{len(added_names)}</span></h3>
            <details {'open' if added_names else ''}>
              <summary>Show channels</summary>
              <ul>{list_items(added_names, "No channels added.")}</ul>
            </details>
          </div>
          <div class="panel">
            <h3>Removed since previous build <span class="count negative">-{len(removed_names)}</span></h3>
            <details {'open' if removed_names else ''}>
              <summary>Show channels</summary>
              <ul>{list_items(removed_names, "No channels removed.")}</ul>
            </details>
          </div>
        </div>
        <p class="muted">Compared with report generated {esc(previous)}.</p>
        """
    else:
        change_html = """
        <div class="panel">
          <strong>No previous report was available for comparison.</strong>
          <p class="muted">After the next successful build, this section will show channels added and removed since the previous deployment.</p>
        </div>
        """

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<style>
:root {{
  color-scheme: light dark;
  --bg: #0d1117;
  --card: #161b22;
  --border: #30363d;
  --text: #e6edf3;
  --muted: #8b949e;
  --accent: #58a6ff;
  --good: #3fb950;
  --purple: #a371f7;
  --warn: #d29922;
  --bad: #f85149;
}}
@media (prefers-color-scheme: light) {{
  :root {{
    --bg: #ffffff;
    --card: #f6f8fa;
    --border: #d0d7de;
    --text: #1f2328;
    --muted: #656d76;
    --accent: #0969da;
    --good: #1a7f37;
    --purple: #8250df;
  }}
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  line-height: 1.45;
}}
main {{ max-width: 1500px; margin: 0 auto; padding: 28px 20px 60px; }}
h1 {{ margin-bottom: 4px; }}
h2 {{ margin-top: 34px; }}
a {{ color: var(--accent); }}
.muted {{ color: var(--muted); }}
.links {{ display: flex; gap: 14px; flex-wrap: wrap; margin: 18px 0; }}
.cards {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
  margin: 20px 0;
}}
.card, .panel {{
  border: 1px solid var(--border);
  background: var(--card);
  border-radius: 10px;
  padding: 16px;
}}
.card .value {{ font-size: 1.8rem; font-weight: 750; }}
.card .label {{ color: var(--muted); font-size: .92rem; }}
.table-wrap {{
  overflow-x: auto;
  border: 1px solid var(--border);
  border-radius: 10px;
}}
table {{ width: 100%; border-collapse: collapse; }}
th, td {{
  padding: 10px 12px;
  border-bottom: 1px solid var(--border);
  text-align: left;
  vertical-align: top;
}}
th {{
  position: sticky;
  top: 0;
  background: var(--card);
  z-index: 1;
}}
tr:last-child td {{ border-bottom: 0; }}
.channel {{ font-weight: 650; min-width: 220px; }}
.url {{ white-space: nowrap; }}
.badge {{
  display: inline-block;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: .82rem;
  font-weight: 700;
  white-space: nowrap;
}}
.badge.base {{ border: 1px solid var(--border); }}
.badge.added {{ color: var(--good); border: 1px solid var(--good); }}
.badge.alt {{ color: var(--purple); border: 1px solid var(--purple); }}
.badge.verified {{ color: var(--good); border: 1px solid var(--good); }}
.badge.review {{ color: var(--warn); border: 1px solid var(--warn); }}
.badge.rejected {{ color: var(--bad); border: 1px solid var(--bad); }}
.badge.tv {{ color: var(--accent); border: 1px solid var(--accent); }}
.badge.pc {{ color: var(--purple); border: 1px solid var(--purple); }}
.detail {{ color: var(--muted); font-size: .76rem; margin-top: 4px; max-width: 360px; }}
.audit-summary {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
  margin: 12px 0 18px;
}}
.controls {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 10px;
  margin: 14px 0;
}}
input, select {{
  width: 100%;
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--card);
  color: var(--text);
}}
.change-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 12px;
}}
.count {{ font-size: .9rem; }}
.positive {{ color: var(--good); }}
.negative {{ color: #f85149; }}
details ul {{ max-height: 260px; overflow: auto; }}
@media (max-width: 780px) {{
  .controls {{ grid-template-columns: 1fr; }}
}}
</style>
</head>
<body>
<main>
  <h1>{esc(title)}</h1>
  <p class="muted">Generated automatically: {esc(generated)}</p>

  <div class="links">
    <a href="tv.m3u">TV playlist (tv.m3u)</a>
    <a href="channels.csv">Channel inventory (CSV)</a>
    <a href="duplicates.csv">Ignored duplicate URLs (CSV)</a>
    <a href="excluded.csv">Excluded from playlist (CSV)</a>
    <a href="audit.csv">Manual verification (CSV)</a>
    <a href="report.json">Machine report (JSON)</a>
  </div>

  <div class="cards">
    <div class="card"><div class="value">{total_channels}</div><div class="label">Unique channels</div></div>
    <div class="card"><div class="value">{total_streams}</div><div class="label">Unique stream URLs</div></div>
    <div class="card"><div class="value">{added_from_nonbase}</div><div class="label">Channels added beyond base</div></div>
    <div class="card"><div class="value">{total_alternatives}</div><div class="label">Alternative streams kept</div></div>
    <div class="card"><div class="value">{total_duplicates}</div><div class="label">Duplicate URLs ignored</div></div>
  </div>

  <h2>Manual verification</h2>
  <p class="muted">
    This is our persistent playback test log. “Verified” means it worked in both VLC
    and the Samsung test. “TV verified” means Samsung worked even if VLC did not;
    “PC only” means VLC worked but Samsung did not. Provenance is tracked separately,
    so these labels are not legal certifications.
  </p>

  <div class="audit-summary">
    <div class="card"><div class="value">{len(audit_current)}</div><div class="label">Channels/streams in testing queue</div></div>
    <div class="card"><div class="value">{audit_both_tested}</div><div class="label">Tested on both devices</div></div>
    <div class="card"><div class="value">{audit_vlc_pending}</div><div class="label">VLC tests remaining</div></div>
    <div class="card"><div class="value">{audit_samsung_pending}</div><div class="label">Samsung tests remaining</div></div>
    <div class="card"><div class="value">{audit_verified}</div><div class="label">✓ Verified both</div></div>
    <div class="card"><div class="value">{audit_tv_verified}</div><div class="label">TV verified</div></div>
    <div class="card"><div class="value">{audit_pc_only}</div><div class="label">PC only</div></div>
    <div class="card"><div class="value">{audit_review}</div><div class="label">? Needs review</div></div>
    <div class="card"><div class="value">{audit_rejected}</div><div class="label">✕ Rejected</div></div>
  </div>

  <div class="controls">
    <input id="auditSearch" type="search" placeholder="Search manual tests...">
    <select id="auditDecisionFilter">
      <option value="">All manual decisions</option>
      <option value="Verified">Verified</option>
      <option value="TV verified">TV verified</option>
      <option value="PC only">PC only</option>
      <option value="Needs review">Needs review</option>
      <option value="Rejected">Rejected</option>
    </select>
    <select id="auditVlcFilter">
      <option value="">All VLC statuses</option>
      <option value="works">VLC works</option>
      <option value="works_with_warning">VLC works with warning</option>
      <option value="loads">VLC keeps loading</option>
      <option value="mrl_error">VLC MRL error</option>
      <option value="wrong_language">VLC wrong language</option>
      <option value="not_tested">VLC not tested</option>
    </select>
    <select id="auditSamsungFilter">
      <option value="">All Samsung statuses</option>
      <option value="works">Samsung works</option>
      <option value="format_error">Samsung unsupported format</option>
      <option value="generic_error">Samsung generic error</option>
      <option value="loads">Samsung keeps loading</option>
      <option value="wrong_language">Samsung wrong language</option>
      <option value="not_tested">Samsung not tested</option>
    </select>
  </div>
  <p id="auditVisibleCount" class="muted"></p>

  <div class="table-wrap">
    <table id="auditTable">
      <thead>
        <tr>
          <th>Channel</th>
          <th>Feed</th>
          <th>TVG ID</th>
          <th>Source</th>
          <th>Discovery</th>
          <th>Protocol</th>
          <th>Language</th>
          <th>Provenance</th>
          <th>Source flag</th>
          <th>VLC</th>
          <th>Samsung</th>
          <th>Decision</th>
          <th>In playlist</th>
          <th>Reason / notes</th>
          <th>URL</th>
        </tr>
      </thead>
      <tbody>{''.join(audit_table_rows)}</tbody>
    </table>
  </div>

  <h2>Source contribution</h2>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>Source</th>
          <th>Raw entries</th>
          <th>Unique channels in source</th>
          <th>Stream URLs kept</th>
          <th>New channels contributed</th>
          <th>Alternative streams</th>
          <th>Duplicate URLs ignored</th>
        </tr>
      </thead>
      <tbody>{source_rows}</tbody>
    </table>
  </div>

  <h2>Changes since previous build</h2>
  {change_html}

  <h2>Channel inventory</h2>
  <p class="muted">
    “Added channel” means this source introduced a channel that had not appeared in an earlier source.
    “Alternative stream” means the channel already existed, but this source supplied a different stream URL.
  </p>

  <div class="controls">
    <input id="search" type="search" placeholder="Search channel, TVG ID, group or URL...">
    <select id="sourceFilter">
      <option value="">All sources</option>
      {source_options}
    </select>
    <select id="statusFilter">
      <option value="">All classifications</option>
      <option value="Base channel">Base channel</option>
      <option value="Added channel">Added channel</option>
      <option value="Alternative stream">Alternative stream</option>
    </select>
  </div>

  <p id="visibleCount" class="muted"></p>

  <div class="table-wrap">
    <table id="channels">
      <thead>
        <tr>
          <th>Channel</th>
          <th>TVG ID</th>
          <th>Group</th>
          <th>Source</th>
          <th>Result</th>
          <th>URL</th>
        </tr>
      </thead>
      <tbody>
        {''.join(channel_rows)}
      </tbody>
    </table>
  </div>
</main>

<script>
const search = document.getElementById('search');
const sourceFilter = document.getElementById('sourceFilter');
const statusFilter = document.getElementById('statusFilter');
const rows = Array.from(document.querySelectorAll('#channels tbody tr'));
const visibleCount = document.getElementById('visibleCount');

function applyFilters() {{
  const q = search.value.trim().toLowerCase();
  const source = sourceFilter.value;
  const status = statusFilter.value;
  let shown = 0;

  for (const row of rows) {{
    const matchesText = !q || row.innerText.toLowerCase().includes(q);
    const matchesSource = !source || row.dataset.source === source;
    const matchesStatus = !status || row.dataset.status === status;
    const show = matchesText && matchesSource && matchesStatus;
    row.style.display = show ? '' : 'none';
    if (show) shown++;
  }}

  visibleCount.textContent = `Showing ${{shown}} of ${{rows.length}} stream entries`;
}}

const auditSearch = document.getElementById('auditSearch');
const auditDecisionFilter = document.getElementById('auditDecisionFilter');
const auditVlcFilter = document.getElementById('auditVlcFilter');
const auditSamsungFilter = document.getElementById('auditSamsungFilter');
const auditRows = Array.from(document.querySelectorAll('#auditTable tbody tr'));
const auditVisibleCount = document.getElementById('auditVisibleCount');

function applyAuditFilters() {{
  const q = auditSearch.value.trim().toLowerCase();
  const decision = auditDecisionFilter.value;
  const vlc = auditVlcFilter.value;
  const samsung = auditSamsungFilter.value;
  let shown = 0;

  for (const row of auditRows) {{
    const matchesText = !q || row.innerText.toLowerCase().includes(q);
    const matchesDecision = !decision || row.dataset.auditDecision === decision;
    const matchesVlc = !vlc || row.dataset.auditVlc === vlc;
    const matchesSamsung = !samsung || row.dataset.auditSamsung === samsung;
    const show = matchesText && matchesDecision && matchesVlc && matchesSamsung;
    row.style.display = show ? '' : 'none';
    if (show) shown++;
  }}

  auditVisibleCount.textContent = `Showing ${{shown}} of ${{auditRows.length}} manually reviewed/candidate channels`;
}}

auditSearch.addEventListener('input', applyAuditFilters);
auditDecisionFilter.addEventListener('change', applyAuditFilters);
auditVlcFilter.addEventListener('change', applyAuditFilters);
auditSamsungFilter.addEventListener('change', applyAuditFilters);
applyAuditFilters();

search.addEventListener('input', applyFilters);
sourceFilter.addEventListener('change', applyFilters);
statusFilter.addEventListener('change', applyFilters);
applyFilters();
</script>
</body>
</html>
"""


def main() -> None:
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    audit_items = load_audit(cfg.get("audit_path", "audit.json"))

    source_items: list[dict] = []

    for i, item in enumerate(cfg.get("sources", []), start=1):
        source_items.append(source_spec(item, f"Source {i}", "base" if i == 1 else "source"))

    for i, item in enumerate(cfg.get("extras", []), start=1):
        source_items.append(source_spec(item, f"Extra {i}", "extras"))

    if not source_items:
        raise RuntimeError("config.json contains no sources or extras.")

    final_entries: list[dict] = []
    duplicate_rows: list[dict] = []
    source_stats: list[dict] = []

    seen_urls: dict[str, dict] = {}
    seen_channels: dict[str, dict] = {}

    for source_index, spec in enumerate(source_items):
        name = str(spec.get("name") or f"Source {source_index + 1}")
        kind = str(spec.get("kind") or "source")

        if spec.get("url"):
            location = str(spec["url"])
            print(f"Downloading {name}: {location}")
            text = download_m3u(location)
        elif spec.get("path"):
            location = str(spec["path"])
            print(f"Reading {name}: {location}")
            text = read_local(location)
        else:
            raise RuntimeError(f"Source '{name}' has neither 'url' nor 'path'.")

        entries = parse_entries(text)
        if spec.get("url") and not entries:
            raise RuntimeError(f"No playable entries found in remote source: {location}")

        source_keys = {channel_key(e) for e in entries}
        kept = 0
        new_channels = 0
        alternatives = 0
        duplicate_urls = 0

        for entry in entries:
            url = (entry.get("url") or "").strip()
            if not url:
                continue

            key = channel_key(entry)
            clean_name = strip_display_annotations(entry.get("display_name", ""))
            entry["channel_key"] = key
            entry["channel_name"] = clean_name
            entry["source"] = name
            entry["source_kind"] = kind
            entry["language_code"] = str(
                spec.get("language_code") or cfg.get("default_language_code") or "HU"
            ).upper()
            entry["source_flags"] = extract_source_flags(entry.get("display_name", ""))

            if url in seen_urls:
                duplicate_urls += 1
                first = seen_urls[url]
                duplicate_rows.append({
                    "channel_name": clean_name,
                    "tvg_id": entry.get("tvg_id", ""),
                    "source": name,
                    "stream_url": url,
                    "already_kept_from": first["source"],
                    "already_kept_as": first["channel_name"],
                })
                continue

            if key not in seen_channels:
                classification = "Base channel" if source_index == 0 else "Added channel"
                new_channels += 1
                seen_channels[key] = {
                    "key": key,
                    "name": clean_name,
                    "first_source": name,
                }
            else:
                classification = "Alternative stream"
                alternatives += 1

            entry["classification"] = classification
            final_entries.append(entry)
            seen_urls[url] = entry
            kept += 1

        source_stats.append({
            "name": name,
            "kind": kind,
            "location": location,
            "raw_entries": len(entries),
            "unique_channels_in_source": len(source_keys),
            "kept_stream_urls": kept,
            "new_channels_contributed": new_channels,
            "alternative_streams": alternatives,
            "duplicate_urls_ignored": duplicate_urls,
        })

    audit_rows = prepare_audit_rows(audit_items, final_entries)

    audit_by_url = {
        row["stream_url"]: row
        for row in audit_rows
        if row.get("stream_url")
    }

    # Legacy fallbacks are intentionally limited to old audit rows that do not
    # identify a specific stream URL. A per-URL result must never "bleed" into
    # another feed of the same channel.
    audit_by_tvg = {
        normalized_tvg_id(row.get("tvg_id", "")): row
        for row in audit_rows
        if not row.get("stream_url")
        and normalized_tvg_id(row.get("tvg_id", ""))
    }
    audit_by_name = {
        normalize_text(row.get("channel", "")): row
        for row in audit_rows
        if not row.get("stream_url")
        and row.get("channel")
    }

    def audit_for_entry(entry: dict) -> dict | None:
        url = str(entry.get("url") or "").strip()
        if url and url in audit_by_url:
            return audit_by_url[url]

        tid = normalized_tvg_id(str(entry.get("tvg_id") or ""))
        if tid and tid in audit_by_tvg:
            return audit_by_tvg[tid]

        return audit_by_name.get(
            normalize_text(entry.get("channel_name", ""))
        )

    candidate_entries: list[dict] = []
    excluded_rows: list[dict] = []

    for source_order, entry in enumerate(final_entries):
        audit = audit_for_entry(entry)
        decision = audit.get("decision", "Needs review") if audit else "Needs review"
        exclude = bool(audit.get("exclude_from_playlist")) if audit else False

        if exclude or decision == "Rejected":
            excluded_rows.append({
                "channel_name": entry.get("channel_name", ""),
                "tvg_id": entry.get("tvg_id", ""),
                "source": entry.get("source", ""),
                "stream_url": entry.get("url", ""),
                "reason": (
                    (audit or {}).get("reason")
                    or (audit or {}).get("notes")
                    or "Rejected by manual audit"
                ),
            })
            continue

        candidate = dict(entry)
        candidate["_audit"] = audit or {}
        candidate["_decision"] = decision
        candidate["_source_order"] = source_order
        candidate_entries.append(candidate)

    # Group non-rejected candidate feeds by logical channel.
    candidate_groups: dict[str, list[dict]] = {}
    for entry in candidate_entries:
        candidate_groups.setdefault(entry["channel_key"], []).append(entry)

    def verified_feed_rank(entry: dict) -> tuple:
        audit = entry.get("_audit") or {}
        vlc = str(audit.get("vlc") or "")
        samsung = str(audit.get("samsung") or "")

        # User preference: if several feeds work, one is enough.
        # Prefer the feed that works without a VLC certificate/warning.
        vlc_rank = {
            "works": 3,
            "works_with_warning": 2,
        }.get(vlc, 0)

        samsung_rank = 1 if samsung == "works" else 0

        # Prefer the earlier/base source when two feeds are otherwise equal.
        source_rank = -int(entry.get("_source_order") or 0)

        return (vlc_rank, samsung_rank, source_rank)

    selected_candidates: list[dict] = []

    for channel_key_value, group in candidate_groups.items():
        verified = [e for e in group if e.get("_decision") == "Verified"]

        if verified:
            winner = max(verified, key=verified_feed_rank)
            selected_candidates.append(winner)

            for entry in group:
                if entry is winner:
                    continue
                excluded_rows.append({
                    "channel_name": entry.get("channel_name", ""),
                    "tvg_id": entry.get("tvg_id", ""),
                    "source": entry.get("source", ""),
                    "stream_url": entry.get("url", ""),
                    "reason": (
                        "Suppressed because another feed for this channel is "
                        "already Verified on both VLC and Samsung."
                    ),
                })
        else:
            # No fully verified winner yet, so keep the remaining candidates in
            # the playlist for manual testing.
            selected_candidates.extend(group)

    # Re-number only the feeds that are actually visible in the playlist.
    visible_groups: dict[str, list[dict]] = {}
    for entry in selected_candidates:
        visible_groups.setdefault(entry["channel_key"], []).append(entry)

    published_entries: list[dict] = []

    for channel_key_value, group in visible_groups.items():
        group.sort(key=lambda e: int(e.get("_source_order") or 0))
        visible_count = len(group)

        for visible_index, entry in enumerate(group, start=1):
            audit = entry.get("_audit") or {}
            decision = entry.get("_decision", "Needs review")

            lang = str(
                audit.get("language_code")
                or entry.get("language_code")
                or cfg.get("default_language_code")
                or "HU"
            ).upper()

            suffix = playlist_status_suffix(decision)
            original_display = strip_custom_prefix(entry.get("display_name", ""))

            # If only one feed survives, don't clutter the channel name with
            # Feed 1/2-style labels. Multiple unresolved feeds remain numbered.
            feed_suffix = (
                f" [Feed {visible_index}/{visible_count}]"
                if visible_count > 1
                else ""
            )

            published_name = f"[{lang} {suffix}] {original_display}{feed_suffix}"
            group_title = f"{lang} | {decision}"

            published = dict(entry)
            published["published_name"] = published_name
            published["test_status"] = decision
            published["group_title"] = group_title
            published["visible_feed_index"] = visible_index
            published["visible_feed_count"] = visible_count
            published["lines"] = rewrite_entry_lines(
                entry["lines"], published_name, group_title
            )
            published_entries.append(published)

    published_entries.sort(
        key=lambda e: (
            str(
                e.get("language_code")
                or cfg.get("default_language_code")
                or ""
            ).upper(),
            normalize_text(e.get("channel_name", "")),
            normalize_text(e.get("published_name", "")),
        )
    )

    published_urls = {e.get("url") for e in published_entries}
    for row in audit_rows:
        if row.get("stream_url"):
            row["in_playlist"] = row["stream_url"] in published_urls

    by_channel: dict[str, dict] = {}
    for entry in published_entries:
        key = entry["channel_key"]
        record = by_channel.setdefault(key, {
            "key": key,
            "name": entry["channel_name"],
            "tvg_id": entry.get("tvg_id", ""),
            "sources": [],
            "stream_count": 0,
        })
        if entry["source"] not in record["sources"]:
            record["sources"].append(entry["source"])
        record["stream_count"] += 1

    unique_channels = sorted(
        by_channel.values(),
        key=lambda x: normalize_text(x["name"])
    )

    previous_report = load_previous_report(cfg.get("previous_report_url"))
    changes = {
        "previous_generated_at": None,
        "added_channels": [],
        "removed_channels": [],
    }

    if previous_report:
        previous_by_key = {
            str(ch.get("key")): str(ch.get("name") or ch.get("key"))
            for ch in previous_report.get("channels", [])
            if ch.get("key")
        }
        current_by_key = {ch["key"]: ch["name"] for ch in unique_channels}

        added_keys = sorted(
            set(current_by_key) - set(previous_by_key),
            key=lambda k: normalize_text(current_by_key[k]),
        )
        removed_keys = sorted(
            set(previous_by_key) - set(current_by_key),
            key=lambda k: normalize_text(previous_by_key[k]),
        )

        changes = {
            "previous_generated_at": previous_report.get("generated_at"),
            "added_channels": [current_by_key[k] for k in added_keys],
            "removed_channels": [previous_by_key[k] for k in removed_keys],
        }

    out_path = ROOT / cfg.get("output", "public/tv.m3u")
    public_dir = out_path.parent
    public_dir.mkdir(parents=True, exist_ok=True)

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    out_lines = [
        "#EXTM3U",
        f"# Generated automatically: {generated}",
        "# Tomas IPTV smart builder v14",
        "",
    ]
    for entry in published_entries:
        out_lines.extend(entry["lines"])
        out_lines.append("")
    out_path.write_text("\n".join(out_lines).rstrip() + "\n", encoding="utf-8")

    inventory_rows = [
        {
            "playlist_name": e.get("published_name", e["channel_name"]),
            "channel_name": e["channel_name"],
            "feed_label": (
                f"Feed {int(e.get('visible_feed_index') or 1)}/{int(e.get('visible_feed_count') or 1)}"
                if int(e.get("visible_feed_count") or 1) > 1 else "Single"
            ),
            "feed_index": int(e.get("visible_feed_index") or 1),
            "feed_count": int(e.get("visible_feed_count") or 1),
            "tvg_id": e.get("tvg_id", ""),
            "group_title": e.get("group_title", ""),
            "test_status": e.get("test_status", "Needs review"),
            "source_flags": ", ".join(e.get("source_flags") or []),
            "source": e["source"],
            "classification": e["classification"],
            "stream_url": e["url"],
            "logo": e.get("logo", ""),
        }
        for e in published_entries
    ]
    write_csv(
        public_dir / "channels.csv",
        [
            "playlist_name", "channel_name", "feed_label", "feed_index", "feed_count",
            "tvg_id", "group_title", "test_status",
            "source_flags", "source", "classification", "stream_url", "logo"
        ],
        inventory_rows,
    )

    write_csv(
        public_dir / "duplicates.csv",
        ["channel_name", "tvg_id", "source", "stream_url", "already_kept_from", "already_kept_as"],
        duplicate_rows,
    )

    write_csv(
        public_dir / "excluded.csv",
        ["channel_name", "tvg_id", "source", "stream_url", "reason"],
        excluded_rows,
    )

    write_csv(
        public_dir / "audit.csv",
        [
            "channel", "feed_label", "feed_index", "feed_count", "tvg_id",
            "source", "discovery", "stream_url", "protocol",
            "language", "language_code", "provenance", "source_flags",
            "vlc", "vlc_note", "samsung", "samsung_note", "decision",
            "exclude_from_playlist", "in_playlist", "tested_on", "reason", "notes"
        ],
        audit_rows,
    )

    report = {
        "schema_version": 14,
        "generated_at": generated,
        "summary": {
            "unique_channels": len(unique_channels),
            "unique_stream_urls": len(published_entries),
            "excluded_by_manual_audit": len(excluded_rows),
            "added_channels_beyond_base": sum(
                1 for e in published_entries if e["classification"] == "Added channel"
            ),
            "alternative_streams": sum(
                1 for e in published_entries if e["classification"] == "Alternative stream"
            ),
            "duplicate_urls_ignored": len(duplicate_rows),
        },
        "sources": source_stats,
        "changes": changes,
        "audit": {
            "summary": {
                "current_playlist_rows": sum(1 for e in audit_rows if e["in_playlist"]),
                "tested_on_both": sum(
                    1 for e in audit_rows
                    if e["in_playlist"]
                    and is_tested_status(e["vlc"])
                    and is_tested_status(e["samsung"])
                ),
                "verified": sum(1 for e in audit_rows if e["decision"] == "Verified"),
                "tv_verified": sum(1 for e in audit_rows if e["decision"] == "TV verified"),
                "pc_only": sum(1 for e in audit_rows if e["decision"] == "PC only"),
                "needs_review": sum(1 for e in audit_rows if e["decision"] == "Needs review"),
                "rejected": sum(1 for e in audit_rows if e["decision"] == "Rejected"),
            },
            "channels": audit_rows,
        },
        "channels": unique_channels,
    }

    (public_dir / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    (public_dir / "index.html").write_text(
        make_dashboard(
            cfg=cfg,
            generated=generated,
            final_entries=published_entries,
            unique_channels=unique_channels,
            source_stats=source_stats,
            duplicate_rows=duplicate_rows,
            changes=changes,
            audit_rows=audit_rows,
        ),
        encoding="utf-8",
    )

    (public_dir / ".nojekyll").write_text("", encoding="utf-8")

    print()
    print("Build complete.")
    print(f"Unique channels:        {len(unique_channels)}")
    print(f"Unique stream URLs:     {len(published_entries)}")
    print(f"Excluded by audit:      {len(excluded_rows)}")
    print(f"Duplicate URLs ignored: {len(duplicate_rows)}")
    print(
        "Manual audit:          "
        f"{sum(1 for e in audit_rows if e['decision'] == 'Verified')} verified, "
        f"{sum(1 for e in audit_rows if e['decision'] == 'TV verified')} TV-only, "
        f"{sum(1 for e in audit_rows if e['decision'] == 'PC only')} PC-only, "
        f"{sum(1 for e in audit_rows if e['decision'] == 'Needs review')} needs review, "
        f"{sum(1 for e in audit_rows if e['decision'] == 'Rejected')} rejected"
    )
    for stats in source_stats:
        print(
            f"- {stats['name']}: "
            f"{stats['raw_entries']} raw, "
            f"{stats['new_channels_contributed']} new channels, "
            f"{stats['alternative_streams']} alternatives, "
            f"{stats['duplicate_urls_ignored']} duplicate URLs ignored"
        )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
