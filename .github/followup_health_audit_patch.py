from __future__ import annotations

import json
from pathlib import Path

ROOT = Path.cwd()


def replace_once(rel: str, old: str, new: str) -> None:
    path = ROOT / rel
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"Expected exactly one match in {rel}, found {count}: {old[:160]!r}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# ---------------------------------------------------------------------------
# Health policy: distinguish a known TV-working/client-incompatible stream from
# an actually broken stream or an event-based inactive stream.
# ---------------------------------------------------------------------------
replace_once(
    "health_policy.py",
    'VALID_HEALTH_POLICIES = {"normal", "event_based"}\n',
    'VALID_HEALTH_POLICIES = {"normal", "event_based", "manual_tv_verified"}\n',
)

replace_once(
    "healthcheck.py",
    '''    event_inactive = health_policy == "event_based" and not success\n    actionable_failure = not success and not event_inactive\n''',
    '''    event_inactive = health_policy == "event_based" and not success\n    manual_tv_probe_unavailable = (\n        health_policy == "manual_tv_verified"\n        and not success\n    )\n    actionable_failure = (\n        not success\n        and not event_inactive\n        and not manual_tv_probe_unavailable\n    )\n''',
)

replace_once(
    "healthcheck.py",
    '''    if event_inactive:\n        status = "Event inactive"\n        raw_detail = str(\n            probe.get("detail") or "Automated probe found no active broadcast."\n        ).strip()\n        detail = (\n            "Event-based stream is currently inactive; this does not count as a "\n            "channel failure or build a manual-retest streak. "\n            f"Probe result: {probe_status}. {raw_detail}"\n        )\n        if health_policy_reason:\n            detail += f" Policy reason: {health_policy_reason}"\n    else:\n        status = probe_status\n        detail = probe.get("detail", "")\n''',
    '''    if event_inactive:\n        status = "Event inactive"\n        raw_detail = str(\n            probe.get("detail") or "Automated probe found no active broadcast."\n        ).strip()\n        detail = (\n            "Event-based stream is currently inactive; this does not count as a "\n            "channel failure or build a manual-retest streak. "\n            f"Probe result: {probe_status}. {raw_detail}"\n        )\n        if health_policy_reason:\n            detail += f" Policy reason: {health_policy_reason}"\n    elif manual_tv_probe_unavailable:\n        status = "TV verified; PC probe unavailable"\n        raw_detail = str(\n            probe.get("detail") or "Automated PC-style probe could not verify playback."\n        ).strip()\n        detail = (\n            "Manual TV playback is currently authoritative for this exact stream. "\n            "The automated/desktop-style probe remains unsuccessful and is preserved "\n            "as diagnostic evidence, but it does not count as a channel outage or "\n            "build a manual-retest streak. "\n            f"Probe result: {probe_status}. {raw_detail}"\n        )\n        if health_policy_reason:\n            detail += f" Policy reason: {health_policy_reason}"\n    else:\n        status = probe_status\n        detail = probe.get("detail", "")\n''',
)

replace_once(
    "healthcheck.py",
    '''        "actionable_failure": actionable_failure,\n        "attention": attention,\n''',
    '''        "actionable_failure": actionable_failure,\n        "stream_state": (\n            "playable"\n            if success\n            else (\n                "event_inactive"\n                if event_inactive\n                else (\n                    "manual_tv_verified_probe_failure"\n                    if manual_tv_probe_unavailable\n                    else "probe_failure"\n                )\n            )\n        ),\n        "attention": attention,\n''',
)

replace_once(
    "healthcheck.py",
    '''            "event_based": (\n                "A failed automated probe for an explicitly event_based stream is "\n                "reported as Event inactive, remains success=false, but is informational: "\n                "it does not build a failure streak or recommend a manual retest."\n            ),\n            "tls_certificate_retry": (\n''',
    '''            "event_based": (\n                "A failed automated probe for an explicitly event_based stream is "\n                "reported as Event inactive, remains success=false, but is informational: "\n                "it does not build a failure streak or recommend a manual retest."\n            ),\n            "manual_tv_verified": (\n                "A failed automated probe for an explicitly manual_tv_verified stream "\n                "remains success=false and preserves the raw probe failure, but a recent "\n                "manual TV playback check is authoritative: the failure is informational, "\n                "does not build a streak, and does not request another retest."\n            ),\n            "tls_certificate_retry": (\n''',
)

