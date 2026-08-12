from __future__ import annotations

import json
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


build_path = Path("build.py")
build = build_path.read_text(encoding="utf-8")

build = replace_once(
    build,
    '''def audit_excluded(item: dict) -> bool:\n    """Return True only for the literal JSON boolean true."""\n    return item.get("exclude_from_playlist") is True\n\n\ndef validate_audit_items(''',
    '''def audit_excluded(item: dict) -> bool:\n    """Return True only for the literal JSON boolean true."""\n    return item.get("exclude_from_playlist") is True\n\n\ndef exact_url_audit_matches_entry(\n    audit_item: dict,\n    entry: dict,\n) -> bool:\n    """\n    Return whether an exact-URL audit is safe to attach to this entry.\n\n    Exact URLs remain the primary feed identity, but a saved audit that\n    explicitly names its expected playlist language/country must never jump\n    to a current entry scoped to a disjoint language/country. This protects\n    against upstream metadata reusing the same URL for a differently\n    identified channel, while legacy URL-specific audits without explicit\n    expected_language_codes keep their existing behavior.\n    """\n    audit_expected = normalize_language_codes(\n        audit_item.get("expected_language_codes")\n    )\n\n    if not audit_expected:\n        return True\n\n    entry_expected = normalize_language_codes(\n        entry.get("expected_language_codes")\n        or entry.get("language_code")\n    )\n\n    if not entry_expected:\n        return True\n\n    return bool(\n        set(audit_expected).intersection(\n            entry_expected\n        )\n    )\n\n\ndef validate_audit_items(''',
    "insert exact-URL identity guard",
)

build = replace_once(
    build,
    '''        expected_for_validation = (\n            normalize_language_codes(\n                item.get("expected_language_codes")\n            )\n        )\n\n        # If the audit does not explicitly say what language was expected,''',
    '''        expected_for_validation = (\n            normalize_language_codes(\n                item.get("expected_language_codes")\n            )\n        )\n\n        current_url_expected = (\n            sorted(\n                current_expected_by_url.get(\n                    url_key,\n                    set(),\n                )\n            )\n            if url_key\n            else []\n        )\n\n        if (\n            url_key\n            and expected_for_validation\n            and current_url_expected\n            and not set(\n                expected_for_validation\n            ).intersection(\n                current_url_expected\n            )\n        ):\n            warnings.append(\n                f"{label}: exact stream URL is currently scoped to "\n                f"{', '.join(current_url_expected)}, but the saved audit "\n                f"explicitly expects {', '.join(expected_for_validation)}. "\n                "The saved result will be kept as historical evidence and "\n                "will not be applied to this current entry."\n            )\n\n        # If the audit does not explicitly say what language was expected,''',
    "warn about cross-country exact-URL audit",
)

build = replace_once(
    build,
    '''        # URL-specific audit is always authoritative. Canonically equivalent\n        # URL spellings identify the same stream.\n        if url_key and url_key in manual_by_url:\n            manual = manual_by_url[url_key]\n            manual_key = ("url", url_key)\n''',
    '''        # URL-specific audit is authoritative only when any explicitly\n        # recorded expected language/country is compatible with this current\n        # entry. Canonically equivalent URL spellings still identify the same\n        # stream inside that identity scope.\n        if url_key and url_key in manual_by_url:\n            candidate_manual = manual_by_url[url_key]\n\n            if exact_url_audit_matches_entry(\n                candidate_manual,\n                entry,\n            ):\n                manual = candidate_manual\n                manual_key = ("url", url_key)\n''',
    "guard exact-URL audit application",
)

build = replace_once(
    build,
    '''        if manual_key in used_manual_keys:\n            continue\n\n        if url_key and url_key in current_urls:\n            continue\n\n        legacy_ambiguous = False\n''',
    '''        if manual_key in used_manual_keys:\n            continue\n\n        # An exact URL can still need to remain as historical evidence when\n        # its saved expected language/country conflicts with the current entry.\n        # Do not discard it merely because that URL exists in current inputs.\n        legacy_ambiguous = False\n''',
    "preserve conflicting exact-URL audit history",
)

