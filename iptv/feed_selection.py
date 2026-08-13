#!/usr/bin/env python3
"""Current-feed and test-playlist candidate selection."""
from __future__ import annotations

from iptv.audit import audit_excluded, audit_rows_by_stream_url
from iptv.channel_identity import canonical_stream_url, logical_channel_key
from iptv.playback_status import normalize_test_status

def select_playlist_candidates(
    final_entries: list[dict],
    audit_rows: list[dict],
) -> tuple[list[dict], list[dict]]:
    """
    Select playlist feeds using exact stream URLs only.

    prepare_audit_rows() may convert a safe single-feed legacy audit into a
    URL-specific prepared row. Unmatched channel-level history is never used
    here as a fallback.
    """
    audit_by_url = audit_rows_by_stream_url(
        audit_rows
    )

    candidate_entries: list[dict] = []
    excluded_rows: list[dict] = []

    for source_order, entry in enumerate(final_entries):
        url = str(entry.get("url") or "").strip()
        url_key = canonical_stream_url(url)
        audit = audit_by_url.get(url_key)
        decision = audit.get("decision", "Needs review") if audit else "Needs review"
        exclude = audit_excluded(audit) if audit else False

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

    candidate_groups: dict[str, list[dict]] = {}
    for entry in candidate_entries:
        candidate_groups.setdefault(logical_channel_key(entry), []).append(entry)

    def verified_feed_rank(entry: dict) -> tuple:
        audit = entry.get("_audit") or {}
        vlc = normalize_test_status(str(audit.get("vlc") or ""))
        samsung = normalize_test_status(str(audit.get("samsung") or ""))

        vlc_rank = {
            "works": 3,
            "works_with_warning": 2,
        }.get(vlc, 0)

        samsung_rank = 1 if samsung == "works" else 0
        source_rank = -int(entry.get("_source_order") or 0)
        return (vlc_rank, samsung_rank, source_rank)

    selected_candidates: list[dict] = []

    for group in candidate_groups.values():
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
            selected_candidates.extend(group)

    return selected_candidates, excluded_rows

def make_test_playlist_candidates(
    final_entries: list[dict],
    audit_rows: list[dict],
) -> list[dict]:
    """
    Keep every current unique stream candidate in the testing playlist.

    Unlike the stable family playlist, test.m3u intentionally keeps:
      - Verified
      - TV verified
      - PC only
      - Needs review
      - Rejected
      - exclude_from_playlist feeds
      - alternative feeds

    Exact duplicate URLs have already been removed earlier in the build.
    """
    audit_by_url = audit_rows_by_stream_url(
        audit_rows
    )

    candidates: list[dict] = []

    for source_order, entry in enumerate(
        final_entries
    ):
        url = str(
            entry.get("url") or ""
        ).strip()

        audit = audit_by_url.get(
            canonical_stream_url(url)
        )

        decision = (
            audit.get(
                "decision",
                "Needs review",
            )
            if audit
            else "Needs review"
        )

        candidate = dict(entry)

        candidate["_audit"] = (
            audit or {}
        )

        candidate["_decision"] = (
            decision
        )

        candidate["_source_order"] = (
            source_order
        )

        candidates.append(
            candidate
        )

    return candidates