health_policy_path = ROOT / "health_policy.json"
health_policy = json.loads(health_policy_path.read_text(encoding="utf-8"))
health_policy["description"] = (
    "Controls how automated stream failures affect health history. normal = failures "
    "build a daily streak; event_based = inactive probes are informational because the "
    "stream is not expected to broadcast continuously; manual_tv_verified = a recent "
    "manual TV playback check is authoritative when the PC-style probe cannot play the "
    "exact stream."
)
manual_entries = [
    {
        "name": ":24",
        "tvg_id": "24.sk@SD",
        "health_policy": "manual_tv_verified",
        "reason": (
            "Samsung TV playback was manually verified on 2026-08-12 while VLC only "
            "loads and the automated HTTP probe receives 403; treat that PC/probe "
            "limitation as informational unless manual TV verification changes."
        ),
    },
    {
        "name": ":Šport",
        "tvg_id": "Sport.sk@SD",
        "health_policy": "manual_tv_verified",
        "reason": (
            "Samsung TV playback was manually verified on 2026-08-12 while VLC only "
            "loads and the automated HTTP probe receives 403; treat that PC/probe "
            "limitation as informational unless manual TV verification changes."
        ),
    },
    {
        "name": "Vásárhelyi Televízió",
        "tvg_id": "VasarhelyiTelevizio.hu@SD",
        "health_policy": "manual_tv_verified",
        "reason": (
            "Samsung TV playback was manually verified on 2026-08-12 while VLC only "
            "loads and the automated HLS segment probe cannot confirm playable media; "
            "treat that PC/probe limitation as informational unless manual TV verification changes."
        ),
    },
]
entries = health_policy.setdefault("entries", [])
existing_tvg = {
    str(item.get("tvg_id") or "").casefold()
    for item in entries
    if isinstance(item, dict)
}
for item in manual_entries:
    if item["tvg_id"].casefold() not in existing_tvg:
        entries.append(item)
