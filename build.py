#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def download_text(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 Tomas-IPTV-Playlist-Builder/1.0",
            "Accept": "*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=45) as response:
        data = response.read()
    text = data.decode("utf-8-sig", errors="replace")
    if "#EXTM3U" not in text[:500]:
        raise RuntimeError(f"Source did not look like an M3U playlist: {url}")
    return text

def read_local(path: str) -> str:
    p = ROOT / path
    if not p.exists():
        return "#EXTM3U\n"
    return p.read_text(encoding="utf-8-sig")

def parse_entries(text: str):
    """
    Preserve each M3U entry, including lines such as #EXTVLCOPT.
    De-duplicate only identical stream URLs so alternate feeds are not
    accidentally removed.
    """
    lines = [line.rstrip("\r") for line in text.splitlines()]
    entries = []
    current = None

    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#EXTM3U"):
            continue

        if line.startswith("#EXTINF:"):
            if current and current.get("url"):
                entries.append(current)
            current = {"lines": [raw], "url": None}
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

def main():
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))

    all_entries = []
    source_status = []

    # Base playlists first.
    for url in cfg.get("sources", []):
        print(f"Downloading {url}")
        text = download_text(url)
        entries = parse_entries(text)
        if not entries:
            raise RuntimeError(f"No playable entries found in base source: {url}")
        all_entries.extend(entries)
        source_status.append((url, len(entries)))

    # Then our manually curated extras.
    for path in cfg.get("extras", []):
        print(f"Reading {path}")
        text = read_local(path)
        entries = parse_entries(text)
        all_entries.extend(entries)
        source_status.append((path, len(entries)))

    # Exact-URL deduplication only.
    seen = set()
    merged = []
    for entry in all_entries:
        url = (entry.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        merged.append(entry)

    out_path = ROOT / cfg.get("output", "public/tv.m3u")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    out_lines = [
        "#EXTM3U",
        f"# Generated automatically: {generated}",
        "# Base: IPTV-org Hungary + manually curated official/public extras",
        "",
    ]

    for entry in merged:
        out_lines.extend(entry["lines"])
        out_lines.append("")

    out_path.write_text("\n".join(out_lines).rstrip() + "\n", encoding="utf-8")

    # A tiny landing/status page for humans.
    index = ROOT / "public" / "index.html"
    source_html = "".join(
        f"<li><code>{src}</code> — {count} entries</li>"
        for src, count in source_status
    )
    index.write_text(
        f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tomas IPTV</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:760px;margin:40px auto;padding:0 18px;line-height:1.5}}
code{{overflow-wrap:anywhere}}
a{{font-weight:700}}
</style>
</head>
<body>
<h1>Tomas IPTV</h1>
<p>Current test playlist: <strong>Hungary</strong>.</p>
<p><a href="tv.m3u">Open/download tv.m3u</a></p>
<p>Generated: {generated}</p>
<p>Total stream entries: {len(merged)}</p>
<ul>{source_html}</ul>
</body>
</html>
""",
        encoding="utf-8",
    )

    print(f"Wrote {out_path} with {len(merged)} unique stream URLs.")

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
