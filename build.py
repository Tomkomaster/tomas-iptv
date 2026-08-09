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
    if not p.exists():
        return "#EXTM3U\n"
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
    value = (value or "").strip().casefold().replace(" ", "_")
    aliases = {
        "ok": "works",
        "working": "works",
        "pass": "works",
        "passed": "works",
        "yes": "works",
        "error": "fails",
        "failed": "fails",
        "fail": "fails",
        "no": "fails",
        "pending": "not_tested",
        "untested": "not_tested",
        "not-tested": "not_tested",
        "": "not_tested",
    }
    return aliases.get(value, value)


def calculate_audit_decision(item: dict) -> tuple[str, str]:
    """
    Return (decision, explanation).

    "Verified" means manually verified for OUR playlist:
    - works in VLC
    - works on Samsung
    - language is not known to be wrong

    Provenance remains a separate field. "Verified" is NOT a legal certification.
    """
    explicit = (item.get("decision") or "auto").strip().casefold().replace(" ", "_")
    if explicit in {"verified", "needs_review", "rejected"}:
        label = {
            "verified": "Verified",
            "needs_review": "Needs review",
            "rejected": "Rejected",
        }[explicit]
        return label, str(item.get("reason") or "").strip()

    vlc = normalize_test_status(str(item.get("vlc", "")))
    samsung = normalize_test_status(str(item.get("samsung", "")))
    language = (item.get("language") or "Unknown").strip().casefold()

    wrong_languages = {
        "english", "wrong", "wrong language", "not hungarian",
        "non-hungarian", "not_hungarian"
    }

    if language in wrong_languages:
        return "Rejected", "Wrong language for the Hungarian playlist."

    if vlc == "fails":
        return "Rejected", "Fails the VLC playback test."

    if samsung == "fails":
        return "Rejected", "Fails the Samsung playback test."

    if vlc == "works" and samsung == "works":
        return "Verified", ""

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
    Automatically create a manual-test row for EVERY stream in the final playlist,
    then overlay saved results from audit.json.

    audit.json therefore only needs to contain channels we have actually reviewed
    plus candidates/rejected channels that are not currently in the playlist.
    """
    manual_by_url: dict[str, dict] = {}
    manual_by_tvg_id: dict[str, dict] = {}
    manual_by_name: dict[str, dict] = {}

    for raw in audit_items:
        item = dict(raw)
        url = str(item.get("stream_url") or "").strip()
        tvg_id = normalized_tvg_id(str(item.get("tvg_id") or ""))
        name = normalize_text(str(item.get("channel") or ""))

        if url:
            manual_by_url[url] = item
        if tvg_id:
            manual_by_tvg_id[tvg_id] = item
        if name:
            manual_by_name[name] = item

    used_manual_ids: set[int] = set()
    rows: list[dict] = []

    for entry in final_entries:
        url = str(entry.get("url") or "").strip()
        tvg_id = str(entry.get("tvg_id") or "").strip()
        clean_name = str(entry.get("channel_name") or entry.get("display_name") or "Unnamed channel").strip()

        manual = None
        if url and url in manual_by_url:
            manual = manual_by_url[url]
        elif normalized_tvg_id(tvg_id) and normalized_tvg_id(tvg_id) in manual_by_tvg_id:
            manual = manual_by_tvg_id[normalized_tvg_id(tvg_id)]
        elif normalize_text(clean_name) in manual_by_name:
            manual = manual_by_name[normalize_text(clean_name)]

        default_provenance = (
            "Our curated extra"
            if entry.get("source_kind") == "extras"
            else "IPTV-org source (unreviewed)"
        )

        item = {
            "channel": clean_name,
            "tvg_id": tvg_id,
            "source": str(entry.get("source") or ""),
            "discovery": str(entry.get("source") or "Current playlist"),
            "stream_url": url,
            "protocol": infer_protocol(url),
            "language": "Unknown",
            "provenance": default_provenance,
            "vlc": "not_tested",
            "samsung": "not_tested",
            "decision": "auto",
            "reason": "",
            "notes": "Auto-added from current tv.m3u for manual testing.",
        }

        if manual is not None:
            used_manual_ids.add(id(manual))
            # Manual values override defaults, but empty strings do not erase useful
            # automatically-derived fields such as URL/source/protocol.
            for key, value in manual.items():
                if value not in ("", None):
                    item[key] = value

        decision, auto_reason = calculate_audit_decision(item)

        rows.append({
            "channel": str(item.get("channel") or clean_name).strip(),
            "tvg_id": str(item.get("tvg_id") or tvg_id).strip(),
            "source": str(item.get("source") or entry.get("source") or "").strip(),
            "discovery": str(item.get("discovery") or entry.get("source") or "").strip(),
            "stream_url": str(item.get("stream_url") or url).strip(),
            "protocol": str(item.get("protocol") or infer_protocol(url)).strip(),
            "language": str(item.get("language") or "Unknown").strip(),
            "provenance": str(item.get("provenance") or default_provenance).strip(),
            "vlc": normalize_test_status(str(item.get("vlc") or "")),
            "samsung": normalize_test_status(str(item.get("samsung") or "")),
            "decision": decision,
            "reason": str(item.get("reason") or auto_reason or "").strip(),
            "notes": str(item.get("notes") or "").strip(),
            "in_playlist": True,
        })

    # Keep manually tracked candidates/rejections that are not currently in tv.m3u.
    final_urls = {(e.get("url") or "").strip() for e in final_entries if e.get("url")}
    final_tvg_ids = {
        normalized_tvg_id(str(e.get("tvg_id") or ""))
        for e in final_entries if normalized_tvg_id(str(e.get("tvg_id") or ""))
    }
    final_names = {
        normalize_text(str(e.get("channel_name") or e.get("display_name") or ""))
        for e in final_entries
    }

    for raw in audit_items:
        if id(raw) in used_manual_ids:
            continue

        item = dict(raw)
        url = str(item.get("stream_url") or "").strip()
        tvg_id = normalized_tvg_id(str(item.get("tvg_id") or ""))
        name = normalize_text(str(item.get("channel") or ""))

        # If it matches a current item by another key, don't duplicate it.
        if (url and url in final_urls) or (tvg_id and tvg_id in final_tvg_ids) or (name and name in final_names):
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
            "provenance": str(item.get("provenance") or "Unknown").strip(),
            "vlc": normalize_test_status(str(item.get("vlc") or "")),
            "samsung": normalize_test_status(str(item.get("samsung") or "")),
            "decision": decision,
            "reason": str(item.get("reason") or auto_reason or "").strip(),
            "notes": str(item.get("notes") or "").strip(),
            "in_playlist": False,
        })

    # Testing queue first: not-tested/current items, then partial tests, then verified,
    # then rejected. Alphabetical inside each bucket.
    def progress_rank(row: dict) -> int:
        if row["decision"] == "Rejected":
            return 4
        if row["decision"] == "Verified":
            return 3
        if row["vlc"] == "not_tested" and row["samsung"] == "not_tested":
            return 0
        return 1

    return sorted(
        rows,
        key=lambda x: (
            progress_rank(x),
            0 if x["in_playlist"] else 1,
            normalize_text(x["channel"]),
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
    audit_review = sum(1 for e in audit_rows if e["decision"] == "Needs review")
    audit_rejected = sum(1 for e in audit_rows if e["decision"] == "Rejected")
    audit_current = [e for e in audit_rows if e["in_playlist"]]
    audit_both_tested = sum(
        1 for e in audit_current
        if e["vlc"] in {"works", "fails"} and e["samsung"] in {"works", "fails"}
    )
    audit_vlc_pending = sum(1 for e in audit_current if e["vlc"] == "not_tested")
    audit_samsung_pending = sum(1 for e in audit_current if e["samsung"] == "not_tested")

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
            "fails": ("✕ Fails", "rejected"),
            "not_tested": ("? Not tested", "review"),
            "n/a": ("N/A", "base"),
        }
        label, css = labels.get(value, (value or "?", "review"))
        return f'<span class="badge {css}">{esc(label)}</span>'

    audit_table_rows = []
    for a in audit_rows:
        decision_css = {
            "Verified": "verified",
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
              <td>{esc(a.get("tvg_id", "") or "—")}</td>
              <td>{esc(a.get("source", "") or "—")}</td>
              <td>{esc(a["discovery"])}</td>
              <td>{esc(a["protocol"] or "—")}</td>
              <td>{esc(a["language"])}</td>
              <td>{esc(a["provenance"])}</td>
              <td>{test_badge(a["vlc"])}</td>
              <td>{test_badge(a["samsung"])}</td>
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
    This is our persistent test log. “Verified” means we have accepted the stream
    for this shared playlist after playback/device checks and provenance review;
    it is not a legal certification.
  </p>

  <div class="audit-summary">
    <div class="card"><div class="value">{len(audit_current)}</div><div class="label">Channels/streams in testing queue</div></div>
    <div class="card"><div class="value">{audit_both_tested}</div><div class="label">Tested on both devices</div></div>
    <div class="card"><div class="value">{audit_vlc_pending}</div><div class="label">VLC tests remaining</div></div>
    <div class="card"><div class="value">{audit_samsung_pending}</div><div class="label">Samsung tests remaining</div></div>
    <div class="card"><div class="value">{audit_verified}</div><div class="label">✓ Verified</div></div>
    <div class="card"><div class="value">{audit_review}</div><div class="label">? Needs review</div></div>
    <div class="card"><div class="value">{audit_rejected}</div><div class="label">✕ Rejected</div></div>
  </div>

  <div class="controls">
    <input id="auditSearch" type="search" placeholder="Search manual tests...">
    <select id="auditDecisionFilter">
      <option value="">All manual decisions</option>
      <option value="Verified">Verified</option>
      <option value="Needs review">Needs review</option>
      <option value="Rejected">Rejected</option>
    </select>
    <select id="auditVlcFilter">
      <option value="">All VLC statuses</option>
      <option value="works">VLC works</option>
      <option value="fails">VLC fails</option>
      <option value="not_tested">VLC not tested</option>
    </select>
    <select id="auditSamsungFilter">
      <option value="">All Samsung statuses</option>
      <option value="works">Samsung works</option>
      <option value="fails">Samsung fails</option>
      <option value="not_tested">Samsung not tested</option>
    </select>
  </div>
  <p id="auditVisibleCount" class="muted"></p>

  <div class="table-wrap">
    <table id="auditTable">
      <thead>
        <tr>
          <th>Channel</th>
          <th>TVG ID</th>
          <th>Source</th>
          <th>Discovery</th>
          <th>Protocol</th>
          <th>Language</th>
          <th>Provenance</th>
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

    by_channel: dict[str, dict] = {}
    for entry in final_entries:
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
        "# Tomas IPTV smart builder v4",
        "",
    ]
    for entry in final_entries:
        out_lines.extend(entry["lines"])
        out_lines.append("")
    out_path.write_text("\n".join(out_lines).rstrip() + "\n", encoding="utf-8")

    inventory_rows = [
        {
            "channel_name": e["channel_name"],
            "tvg_id": e.get("tvg_id", ""),
            "group_title": e.get("group_title", ""),
            "source": e["source"],
            "classification": e["classification"],
            "stream_url": e["url"],
            "logo": e.get("logo", ""),
        }
        for e in final_entries
    ]
    write_csv(
        public_dir / "channels.csv",
        ["channel_name", "tvg_id", "group_title", "source", "classification", "stream_url", "logo"],
        inventory_rows,
    )

    write_csv(
        public_dir / "duplicates.csv",
        ["channel_name", "tvg_id", "source", "stream_url", "already_kept_from", "already_kept_as"],
        duplicate_rows,
    )

    write_csv(
        public_dir / "audit.csv",
        [
            "channel", "tvg_id", "source", "discovery", "stream_url", "protocol", "language",
            "provenance", "vlc", "samsung", "decision", "in_playlist",
            "reason", "notes"
        ],
        audit_rows,
    )

    report = {
        "schema_version": 4,
        "generated_at": generated,
        "summary": {
            "unique_channels": len(unique_channels),
            "unique_stream_urls": len(final_entries),
            "added_channels_beyond_base": sum(
                1 for e in final_entries if e["classification"] == "Added channel"
            ),
            "alternative_streams": sum(
                1 for e in final_entries if e["classification"] == "Alternative stream"
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
                    and e["vlc"] in {"works", "fails"}
                    and e["samsung"] in {"works", "fails"}
                ),
                "verified": sum(1 for e in audit_rows if e["decision"] == "Verified"),
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
            final_entries=final_entries,
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
    print(f"Unique stream URLs:     {len(final_entries)}")
    print(f"Duplicate URLs ignored: {len(duplicate_rows)}")
    print(
        "Manual audit:          "
        f"{sum(1 for e in audit_rows if e['decision'] == 'Verified')} verified, "
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