build = replace_once(
    build,
    '''        history_notes = str(\n            item.get("notes") or ""\n        ).strip()\n\n        if legacy_ambiguous:\n''',
    '''        history_notes = str(\n            item.get("notes") or ""\n        ).strip()\n\n        if url_key and url_key in current_expected_by_url:\n            saved_expected = normalize_language_codes(\n                item.get("expected_language_codes")\n            )\n            current_expected = sorted(\n                current_expected_by_url.get(\n                    url_key,\n                    set(),\n                )\n            )\n\n            if (\n                saved_expected\n                and current_expected\n                and not set(saved_expected).intersection(\n                    current_expected\n                )\n            ):\n                identity_note = (\n                    "Historical exact-URL audit only. Saved expected "\n                    f"language/country {format_language_codes(saved_expected)} "\n                    "does not match the current entry scope "\n                    f"{format_language_codes(current_expected)}, so this "\n                    "verification was not transferred."\n                )\n\n                history_notes = " — ".join(\n                    part\n                    for part in (\n                        history_notes,\n                        identity_note,\n                    )\n                    if part\n                )\n\n        if legacy_ambiguous:\n''',
    "annotate historical identity conflict",
)

build = replace_once(
    build,
    '''    audit_by_url: dict[str, dict] = {}\n\n    for row in audit_rows:\n        url = str(row.get("stream_url") or "").strip()\n        if not url:\n            continue\n\n        url_key = canonical_stream_url(url)\n\n        if url_key in audit_by_url:\n            raise RuntimeError(f"Duplicate prepared audit URL: {url}")\n\n        audit_by_url[url_key] = row\n\n    candidate_entries: list[dict] = []\n''',
    '''    audit_by_url = audit_rows_by_stream_url(\n        audit_rows\n    )\n\n    candidate_entries: list[dict] = []\n''',
    "reuse current-row URL audit lookup",
)

build = replace_once(
    build,
    '''    for row in audit_rows:\n        url = str(\n            row.get("stream_url") or ""\n        ).strip()\n\n        if not url:\n            continue\n\n        key = canonical_stream_url(url)\n''',
    '''    for row in audit_rows:\n        # Historical rows may intentionally retain the same URL as a current\n        # entry after an identity-scope conflict. They must never drive current\n        # playlist selection.\n        if row.get("in_playlist") is False:\n            continue\n\n        url = str(\n            row.get("stream_url") or ""\n        ).strip()\n\n        if not url:\n            continue\n\n        key = canonical_stream_url(url)\n''',
    "ignore historical rows in URL lookup",
)

build = replace_once(
    build,
    '''        row_url_key = (\n            canonical_stream_url(\n                row_url\n            )\n        )\n\n        # "in_playlist" now means the stream is a current candidate\n''',
    '''        row_url_key = (\n            canonical_stream_url(\n                row_url\n            )\n        )\n\n        # prepare_audit_rows deliberately marks historical-only rows false.\n        # Preserve that authority even when a different current identity uses\n        # the same URL.\n        if row.get("in_playlist") is False:\n            row["in_stable_playlist"] = False\n            continue\n\n        # "in_playlist" now means the stream is a current candidate\n''',
    "preserve historical-only row state",
)

build_path.write_text(build, encoding="utf-8")


test_path = Path("tests/test_regressions.py")
tests = test_path.read_text(encoding="utf-8")

