#!/usr/bin/env python3
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=check, text=True)


def main() -> None:
    run("git", "config", "user.name", "github-actions[bot]")
    run(
        "git",
        "config",
        "user.email",
        "41898282+github-actions[bot]@users.noreply.github.com",
    )
    run("git", "fetch", "origin", "main")

    # Restore today's main audit byte-for-byte first.
    run("git", "checkout", "origin/main", "--", "audit.json")

    path = Path("audit.json")
    text = path.read_text(encoding="utf-8")

    pattern = re.compile(
        r'(    \{\n'
        r'      "channel": "DTV",\n'
        r'.*?'
        r'      "discovery": "Current IPTV-org Hungary playlist/manual test")'
        r'(\n    \},)',
        re.DOTALL,
    )

    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise SystemExit(
            f"Expected exactly one legacy DTV audit block; found {len(matches)}."
        )

    replacement = (
        matches[0].group(1)
        + ',\n'
        + '      "stream_url": "http://cloudfront44.lexanetwork.com:1732/'
          'hlsrelay003/hls/livestream.sdp.m3u8",\n'
        + '      "tvg_id": "DTV.hu@SD",\n'
        + '      "protocol": "HLS"'
        + matches[0].group(2)
    )
    text = text[: matches[0].start()] + replacement + text[matches[0].end() :]
    path.write_text(text, encoding="utf-8")
    run("git", "add", "audit.json")

    # Remove bytecode accidentally staged by the previous validation run.
    run(
        "git",
        "rm",
        "-r",
        "--ignore-unmatch",
        "__pycache__",
        "tests/__pycache__",
    )

    run("git", "diff", "--check")

    # Validate the cleaned audit against current live sources.
    run("python3", "build.py", "--strict")

    # Validation outputs are not source changes.
    shutil.rmtree("public", ignore_errors=True)
    shutil.rmtree("__pycache__", ignore_errors=True)
    shutil.rmtree("tests/__pycache__", ignore_errors=True)

    run("git", "add", "audit.json")
    run("git", "add", "-u")

    staged = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        text=True,
        check=False,
    )
    if staged.returncode == 0:
        print("Nothing to clean.")
        return
    if staged.returncode != 1:
        raise SystemExit(staged.returncode)

    run("git", "commit", "-m", "Clean PR #4 sync artifacts and minimize audit diff")
    run("git", "push", "origin", "HEAD:agent/audit-epg-health")


if __name__ == "__main__":
    main()
