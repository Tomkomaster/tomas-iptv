from __future__ import annotations

import json
from pathlib import Path

ROOT = Path.cwd()


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"Expected exactly one match in {path}, found {count}: {old[:180]!r}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# ---------------------------------------------------------------------------
# Explicit cross-country EPG aliases. Automatic matching stays country-scoped.
# ---------------------------------------------------------------------------
(ROOT / "epg_cross_country_alias.py").write_text(
    r'''#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import date
from pathlib import Path

from epg_merge import (
    channel_index,
    fresh_count,
    load_xml,
    programme_index,
    read_playlist_rows,
)


COUNTRY_RE = re.compile(r"^[A-Z]{2}$")


def load_cross_country_aliases(
    path: Path | None,
) -> tuple[str, dict[str, dict[str, str]]]:
    """Load explicit aliases that intentionally read another country's guide.

    The existing flat ``aliases`` mapping remains handled by epg_merge and is
    therefore fully backward compatible. This separate section exists so a
    cross-country mapping can never happen by name/quality inference.
    """
    if path is None or not path.is_file():
        return "", {}

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("EPG alias file must contain a JSON object.")

    provider = str(data.get("provider") or "").strip()
    raw_aliases = data.get("cross_country_aliases") or {}
    if not isinstance(raw_aliases, dict):
        raise RuntimeError(
            "EPG alias file 'cross_country_aliases' must be a JSON object."
        )

    aliases: dict[str, dict[str, str]] = {}
    for raw_target, raw_spec in raw_aliases.items():
        target = str(raw_target or "").strip()
        if not target:
            raise RuntimeError("Cross-country EPG aliases may not have blank targets.")
        if not isinstance(raw_spec, dict):
            raise RuntimeError(
                f"Cross-country EPG alias {target!r} must contain an object."
            )

        playlist_country = str(
            raw_spec.get("playlist_country_code") or ""
        ).strip().upper()
        external_country = str(
            raw_spec.get("external_country_code") or ""
        ).strip().upper()
        external_id = str(raw_spec.get("external_id") or "").strip()

        if not COUNTRY_RE.fullmatch(playlist_country):
            raise RuntimeError(
                f"Cross-country EPG alias {target!r} has invalid "
                f"playlist_country_code {playlist_country!r}."
            )
        if not COUNTRY_RE.fullmatch(external_country):
            raise RuntimeError(
                f"Cross-country EPG alias {target!r} has invalid "
                f"external_country_code {external_country!r}."
            )
        if playlist_country == external_country:
            raise RuntimeError(
                f"Cross-country EPG alias {target!r} must reference a different "
                "external country. Use the normal 'aliases' section otherwise."
            )
        if not external_id:
            raise RuntimeError(
                f"Cross-country EPG alias {target!r} requires external_id."
            )

        aliases[target] = {
            "playlist_country_code": playlist_country,
            "external_country_code": external_country,
            "external_id": external_id,
        }

    return provider, aliases


def _external_path(
    external_dir: Path | None,
    country_code: str,
) -> Path | None:
    if external_dir is None:
        return None
    for name in (
        f"{country_code}.xml.gz",
        f"{country_code}.xml",
        f"{country_code}.download",
    ):
        candidate = external_dir / name
        if candidate.is_file():
            return candidate
    return None


def _load_external_country(
    external_dir: Path | None,
    country_code: str,
    cache: dict[str, dict],
) -> dict:
    if country_code in cache:
        return cache[country_code]

    path = _external_path(external_dir, country_code)
    if path is None:
        result = {"available": False, "error": "external guide not downloaded"}
        cache[country_code] = result
        return result

    try:
        root = load_xml(path)
        result = {
            "available": True,
            "path": path,
            "root": root,
            "channels": channel_index(root),
            "programmes": programme_index(root),
        }
    except Exception as exc:
        result = {
            "available": False,
            "path": path,
            "error": str(exc),
        }

    cache[country_code] = result
    return result


def apply_cross_country_aliases(
    *,
    country_code: str,
    playlist_path: Path,
    country_root: ET.Element,
    country_report: dict,
    aliases: dict[str, dict[str, str]],
    alias_provider: str,
    countries_cfg: dict,
    external_dir: Path | None,
    external_cache: dict[str, dict],
    reference_date: date | None,
    future_days: int,
) -> dict[str, object]:
    """Apply only explicit, fresh, cross-country EPG aliases.

    A target already mapped by its own country's normal deterministic matching
    is never replaced. An alias whose foreign EPG entry has no current/future
    programmes is intentionally left unmatched rather than inflating coverage
    with a mapped-but-empty channel.
    """
    code = str(country_code or "").strip().upper()
    playlist_ids = {
        tvg_id
        for tvg_id, _ in read_playlist_rows(playlist_path)
    }
    matched_items = [
        dict(item)
        for item in (country_report.get("matched") or [])
        if isinstance(item, dict)
    ]
    matched_ids = {
        str(item.get("tvg_id") or "").strip()
        for item in matched_items
        if str(item.get("tvg_id") or "").strip()
    }

    if reference_date is None:
        raw_reference = str(country_report.get("reference_date") or "").strip()
        reference_date = (
            date.fromisoformat(raw_reference)
            if raw_reference
            else date.today()
        )

    configured_targets = [
        target
        for target, spec in aliases.items()
        if spec.get("playlist_country_code") == code
    ]
    used: list[dict[str, object]] = []
    skipped: list[dict[str, object]] = []

    for target in configured_targets:
        if target not in playlist_ids or target in matched_ids:
            continue

        spec = aliases[target]
        source_code = spec["external_country_code"]
        external_id = spec["external_id"]
        source_cfg = countries_cfg.get(source_code) or {}
        if not isinstance(source_cfg, dict):
            source_cfg = {}
        source_external_cfg = source_cfg.get("external") or {}
        if not isinstance(source_external_cfg, dict):
            source_external_cfg = {}
        source_provider = str(
            source_external_cfg.get("provider") or "epgshare01.online"
        ).strip() or "epgshare01.online"

        if alias_provider and source_provider != alias_provider:
            raise RuntimeError(
                "Cross-country EPG alias provider mismatch for "
                f"{target}: alias file {alias_provider!r}, "
                f"{source_code} source {source_provider!r}."
            )

        source = _load_external_country(
            external_dir,
            source_code,
            external_cache,
        )
        if not source.get("available"):
            skipped.append({
                "tvg_id": target,
                "external_country_code": source_code,
                "provider_xmltv_id": external_id,
                "reason": str(source.get("error") or "external guide unavailable"),
            })
            continue

        source_channel = (source.get("channels") or {}).get(external_id)
        if source_channel is None:
            skipped.append({
                "tvg_id": target,
                "external_country_code": source_code,
                "provider_xmltv_id": external_id,
                "reason": "external XMLTV channel ID not present",
            })
            continue

        programmes = list((source.get("programmes") or {}).get(external_id, []))
        fresh_programmes = fresh_count(
            programmes,
            reference_date,
            max(int(future_days), 0),
        )
        if fresh_programmes <= 0:
            skipped.append({
                "tvg_id": target,
                "external_country_code": source_code,
                "provider_xmltv_id": external_id,
                "reason": "no current/future programme data",
            })
            continue

        channel_copy = copy.deepcopy(source_channel)
        channel_copy.set("id", target)
        country_root.append(channel_copy)

        seen_programmes: set[tuple[str, str, str]] = set()
        for programme in programmes:
            programme_copy = copy.deepcopy(programme)
            programme_copy.set("channel", target)
            key = (
                target,
                str(programme_copy.get("start") or ""),
                str(programme_copy.get("stop") or ""),
            )
            if key in seen_programmes:
                continue
            seen_programmes.add(key)
            country_root.append(programme_copy)

        match_item = {
            "tvg_id": target,
            "provider": source_provider,
            "provider_xmltv_id": external_id,
            "match_type": "external_explicit_cross_country_alias",
            "external_country_code": source_code,
            "fresh_programmes": fresh_programmes,
        }
        matched_items.append(match_item)
        matched_ids.add(target)
        used.append({
            "tvg_id": target,
            "external_country_code": source_code,
            "provider_xmltv_id": external_id,
            "fresh_programmes": fresh_programmes,
        })

        providers = Counter({
            str(provider): int(count or 0)
            for provider, count in (country_report.get("providers") or {}).items()
        })
        providers[source_provider] += 1
        country_report["providers"] = dict(sorted(providers.items()))

        fresh_providers = Counter({
            str(provider): int(count or 0)
            for provider, count in (
                country_report.get("fresh_channels_by_provider") or {}
            ).items()
        })
        fresh_providers[source_provider] += 1
        country_report["fresh_channels_by_provider"] = dict(
            sorted(fresh_providers.items())
        )

    country_report["matched"] = matched_items
    country_report["unmatched_tvg_ids"] = [
        tvg_id
        for tvg_id in (country_report.get("unmatched_tvg_ids") or [])
        if str(tvg_id).strip() not in matched_ids
    ]
    total = int(country_report.get("playlist_tvg_ids") or len(playlist_ids))
    mapped = len(matched_ids)
    country_report["matched_tvg_ids"] = mapped
    country_report["mapping_coverage_percent"] = round(
        mapped / total * 100.0 if total else 0.0,
        1,
    )

    external_info = country_report.get("external") or {}
    if not isinstance(external_info, dict):
        external_info = {}
    external_info["cross_country_aliases_configured"] = len(configured_targets)
    external_info["cross_country_aliases_used"] = used
    external_info["cross_country_aliases_skipped"] = skipped
    country_report["external"] = external_info

    return {
        "configured": len(configured_targets),
        "used": used,
        "skipped": skipped,
    }
''',
    encoding="utf-8",
)