health_policy_path.write_text(
    json.dumps(health_policy, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)

replace_once(
    "docs/health-policy.md",
    '''- `normal` — default for ordinary 24/7 channels. Automated failures remain warnings, build a daily failure streak, and recommend a manual retest after three failed days.\n- `event_based` — for streams that legitimately exist only while an event is being broadcast. A failed automated probe is reported as `Event inactive`, remains visible in `health.json`, and is informational rather than actionable.\n\nFor an `event_based` inactive result:\n''',
    '''- `normal` — default for ordinary 24/7 channels. Automated failures remain warnings, build a daily failure streak, and recommend a manual retest after three failed days.\n- `event_based` — for streams that legitimately exist only while an event is being broadcast. A failed automated probe is reported as `Event inactive`, remains visible in `health.json`, and is informational rather than actionable.\n- `manual_tv_verified` — for an exact stream that was recently confirmed working on the family/Samsung TV but cannot be validated by VLC or the automated PC-style probe. The raw probe failure stays visible, but it is informational and does not create a false outage/retest loop.\n\nFor an `event_based` inactive or `manual_tv_verified` probe-failure result:\n''',
)
replace_once(
    "docs/health-policy.md",
    '''This avoids pretending that an inactive event stream is playable while also avoiding a false dead-channel alarm.\n''',
    '''This avoids pretending that an inactive/event stream or a PC-incompatible stream passed the automated probe while also avoiding a false dead-channel alarm. `manual_tv_verified` should only be used after a dated manual TV check and should be removed if that manual evidence becomes stale or playback stops working on the TV.\n''',
)

# ---------------------------------------------------------------------------
# Audit migration: add modern country/language fields without deleting legacy
# aliases. URL migration remains available; --modernize-only can enrich every
# row without changing stream identity.
# ---------------------------------------------------------------------------
replace_once(
    "migrate_audit.py",
    '''from urllib.parse import urlparse, urlunparse\n\n\nQUALITY_SUFFIX_RE''',
    '''from urllib.parse import urlparse, urlunparse\n\nfrom country_language import (\n    country_code_from_tvg_id,\n    country_language_defaults,\n    normalize_country_code,\n    normalize_language_codes,\n)\n\n\nQUALITY_SUFFIX_RE''',
)

replace_once(
    "migrate_audit.py",
    '''def migrate(\n    audit_path: Path,\n    current_path: Path,\n    write: bool = False,\n) -> dict[str, int]:\n''',
    '''def _first_country(*values) -> str:\n    for value in values:\n        code = normalize_country_code(str(value or ""))\n        if code:\n            return code\n    return ""\n\n\ndef modernize_audit_item(\n    item: dict,\n    candidate: dict[str, str] | None = None,\n    cfg: dict | None = None,\n) -> bool:\n    """Add the modern country/language model while retaining legacy aliases.\n\n    The migration deliberately leaves cross-language output_country_code blank\n    unless an explicit legacy output exists. A blank modern output field lets\n    the normal verified-country routing logic decide later and avoids pinning a\n    rejected/untested row to the wrong destination.\n    """\n    cfg = cfg or {}\n    candidate = candidate or {}\n\n    playlist_country = _first_country(\n        item.get("playlist_country_code"),\n        item.get("playlist_language_code"),\n        item.get("language_code"),\n        candidate.get("playlist_country_code"),\n        candidate.get("country_code"),\n        candidate.get("language_code"),\n    )\n    if not playlist_country:\n        playlist_country = country_code_from_tvg_id(\n            str(item.get("tvg_id") or candidate.get("tvg_id") or "")\n        )\n\n    expected = normalize_language_codes(\n        item.get("expected_language_codes")\n    )\n    if not expected and playlist_country:\n        expected = country_language_defaults(cfg, playlist_country)\n\n    observed = normalize_language_codes(\n        item.get("observed_language_codes")\n    )\n    if not observed:\n        observed = normalize_language_codes(\n            item.get("language")\n        )\n\n    language_codes = normalize_language_codes(\n        item.get("language_codes")\n    )\n    if not language_codes:\n        language_codes = list(observed or expected)\n\n    output_country = _first_country(\n        item.get("output_country_code"),\n        item.get("output_language_code"),\n        candidate.get("output_country_code"),\n    )\n    if not output_country and playlist_country:\n        defaults = set(\n            country_language_defaults(cfg, playlist_country)\n        )\n        # Same-country/unknown-language rows are safe to make explicit. For a\n        # true cross-language row, leave output blank so verified routing stays\n        # authoritative instead of this migration silently pinning a country.\n        if not observed or defaults.intersection(observed):\n            output_country = playlist_country\n\n    modern = {\n        "playlist_country_code": playlist_country,\n        "output_country_code": output_country,\n        "language_codes": language_codes,\n        "expected_language_codes": expected,\n        "observed_language_codes": observed,\n    }\n\n    changed = False\n    for key, value in modern.items():\n        if item.get(key) != value:\n            item[key] = value\n            changed = True\n    return changed\n\n\ndef migrate(\n    audit_path: Path,\n    current_path: Path,\n    write: bool = False,\n    modernize_only: bool = False,\n    config_path: Path | None = None,\n) -> dict[str, int]:\n''',
)

replace_once(
    "migrate_audit.py",
    '''    rows = load_current_rows(current_path)\n\n    migrated = 0\n    ambiguous = 0\n    missing = 0\n    already_exact = 0\n\n    for index, item in enumerate(items, start=1):\n        if not isinstance(item, dict):\n            continue\n\n        if str(item.get("stream_url") or "").strip():\n            already_exact += 1\n            continue\n\n        candidate = choose_unique_candidate(\n            item,\n            rows,\n        )\n''',
    '''    rows = load_current_rows(current_path)\n\n    cfg: dict = {}\n    resolved_config = config_path\n    if resolved_config is None:\n        sibling = audit_path.parent / "config.json"\n        if sibling.is_file():\n            resolved_config = sibling\n    if resolved_config is not None and resolved_config.is_file():\n        loaded = json.loads(resolved_config.read_text(encoding="utf-8"))\n        if isinstance(loaded, dict):\n            cfg = loaded\n\n    migrated = 0\n    modernized = 0\n    ambiguous = 0\n    missing = 0\n    already_exact = 0\n\n    for index, item in enumerate(items, start=1):\n        if not isinstance(item, dict):\n            continue\n\n        candidate = choose_unique_candidate(\n            item,\n            rows,\n        )\n\n        if modernize_audit_item(\n            item,\n            candidate=candidate,\n            cfg=cfg,\n        ):\n            modernized += 1\n\n        if modernize_only:\n            continue\n\n        if str(item.get("stream_url") or "").strip():\n            already_exact += 1\n            continue\n''',
)

replace_once(
    "migrate_audit.py",
    '''    if write and migrated:\n''',
    '''    if write and (migrated or modernized):\n''',
)
replace_once(
    "migrate_audit.py",
    '''    summary = {\n        "migrated": migrated,\n        "already_exact": already_exact,\n        "ambiguous": ambiguous,\n        "missing": missing,\n    }\n''',
    '''    summary = {\n        "migrated": migrated,\n        "modernized": modernized,\n        "already_exact": already_exact,\n        "ambiguous": ambiguous,\n        "missing": missing,\n    }\n''',
)
replace_once(
    "migrate_audit.py",
    '''        "Audit migration summary: "\n        f"{migrated} safe one-to-one, "\n        f"{already_exact} already exact, "\n''',
    '''        "Audit migration summary: "\n        f"{migrated} safe one-to-one, "\n        f"{modernized} modernized metadata rows, "\n        f"{already_exact} already exact, "\n''',
)
replace_once(
    "migrate_audit.py",
    '''    parser.add_argument(\n        "--write",\n        action="store_true",\n        help="Write safe one-to-one migrations back to audit.json.",\n    )\n    args = parser.parse_args()\n\n    migrate(\n        args.audit,\n        args.current,\n        write=args.write,\n    )\n''',
    '''    parser.add_argument(\n        "--write",\n        action="store_true",\n        help="Write safe migrations back to audit.json.",\n    )\n    parser.add_argument(\n        "--modernize-only",\n        action="store_true",\n        help=(\n            "Only add/update modern country and ISO-639-3 language fields; "\n            "do not attach missing stream URLs."\n        ),\n    )\n    parser.add_argument(\n        "--config",\n        type=Path,\n        default=Path("config.json"),\n        help="Project config used for country-to-language defaults.",\n    )\n    args = parser.parse_args()\n\n    migrate(\n        args.audit,\n        args.current,\n        write=args.write,\n        modernize_only=args.modernize_only,\n        config_path=args.config,\n    )\n''',
)
replace_once(
    "migrate_audit.py",
    '''            "Safely migrate legacy channel-level audit rows "\n            "to exact stream_url rows using generated public/audit.csv."\n''',
    '''            "Safely migrate legacy audit rows to exact stream URLs and/or "\n            "the modern country + ISO-639-3 spoken-language model."\n''',
)

# Nicktoons: the exact URL is a Czech feed and was already proven to work on
# both devices. Its old rejection was only meaningful while it was attached to
# HU scope. Preserve legacy aliases, but make the current audit identity CZ.
audit_path = ROOT / "audit.json"
audit_payload = json.loads(audit_path.read_text(encoding="utf-8"))
audit_items = audit_payload.get("channels") if isinstance(audit_payload, dict) else audit_payload
if not isinstance(audit_items, list):
    raise RuntimeError("audit.json does not contain a channel list")
nick_url = "http://88.212.15.19/live/test_nicktoons/playlist.m3u8"
nick_matches = [
    item for item in audit_items
    if isinstance(item, dict)
    and str(item.get("stream_url") or "").strip() == nick_url
]
if len(nick_matches) != 1:
    raise RuntimeError(f"Expected exactly one Nicktoons Czech audit row, found {len(nick_matches)}")
nick = nick_matches[0]
nick.update({
    "language": "Czech",
    "language_code": "CZ",
    "playlist_country_code": "CZ",
    "output_country_code": "CZ",
    "language_codes": ["ces"],
    "expected_language_codes": ["ces"],
    "observed_language_codes": ["ces"],
    "language_match": "yes",
    "vlc": "works",
    "samsung": "works",
    "decision": "auto",
    "exclude_from_playlist": False,
    "discovery": "IPTV-org Czech-language source; migrated from legacy Hungarian-scope audit",
    "reason": (
        "This exact stream was already manually verified as working Czech on both devices. "
        "It was rejected only because it was originally audited under Hungarian scope; "
        "after country/language separation it is a correctly scoped Czech feed."
    ),
    "notes": (
        "Migrated to the modern CZ/ces audit model on 2026-08-12. Legacy aliases are "
        "retained for backward compatibility."
    ),
})
audit_path.write_text(
    json.dumps(audit_payload, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)

# Regression coverage added as one focused follow-up test module.
(ROOT / "tests" / "test_health_audit_followup.py").write_text(
    '''import csv\nimport json\nimport tempfile\nimport unittest\nfrom pathlib import Path\n\nfrom health_policy import compile_health_policy, resolve_health_policy\nfrom healthcheck import apply_history\nfrom migrate_audit import migrate\n\n\nROOT = Path(__file__).resolve().parents[1]\n\n\nclass ManualTvVerifiedHealthTests(unittest.TestCase):\n    def test_policy_is_valid_and_failed_probe_is_informational(self):\n        default, indexes = compile_health_policy({\n            "default": "normal",\n            "entries": [{\n                "tvg_id": "24.sk@SD",\n                "health_policy": "manual_tv_verified",\n                "reason": "Manual Samsung verification is current.",\n            }],\n        })\n        policy = resolve_health_policy(\n            {"tvg_id": "24.sk@SD", "channel": ":24"},\n            default=default,\n            indexes=indexes,\n        )\n        entry = {\n            "channel": ":24",\n            "tvg_id": "24.sk@SD",\n            "stream_url": "http://example.test/24.m3u8",\n            "health_policy": policy["health_policy"],\n            "health_policy_reason": policy["reason"],\n            "health_policy_match": policy["matched_by"],\n        }\n        probe = {\n            "status": "HTTP error",\n            "success": False,\n            "detail": "HTTP 403",\n            "http_status": 403,\n        }\n        row = apply_history(\n            entry,\n            probe,\n            {"consecutive_failures": 2, "checked_at": "2026-08-11 04:00:00 UTC"},\n            "2026-08-12 04:00:00 UTC",\n        )\n        self.assertFalse(row["success"])\n        self.assertFalse(row["actionable_failure"])\n        self.assertEqual(row["consecutive_failures"], 0)\n        self.assertFalse(row["manual_retest_recommended"])\n        self.assertEqual(row["attention"], "informational")\n        self.assertEqual(row["stream_state"], "manual_tv_verified_probe_failure")\n        self.assertEqual(row["probe_status"], "HTTP error")\n        self.assertEqual(row["status"], "TV verified; PC probe unavailable")\n\n    def test_three_current_false_positives_are_explicitly_scoped(self):\n        payload = json.loads((ROOT / "health_policy.json").read_text(encoding="utf-8"))\n        default, indexes = compile_health_policy(payload)\n        for tvg_id in (\n            "24.sk@SD",\n            "Sport.sk@SD",\n            "VasarhelyiTelevizio.hu@SD",\n        ):\n            with self.subTest(tvg_id=tvg_id):\n                result = resolve_health_policy(\n                    {"tvg_id": tvg_id},\n                    default=default,\n                    indexes=indexes,\n                )\n                self.assertEqual(result["health_policy"], "manual_tv_verified")\n                self.assertEqual(result["matched_by"], "tvg_id")\n\n\nclass ModernAuditMigrationTests(unittest.TestCase):\n    def write_current(self, path: Path):\n        with path.open("w", encoding="utf-8", newline="") as handle:\n            writer = csv.DictWriter(\n                handle,\n                fieldnames=["channel", "tvg_id", "stream_url", "protocol"],\n            )\n            writer.writeheader()\n            writer.writerow({\n                "channel": "Example",\n                "tvg_id": "Example.sk@SD",\n                "stream_url": "https://example.test/live.m3u8",\n                "protocol": "HLS",\n            })\n\n    def test_modernize_only_adds_iso_fields_and_keeps_legacy_aliases(self):\n        with tempfile.TemporaryDirectory() as tmp:\n            root = Path(tmp)\n            audit = root / "audit.json"\n            current = root / "audit.csv"\n            audit.write_text(json.dumps({\n                "channels": [{\n                    "channel": "Example",\n                    "tvg_id": "Example.sk@SD",\n                    "stream_url": "https://example.test/live.m3u8",\n                    "language": "Slovak",\n                    "language_code": "SK",\n                    "expected_language_codes": ["SK"],\n                    "observed_language_codes": ["SK"],\n                }]\n            }), encoding="utf-8")\n            self.write_current(current)\n            summary = migrate(\n                audit,\n                current,\n                write=True,\n                modernize_only=True,\n            )\n            item = json.loads(audit.read_text(encoding="utf-8"))["channels"][0]\n            self.assertEqual(item["language_code"], "SK")\n            self.assertEqual(item["playlist_country_code"], "SK")\n            self.assertEqual(item["output_country_code"], "SK")\n            self.assertEqual(item["language_codes"], ["slk"])\n            self.assertEqual(item["expected_language_codes"], ["slk"])\n            self.assertEqual(item["observed_language_codes"], ["slk"])\n            self.assertEqual(summary["modernized"], 1)\n\n    def test_cross_language_output_is_not_pinned_by_metadata_migration(self):\n        with tempfile.TemporaryDirectory() as tmp:\n            root = Path(tmp)\n            audit = root / "audit.json"\n            current = root / "audit.csv"\n            audit.write_text(json.dumps({\n                "channels": [{\n                    "channel": "Cross",\n                    "tvg_id": "Cross.sk@SD",\n                    "stream_url": "https://example.test/cross.m3u8",\n                    "language_code": "SK",\n                    "expected_language_codes": ["SK"],\n                    "observed_language_codes": ["CZ"],\n                }]\n            }), encoding="utf-8")\n            self.write_current(current)\n            migrate(audit, current, write=True, modernize_only=True)\n            item = json.loads(audit.read_text(encoding="utf-8"))["channels"][0]\n            self.assertEqual(item["playlist_country_code"], "SK")\n            self.assertEqual(item["output_country_code"], "")\n            self.assertEqual(item["expected_language_codes"], ["slk"])\n            self.assertEqual(item["observed_language_codes"], ["ces"])\n\n    def test_nicktoons_czech_audit_is_modern_and_not_legacy_hu_rejected(self):\n        payload = json.loads((ROOT / "audit.json").read_text(encoding="utf-8"))\n        rows = [\n            item for item in payload["channels"]\n            if item.get("stream_url")\n            == "http://88.212.15.19/live/test_nicktoons/playlist.m3u8"\n        ]\n        self.assertEqual(len(rows), 1)\n        item = rows[0]\n        self.assertEqual(item["language_code"], "CZ")\n        self.assertEqual(item["playlist_country_code"], "CZ")\n        self.assertEqual(item["output_country_code"], "CZ")\n        self.assertEqual(item["expected_language_codes"], ["ces"])\n        self.assertEqual(item["observed_language_codes"], ["ces"])\n        self.assertEqual(item["vlc"], "works")\n        self.assertEqual(item["samsung"], "works")\n        self.assertFalse(item["exclude_from_playlist"])\n\n\nif __name__ == "__main__":\n    unittest.main()\n''',
    encoding="utf-8",
)

print("Applied stream-health and audit follow-up patch.")
