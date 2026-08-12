from __future__ import annotations

import json
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


path = Path("build.py")
text = path.read_text(encoding="utf-8")

# Keep the existing audit helper API backward-compatible: historical audit
# language lists still expose HU/SK/CZ-style tokens. The new authoritative
# channel/source language_codes field is ISO-639-3 and is normalized separately.
text = replace_once(
    text,
    '''def normalize_language_codes(value) -> list[str]:
    """Normalize spoken-language lists to ISO-639-3 while accepting legacy values."""
    return normalize_spoken_language_codes(value)
''',
    '''def normalize_language_codes(value) -> list[str]:
    """Normalize legacy audit-language values while preserving their API."""
    if value is None:
        return []
    if isinstance(value, str):
        values = [
            part.strip()
            for part in re.split(r"[,;/+]", value)
            if part.strip()
        ]
    elif isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        values = [value]
    result: list[str] = []
    for raw in values:
        code = normalize_language_code(str(raw or ""))
        if code and code not in result:
            result.append(code)
    return result
''',
    "legacy normalize_language_codes",
)

# New language_codes are always real spoken-language metadata.
text = text.replace(
    'normalize_language_codes(entry.get("language_codes"))',
    'normalize_spoken_language_codes(entry.get("language_codes"))',
)
text = text.replace(
    'normalize_language_codes(source.get("language_codes"))',
    'normalize_spoken_language_codes(source.get("language_codes"))',
)
text = text.replace(
    'identity_languages = normalize_language_codes(raw_identity_languages)',
    'identity_languages = normalize_spoken_language_codes(raw_identity_languages)',
)
text = text.replace(
    '"language_codes": normalize_language_codes(\n                entry.get("language_codes") or expected_codes\n            ),',
    '"language_codes": normalize_spoken_language_codes(\n                entry.get("language_codes") or expected_codes\n            ),',
)
text = text.replace(
    'legacy_code = normalize_spoken_language_code(\n                str(item.get("language_code") or "")\n            )',
    'legacy_code = normalize_language_code(\n                str(item.get("language_code") or "")\n            )',
)

# Compare legacy and modern language tokens through the ISO-639-3 layer.
text = replace_once(
    text,
    '''    expected = set(expected_codes)
    observed = set(observed_codes)

    if not expected.intersection(observed):
''',
    '''    expected = set(normalize_spoken_language_codes(expected_codes))
    observed = set(normalize_spoken_language_codes(observed_codes))

    if not expected.intersection(observed):
''',
    "derive_language_match",
)
text = replace_once(
    text,
    '''    supported = normalize_language_codes(
        supported_language_codes
    )

    if language_match in {
''',
    '''    supported = normalize_spoken_language_codes(
        supported_language_codes
    )
    observed_supported = normalize_spoken_language_codes(observed_codes)

    if language_match in {
''',
    "language acceptance support",
)
text = text.replace(
    'and set(observed_codes).intersection(\n                supported\n            )',
    'and set(observed_supported).intersection(\n                supported\n            )',
    1,
)

# Old isolated configs without the new route table retain the project's
# historical HU/SK/CZ one-to-one behavior. Migrated production config uses
# explicit verified_country_routes and therefore does not generalize
# language -> country for future countries.
text = replace_once(
    text,
    '''    routed = verified_country_route(
        cfg,
        source_code,
        audit_row.get("observed_language_codes"),
    )
''',
    '''    if "verified_country_routes" not in cfg:
        return verified_output_language_code(
            audit_row,
            source_code,
            configured_playlist_country_codes(cfg),
        )

    routed = verified_country_route(
        cfg,
        source_code,
        audit_row.get("observed_language_codes"),
    )
''',
    "verified country route compatibility",
)
text = text.replace(
    'observed = normalize_language_codes(audit_row.get("observed_language_codes"))',
    'observed = normalize_spoken_language_codes(audit_row.get("observed_language_codes"))',
    1,
)

# Preserve the existing public make_dashboard() call shape. New country_stats
# is derived when older callers/tests omit it.
text = replace_once(
    text,
    '''    source_stats: list[dict],
    country_stats: list[dict],
    language_stats: list[dict],
    duplicate_rows: list[dict],
    changes: dict,
    audit_rows: list[dict],
    audit_ambiguity_warnings: list[str],
) -> str:
    """Render the dashboard through the standalone presentation layer."""
    return render_dashboard(
''',
    '''    source_stats: list[dict],
    language_stats: list[dict],
    duplicate_rows: list[dict],
    changes: dict,
    audit_rows: list[dict],
    audit_ambiguity_warnings: list[str],
    country_stats: list[dict] | None = None,
) -> str:
    """Render the dashboard through the standalone presentation layer."""
    if country_stats is None:
        country_stats = summarize_country_stats(final_entries, source_stats)
    return render_dashboard(
''',
    "make_dashboard compatibility signature",
)

path.write_text(text, encoding="utf-8")

# Keep canonical identity's old language_code alias readable while the new
# country_code/language_codes fields are authoritative.
identity_path = Path("identity_overrides.json")
identity_data = json.loads(identity_path.read_text(encoding="utf-8"))
for identity in (identity_data.get("identities") or {}).values():
    if (
        isinstance(identity, dict)
        and identity.get("country_code")
        and not identity.get("language_code")
    ):
        identity["language_code"] = identity["country_code"]
identity_path.write_text(
    json.dumps(identity_data, indent=2, ensure_ascii=False) + "\n",
    encoding="utf-8",
)

# The old report test intentionally used report["languages"] as a country
# summary. After the separation it must test both dimensions independently.
test_path = Path("tests/test_build.py")
test_text = test_path.read_text(encoding="utf-8")
test_text = replace_once(
    test_text,
    '''            language_stats = {
                row["language_code"]: row
                for row in report["languages"]
            }

            self.assertEqual(
                language_stats["HU"][
                    "unique_channels"
                ],
                2,
            )

            self.assertEqual(
                language_stats["HU"][
                    "base_channels"
                ],
                1,
            )

            self.assertEqual(
                language_stats["HU"][
                    "added_channels"
                ],
                1,
            )

            self.assertEqual(
                language_stats["SK"][
                    "unique_channels"
                ],
                1,
            )

            self.assertEqual(
                language_stats["SK"][
                    "base_channels"
                ],
                1,
            )
''',
    '''            country_stats = {
                row["country_code"]: row
                for row in report["countries"]
            }
            language_stats = {
                row["language_code"]: row
                for row in report["languages"]
            }

            self.assertEqual(
                country_stats["HU"]["unique_channels"],
                2,
            )
            self.assertEqual(
                country_stats["HU"]["base_channels"],
                1,
            )
            self.assertEqual(
                country_stats["HU"]["added_channels"],
                1,
            )
            self.assertEqual(
                country_stats["SK"]["unique_channels"],
                1,
            )
            self.assertEqual(
                country_stats["SK"]["base_channels"],
                1,
            )

            self.assertEqual(
                language_stats["hun"]["unique_channels"],
                2,
            )
            self.assertEqual(
                language_stats["slk"]["unique_channels"],
                1,
            )
''',
    "report summary test",
)
test_path.write_text(test_text, encoding="utf-8")

print("country/language compatibility patches applied")