# ---------------------------------------------------------------------------
# Extend multi-country orchestration without changing country-scoped matching.
# ---------------------------------------------------------------------------
epg_multi = ROOT / "epg_multi_merge.py"
replace_once(
    epg_multi,
    "from epg_merge import load_external_aliases, merge_guides\n",
    "from epg_cross_country_alias import (\n"
    "    apply_cross_country_aliases,\n"
    "    load_cross_country_aliases,\n"
    ")\n"
    "from epg_merge import load_external_aliases, merge_guides\n",
)
replace_once(
    epg_multi,
    '''    if not isinstance(country_outputs, dict):\n        raise RuntimeError("country_outputs must be a JSON object.")\n\n    combined_root = ET.Element(\n''',
    '''    if not isinstance(country_outputs, dict):\n        raise RuntimeError("country_outputs must be a JSON object.")\n\n    (\n        cross_alias_provider,\n        cross_country_aliases,\n    ) = load_cross_country_aliases(aliases_path)\n    cross_country_external_cache: dict[str, dict] = {}\n\n    combined_root = ET.Element(\n''',
)
replace_once(
    epg_multi,
    '''            if country_root.tag != "tv":\n                raise RuntimeError(f"Invalid country EPG root for {code}: {country_root.tag!r}")\n\n            for channel in country_root.findall("channel"):\n''',
    '''            if country_root.tag != "tv":\n                raise RuntimeError(f"Invalid country EPG root for {code}: {country_root.tag!r}")\n\n            apply_cross_country_aliases(\n                country_code=code,\n                playlist_path=playlist_path,\n                country_root=country_root,\n                country_report=country_report,\n                aliases=cross_country_aliases,\n                alias_provider=cross_alias_provider,\n                countries_cfg=countries_cfg,\n                external_dir=external_dir,\n                external_cache=cross_country_external_cache,\n                reference_date=reference_date,\n                future_days=max(future_days, 0),\n            )\n\n            for channel in country_root.findall("channel"):\n''',
)
replace_once(
    epg_multi,
    '''    explicit_aliases_configured = max(\n        [\n            int(info.get("explicit_aliases_configured") or 0)\n            for info in external_countries.values()\n        ]\n        or [0]\n    )\n\n    report = {\n''',
    '''    explicit_aliases_configured = max(\n        [\n            int(info.get("explicit_aliases_configured") or 0)\n            for info in external_countries.values()\n        ]\n        or [0]\n    )\n\n    cross_country_aliases_used: list[dict] = []\n    cross_country_aliases_skipped: list[dict] = []\n    for code, info in external_countries.items():\n        for raw_item in info.get("cross_country_aliases_used") or []:\n            item = dict(raw_item) if isinstance(raw_item, dict) else {"value": raw_item}\n            item.setdefault("country_code", code)\n            cross_country_aliases_used.append(item)\n        for raw_item in info.get("cross_country_aliases_skipped") or []:\n            item = dict(raw_item) if isinstance(raw_item, dict) else {"value": raw_item}\n            item.setdefault("country_code", code)\n            cross_country_aliases_skipped.append(item)\n\n    report = {\n''',
)
replace_once(
    epg_multi,
    '''            "explicit_aliases_configured": explicit_aliases_configured,\n            "ambiguous": ambiguous,\n            "countries": external_countries,\n''',
    '''            "explicit_aliases_configured": explicit_aliases_configured,\n            "cross_country_aliases_configured": len(cross_country_aliases),\n            "cross_country_aliases_used": cross_country_aliases_used,\n            "cross_country_aliases_skipped": cross_country_aliases_skipped,\n            "ambiguous": ambiguous,\n            "countries": external_countries,\n''',
)