test_method = '''    def test_exact_url_audit_does_not_cross_explicit_language_scope(self):\n        url = "https://dash.antik.sk/live/test_upnetwork/playlist.m3u8"\n\n        entry = {\n            "lines": [\n                '#EXTINF:-1 tvg-id="UpNetwork.cz@SD" tvg-name="Up Network",Up Network',\n                url,\n            ],\n            "url": url,\n            "display_name": "Up Network",\n            "tvg_id": "UpNetwork.cz@SD",\n            "tvg_name": "Up Network",\n            "logo": "",\n            "group_title": "",\n            "channel_name": "Up Network",\n            "source": "IPTV-org Czechia",\n            "source_kind": "base",\n            "language_code": "CZ",\n            "source_flags": [],\n            "classification": "Base channel",\n        }\n        entry["channel_key"] = build.channel_key(entry)\n\n        audit = [{\n            "channel": "Kanal1",\n            "stream_url": url,\n            "vlc": "works",\n            "samsung": "works",\n            "decision": "auto",\n            "expected_language_codes": ["SK"],\n            "observed_language_codes": ["SK"],\n            "language": "Slovak",\n            "language_code": "SK",\n        }]\n\n        warnings, ambiguity_warnings = build.validate_audit_items(\n            audit,\n            [entry],\n            strict=True,\n        )\n\n        self.assertEqual(ambiguity_warnings, [])\n        self.assertTrue(\n            any(\n                "saved audit explicitly expects SK" in warning\n                for warning in warnings\n            )\n        )\n\n        rows = build.prepare_audit_rows(audit, [entry])\n        current = [row for row in rows if row["in_playlist"]]\n        historical = [row for row in rows if not row["in_playlist"]]\n\n        self.assertEqual(len(current), 1)\n        self.assertEqual(current[0]["channel"], "Up Network")\n        self.assertEqual(current[0]["expected_language_codes"], ["CZ"])\n        self.assertEqual(current[0]["decision"], "Needs review")\n        self.assertEqual(current[0]["vlc"], "not_tested")\n        self.assertEqual(current[0]["samsung"], "not_tested")\n\n        self.assertEqual(len(historical), 1)\n        self.assertEqual(historical[0]["channel"], "Kanal1")\n        self.assertEqual(historical[0]["expected_language_codes"], ["SK"])\n        self.assertEqual(historical[0]["decision"], "Verified")\n        self.assertIn(\n            "Historical exact-URL audit only",\n            historical[0]["notes"],\n        )\n\n        test_candidates = build.make_test_playlist_candidates(\n            [entry],\n            rows,\n        )\n        self.assertEqual(len(test_candidates), 1)\n        self.assertEqual(\n            test_candidates[0]["_decision"],\n            "Needs review",\n        )\n\n        stable, _excluded = build.select_stable_playlist_candidates(\n            [entry],\n            rows,\n            {\n                "stable_playlist": {\n                    "allowed_decisions": [\n                        "Verified",\n                        "TV verified",\n                    ]\n                }\n            },\n        )\n        self.assertEqual(stable, [])\n\n'''

tests = replace_once(
    tests,
    '''\n\nclass AuditBooleanRegressionTests(unittest.TestCase):\n''',
    "\n\n" + test_method + "\nclass AuditBooleanRegressionTests(unittest.TestCase):\n",
    "add cross-country exact-URL regression",
)

test_path.write_text(tests, encoding="utf-8")


config_path = Path("config.json")
config = json.loads(config_path.read_text(encoding="utf-8"))
redundant_sources = {
    "IPTV-org Slovakia country",
    "IPTV-org Hungary country",
    "IPTV-org Czech country",
}
original_count = len(config.get("sources") or [])
config["sources"] = [
    source
    for source in (config.get("sources") or [])
    if str(source.get("name") or "") not in redundant_sources
]
if original_count - len(config["sources"]) != 3:
    raise RuntimeError("Expected to remove exactly three redundant country sources")
config_path.write_text(
    json.dumps(config, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)


workflow_path = Path(".github/workflows/build-and-publish.yml")
workflow = workflow_path.read_text(encoding="utf-8")
workflow = replace_once(
    workflow,
    "      - name: Build IPTV playlist\n        run: python3 build.py\n",
    "      - name: Build IPTV playlist\n        run: python3 build.py --strict\n",
    "enable strict production build",
)
workflow_path.write_text(workflow, encoding="utf-8")


ci_path = Path(".github/workflows/ci.yml")
ci_path.write_text(
    '''name: Validate pull requests\n\non:\n  pull_request:\n    branches:\n      - main\n\npermissions:\n  contents: read\n\njobs:\n  validate:\n    runs-on: ubuntu-latest\n\n    steps:\n      - name: Checkout repository\n        uses: actions/checkout@v7\n\n      - name: Run unit tests\n        run: python3 -m unittest discover -s tests -v\n\n      - name: Run strict playlist build\n        run: python3 build.py --strict\n''',
    encoding="utf-8",
)

# Remove the temporary applicator/workflow from the final branch diff. The
# currently running workflow has already loaded its definition.
Path(".github/workflows/agent-apply-fixes.yml").unlink()
Path(".github/scripts/apply_requested_fixes.py").unlink()
