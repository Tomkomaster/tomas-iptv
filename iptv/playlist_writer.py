from __future__ import annotations

from pathlib import Path
from typing import Callable


def playlist_header(cfg: dict) -> str:
    """Build the #EXTM3U header, including the configured XMLTV URL."""
    header = "#EXTM3U"
    epg = cfg.get("epg") or {}

    if not isinstance(epg, dict) or not bool(epg.get("enabled")):
        return header

    public_url = str(epg.get("public_url") or "").strip()
    if not public_url:
        return header

    safe_url = public_url.replace('"', "%22")
    return (
        f'{header} '
        f'url-tvg="{safe_url}" '
        f'x-tvg-url="{safe_url}"'
    )


def write_m3u_playlist(
    path: Path,
    cfg: dict,
    entries: list[dict],
    generated: str,
    playlist_label: str,
    name_style: str = "status",
    *,
    strip_custom_prefix: Callable[[str], str],
    normalize_country_code: Callable[[str], str],
    rewrite_entry_lines: Callable[[list[str], str, str], list[str]],
) -> None:
    """Write one generated M3U playlist without embedding a fake build version."""
    path.parent.mkdir(parents=True, exist_ok=True)

    out_lines = [
        playlist_header(cfg),
        f"# Generated automatically: {generated}",
        f"# Playlist: {playlist_label}",
        "",
    ]

    valid_name_styles = {
        "status",
        "language",
        "country",
        "plain",
    }
    if name_style not in valid_name_styles:
        raise ValueError(f"Unsupported playlist name_style: {name_style!r}")

    for entry in entries:
        entry_lines = entry["lines"]

        if name_style != "status":
            original_display = strip_custom_prefix(
                str(
                    entry.get("published_name")
                    or entry.get("display_name")
                    or "Unnamed channel"
                )
            )

            if name_style in {"language", "country"}:
                country_code = (
                    normalize_country_code(
                        str(
                            entry.get("country_code")
                            or entry.get("language_code")
                            or cfg.get("default_country_code")

                            or "HU"
                        )
                    )
                    or "HU"
                )
                output_name = f"[{country_code}] {original_display}"
            else:
                output_name = original_display

            entry_lines = rewrite_entry_lines(
                entry_lines,
                output_name,
                str(entry.get("group_title") or ""),
            )

        out_lines.extend(entry_lines)
        out_lines.append("")

    path.write_text(
        "\n".join(out_lines).rstrip() + "\n",
        encoding="utf-8",
    )
