#!/usr/bin/env python3
"""Shared VLC/Samsung playback-status normalization for Tomas IPTV.

This deliberately tiny module prevents language-routing and audit code from
having to import each other just to interpret manual playback test values.
"""
from __future__ import annotations

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
