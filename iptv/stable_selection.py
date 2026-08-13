#!/usr/bin/env python3
"""Stable family-playlist filtering and best-feed choice.

The scorer, quality-context builder and routing/candidate functions are injected
by build_core at call time. That deliberately preserves the historical runtime
monkeypatch contract used by same-build verified-feed failover.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from iptv.audit import audit_excluded
from iptv.channel_identity import logical_channel_key

def stable_block_reason(
    entry: dict,
    cfg: dict,
) -> str:
    """
    Return a reason when a stream is never suitable for the stable
    family playlist even if somebody accidentally marks it Verified.

    The stream still remains available in test.m3u.
    """
    stable_cfg = (
        cfg.get("stable_playlist")
        or {}
    )

    blocked_hosts = [
        str(value).strip().casefold()
        for value in (
            stable_cfg.get(
                "blocked_hosts"
            )
            or [
                "youtube.com",
                "youtube-nocookie.com",
                "youtu.be",
                "googlevideo.com",
                "ythls.onrender.com",
            ]
        )
        if str(value).strip()
    ]

    url = str(
        entry.get("url") or ""
    ).strip()

    hostname = (
        urlparse(url).hostname
        or ""
    ).casefold()

    for blocked_host in blocked_hosts:
        if (
            hostname == blocked_host
            or hostname.endswith(
                "." + blocked_host
            )
        ):
            return (
                "Test-only stream host: "
                f"{hostname}"
            )

    blocked_flags = {
        str(value).strip().casefold()
        for value in (
            stable_cfg.get(
                "blocked_source_flags"
            )
            or ["Offline"]
        )
        if str(value).strip()
    }

    entry_flags = {
        str(value).strip().casefold()
        for value in (
            entry.get(
                "source_flags"
            )
            or []
        )
        if str(value).strip()
    }

    matching_flags = (
        blocked_flags
        & entry_flags
    )

    if matching_flags:
        return (
            "Blocked source flag: "
            + ", ".join(
                sorted(
                    matching_flags
                )
            )
        )

    blocked_terms = [
        str(value).strip().casefold()
        for value in (
            stable_cfg.get(
                "blocked_name_terms"
            )
            or [
                "webcam",
                "web cam",
                "camera",
                "kamera",
                "időkép",
                "idokep",
            ]
        )
        if str(value).strip()
    ]

    searchable_text = " ".join(
        str(
            entry.get(field)
            or ""
        )
        for field in (
            "channel_name",
            "display_name",
            "tvg_name",
            "group_title",
            "source_group_title",
            "source",
        )
    ).casefold()

    for term in blocked_terms:
        if re.search(
            rf"(?<!\w){re.escape(term)}(?!\w)",
            searchable_text,
            flags=re.IGNORECASE,
        ):
            return (
                "Test-only channel type: "
                f"{term}"
            )

    return ""

def select_stable_playlist_candidates(
    final_entries: list[dict],
    audit_rows: list[dict],
    cfg: dict,
    *,
    make_test_candidates,
    route_candidates,
    build_quality_context,
    score_quality,
) -> tuple[
    list[dict],
    list[dict],
]:
    """
    Select the family-safe playlist.

    Only explicitly TV-safe decisions are accepted:
      - Verified
      - TV verified

    PC-only, Needs-review, Rejected, explicitly excluded, YouTube,
    webcam/camera and Offline feeds remain outside tv.m3u.

    Only one best stable feed is published for each logical channel.
    """
    stable_cfg = (
        cfg.get("stable_playlist")
        or {}
    )

    quality_context = (
        build_quality_context(
            cfg
        )
    )

    allowed_decisions = {
        str(value).strip()
        for value in (
            stable_cfg.get(
                "allowed_decisions"
            )
            or [
                "Verified",
                "TV verified",
            ]
        )
        if str(value).strip()
    }

    all_candidates = (
        route_candidates(
            make_test_candidates(
                final_entries,
                audit_rows,
            ),
            cfg,
        )
    )

    stable_groups: dict[
        str,
        list[dict],
    ] = {}

    excluded_rows: list[dict] = []

    def add_excluded(
        entry: dict,
        reason: str,
    ) -> None:
        excluded_rows.append({
            "channel_name": entry.get(
                "channel_name",
                "",
            ),
            "tvg_id": entry.get(
                "tvg_id",
                "",
            ),
            "source": entry.get(
                "source",
                "",
            ),
            "stream_url": entry.get(
                "url",
                "",
            ),
            "reason": reason,
        })

    for entry in all_candidates:
        audit = (
            entry.get("_audit")
            or {}
        )

        decision = entry.get(
            "_decision",
            "Needs review",
        )

        if audit_excluded(audit):
            add_excluded(
                entry,
                (
                    audit.get("reason")
                    or audit.get("notes")
                    or (
                        "Explicitly excluded "
                        "from stable family playlist."
                    )
                ),
            )
            continue

        if decision == "Rejected":
            add_excluded(
                entry,
                (
                    audit.get("reason")
                    or audit.get("notes")
                    or (
                        "Rejected by manual "
                        "playback/language audit."
                    )
                ),
            )
            continue

        if (
            decision
            not in allowed_decisions
        ):
            add_excluded(
                entry,
                (
                    "Not stable yet: "
                    f"{decision}"
                ),
            )
            continue

        block_reason = (
            stable_block_reason(
                entry,
                cfg,
            )
        )

        if block_reason:
            add_excluded(
                entry,
                block_reason,
            )
            continue

        stable_groups.setdefault(
            logical_channel_key(entry),
            [],
        ).append(
            entry
        )

    def stable_feed_rank(
        entry: dict,
    ) -> tuple:
        quality = score_quality(
            entry,
            cfg,
            context=quality_context,
        )

        entry[
            "_feed_quality_score"
        ] = int(
            quality.get("score")
            or 0
        )

        entry[
            "_feed_quality_summary"
        ] = str(
            quality.get("summary")
            or ""
        )

        source_rank = -int(
            entry.get(
                "_source_order"
            )
            or 0
        )

        return (
            entry[
                "_feed_quality_score"
            ],
            source_rank,
        )

    selected: list[dict] = []

    for group in stable_groups.values():
        winner = max(
            group,
            key=stable_feed_rank,
        )

        selected.append(
            winner
        )

        winner_score = int(
            winner.get(
                "_feed_quality_score"
            )
            or 0
        )

        for entry in group:
            if entry is winner:
                continue

            entry_score = int(
                entry.get(
                    "_feed_quality_score"
                )
                or 0
            )

            add_excluded(
                entry,
                (
                    "Another stable feed for "
                    "this logical channel was "
                    "ranked higher by feed-quality "
                    f"score (winner {winner_score}; "
                    f"this feed {entry_score})."
                ),
            )

    return (
        selected,
        excluded_rows,
    )