# ---------------------------------------------------------------------------
# Expand only manually audited aliases with fresh current programme data.
# ---------------------------------------------------------------------------
alias_path = ROOT / "epg_aliases.json"
alias_data = json.loads(alias_path.read_text(encoding="utf-8"))
aliases = alias_data.setdefault("aliases", {})
aliases.update({
    "CanalPlusActionEurope.nl@Czechia": "CANAL.PLUS.ACTION.CZ.cz",
    "FILMBOXPlusComedy.pl@Czechia": "Filmbox+.comedy.cz",
    "FILMBOXPlusEmotion.pl@Czechia": "Filmbox+.emotion.cz",
    "FILMBOXPlusHits.pl@Czechia": "Filmbox+.hits.cz",
    "FILMBOXPlusOne.pl@Czechia": "Filmbox+.one.cz",
})
alias_data["cross_country_aliases"] = {
    "ducktvPLUS.sk@SD": {
        "playlist_country_code": "SK",
        "external_country_code": "CZ",
        "external_id": "ducktv.plus.cz",
    },
    "HAHATV.sk@SD": {
        "playlist_country_code": "SK",
        "external_country_code": "CZ",
        "external_id": "HaHa.TV.cz",
    },
    "PrimaKrimiSK.sk@HD": {
        "playlist_country_code": "SK",
        "external_country_code": "CZ",
        "external_id": "Prima.KRIMI.SK.cz",
    },
    "TVT.sk@SD": {
        "playlist_country_code": "SK",
        "external_country_code": "CZ",
        "external_id": "TVT.cz",
    },
    "ZapadoslovenskaTV.sk@SD": {
        "playlist_country_code": "SK",
        "external_country_code": "CZ",
        "external_id": "Západoslovenská.televízia.cz",
    },
}
alias_data["description"] = (
    "Explicit audited aliases from exact playlist tvg-id values to EPGshare "
    "XMLTV channel IDs. Runtime fuzzy matching is intentionally not used. "
    "cross_country_aliases may read another already-downloaded country guide "
    "only through an explicit country + XMLTV ID declaration."
)
alias_path.write_text(
    json.dumps(alias_data, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)


# ---------------------------------------------------------------------------
# Regression tests for explicit-only cross-country mapping and freshness gate.
# ---------------------------------------------------------------------------
(ROOT / "tests/test_epg_cross_country_alias.py").write_text(
    r'''import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

from epg_multi_merge import merge_country_guides


class CrossCountryEpgAliasTests(unittest.TestCase):
    def write_playlist(self, path: Path, tvg_id: str, name: str) -> None:
        path.write_text(
            "#EXTM3U\n"
            f'#EXTINF:-1 tvg-id="{tvg_id}",{name}\n'
            "https://example.test/stream.m3u8\n",
            encoding="utf-8",
        )

    def write_external(
        self,
        path: Path,
        channels: list[tuple[str, str, str, str]],
    ) -> None:
        root = ET.Element("tv")
        for channel_id, name, start, title in channels:
            channel = ET.SubElement(root, "channel", {"id": channel_id})
            display = ET.SubElement(channel, "display-name")
            display.text = name
            programme = ET.SubElement(
                root,
                "programme",
                {
                    "start": start,
                    "stop": start[:8] + "070000 +0200",
                    "channel": channel_id,
                },
            )
            title_node = ET.SubElement(programme, "title")
            title_node.text = title
        ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)

    def base_fixture(self, root: Path) -> tuple[Path, Path, Path, Path]:
        public = root / "public"
        public.mkdir()
        external = root / "external"
        external.mkdir()

        self.write_playlist(public / "sk.m3u", "Local.sk@SD", "Cross Demo")
        self.write_playlist(public / "cz.m3u", "Czech.cz@SD", "Czech Demo")
        self.write_external(
            external / "SK.xml",
            [("Other.SK", "Other Slovak", "20260811060000 +0200", "SK programme")],
        )
        self.write_external(
            external / "CZ.xml",
            [
                ("Cross.CZ", "Cross Demo", "20260811060000 +0200", "Cross programme"),
                ("Czech.CZ", "Czech Demo", "20260811060000 +0200", "Czech programme"),
            ],
        )

        config = {
            "country_outputs": {
                "SK": "public/sk.m3u",
                "CZ": "public/cz.m3u",
            },
            "epg": {
                "countries": {
                    code: {
                        "sites": ["example.test"],
                        "external": {
                            "provider": "epgshare01.online",
                            "url": f"https://example.test/{code}.xml.gz",
                        },
                    }
                    for code in ("SK", "CZ")
                }
            },
        }
        config_path = root / "config.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")

        iptv_guide = root / "iptv.xml"
        iptv_guide.write_text("<tv />\n", encoding="utf-8")
        iptv_coverage = root / "iptv.json"
        iptv_coverage.write_text(
            json.dumps({
                "matched": [],
                "countries": {
                    "SK": {"playlist_tvg_ids": 1, "matched_tvg_ids": 0},
                    "CZ": {"playlist_tvg_ids": 1, "matched_tvg_ids": 0},
                },
                "tvg_id_countries": {
                    "Local.sk@SD": "SK",
                    "Czech.cz@SD": "CZ",
                },
            }),
            encoding="utf-8",
        )
        return config_path, iptv_guide, iptv_coverage, external

    def run_merge(self, root: Path, aliases_path: Path | None) -> dict:
        config, guide, coverage, external = self.base_fixture(root)
        return merge_country_guides(
            config_path=config,
            iptv_guide_path=guide,
            iptv_coverage_path=coverage,
            external_dir=external,
            aliases_path=aliases_path,
            reference_date=date(2026, 8, 11),
            future_days=7,
            output_path=root / "guide.xml",
            report_path=root / "coverage.json",
        )

    def test_other_country_same_name_is_not_automatic(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            result = self.run_merge(root, None)
            self.assertIn("Local.sk@SD", result["unmatched_tvg_ids"])
            self.assertEqual(result["countries"]["SK"]["matched_tvg_ids"], 0)

    def test_explicit_cross_country_alias_maps_fresh_programmes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            aliases_path = root / "aliases.json"
            aliases_path.write_text(
                json.dumps({
                    "provider": "epgshare01.online",
                    "aliases": {},
                    "cross_country_aliases": {
                        "Local.sk@SD": {
                            "playlist_country_code": "SK",
                            "external_country_code": "CZ",
                            "external_id": "Cross.CZ",
                        }
                    },
                }),
                encoding="utf-8",
            )
            result = self.run_merge(root, aliases_path)

            self.assertNotIn("Local.sk@SD", result["unmatched_tvg_ids"])
            self.assertEqual(result["countries"]["SK"]["matched_tvg_ids"], 1)
            item = next(
                item
                for item in result["matched"]
                if item.get("tvg_id") == "Local.sk@SD"
            )
            self.assertEqual(
                item["match_type"],
                "external_explicit_cross_country_alias",
            )
            self.assertEqual(item["external_country_code"], "CZ")
            self.assertGreater(int(item["fresh_programmes"]), 0)
            self.assertEqual(result["external"]["cross_country_aliases_configured"], 1)
            self.assertEqual(len(result["external"]["cross_country_aliases_used"]), 1)

            guide = ET.parse(root / "guide.xml").getroot()
            titles = {
                programme.get("channel"): programme.findtext("title")
                for programme in guide.findall("programme")
            }
            self.assertEqual(titles["Local.sk@SD"], "Cross programme")

    def test_cross_country_alias_without_fresh_programmes_stays_unmapped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config, guide, coverage, external = self.base_fixture(root)
            self.write_external(
                external / "CZ.xml",
                [
                    ("Cross.CZ", "Cross Demo", "20260701060000 +0200", "Old programme"),
                    ("Czech.CZ", "Czech Demo", "20260811060000 +0200", "Czech programme"),
                ],
            )
            aliases_path = root / "aliases.json"
            aliases_path.write_text(
                json.dumps({
                    "provider": "epgshare01.online",
                    "cross_country_aliases": {
                        "Local.sk@SD": {
                            "playlist_country_code": "SK",
                            "external_country_code": "CZ",
                            "external_id": "Cross.CZ",
                        }
                    },
                }),
                encoding="utf-8",
            )
            result = merge_country_guides(
                config_path=config,
                iptv_guide_path=guide,
                iptv_coverage_path=coverage,
                external_dir=external,
                aliases_path=aliases_path,
                reference_date=date(2026, 8, 11),
                future_days=7,
                output_path=root / "guide.xml",
                report_path=root / "coverage.json",
            )
            self.assertIn("Local.sk@SD", result["unmatched_tvg_ids"])
            self.assertEqual(len(result["external"]["cross_country_aliases_used"]), 0)
            skipped = result["external"]["cross_country_aliases_skipped"]
            self.assertEqual(skipped[0]["reason"], "no current/future programme data")


if __name__ == "__main__":
    unittest.main()
''',
    encoding="utf-8",
)


# ---------------------------------------------------------------------------
# Document the policy and why mapping—not scraper expansion—is the current work.
# ---------------------------------------------------------------------------
doc = ROOT / "docs/multi-country-external-epg.md"
text = doc.read_text(encoding="utf-8")
addition = '''\n## Explicit alias policy\n\nAutomatic external matching remains country-scoped: HU playlist entries are inferred only against the HU external guide, SK only against SK, and CZ only against CZ. Runtime fuzzy matching is intentionally not used.\n\n`epg_aliases.json` is the audited exception layer. Normal `aliases` map an exact playlist `tvg-id` to an exact XMLTV ID in the same country's EPGshare guide. `cross_country_aliases` additionally declare both the playlist country and the external guide country. This is useful when EPGshare carries a station in a neighboring country's package but not in its geographic guide. Cross-country aliases are applied only when the declared external XMLTV ID has current/future programme data; stale or empty mappings remain unmatched rather than inflating coverage.\n\nThis keeps identification improvements deterministic and reviewable while leaving provider scraping unchanged.\n'''
if "## Explicit alias policy" not in text:
    doc.write_text(text.rstrip() + "\n" + addition, encoding="utf-8")
