"""Single-channel playlist selectors built from the stable published entries."""
from __future__ import annotations

from iptv.channel_identity import normalize_text, strip_custom_prefix, strip_display_annotations


def select_prima_cool_cz_entries(entries: list[dict]) -> list[dict]:
    """Pick just Czech Prima Cool from the already-selected stable channels.

    Use the canonical TV guide ID where possible and fall back to the
    published channel name. Never include the separate Slovak Prima Cool SK.
    """
    matches = []
    for entry in entries:
        if str(entry.get("country_code") or "").strip().upper() != "CZ":
            continue

        tvg_id = str(entry.get("tvg_id") or "").strip().casefold().split("@", 1)[0]
        published_name = str(
            entry.get("published_name") or entry.get("display_name") or ""
        )
        clean_name = normalize_text(
            strip_display_annotations(strip_custom_prefix(published_name))
        )
        if tvg_id == "primacool.cz" or clean_name == "prima cool":
            matches.append(entry)

    # A single-channel playlist must never publish more than one feed.
    return matches[:1]


