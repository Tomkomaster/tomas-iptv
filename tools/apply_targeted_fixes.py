from pathlib import Path


path = Path("build.py")
text = path.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"{label}: expected exactly one match, found {count}"
        )
    text = text.replace(old, new, 1)


# 1) Add a language-scoped logical identity while preserving channel_key().
replace_once(
    '''    return ""\n\n\ndef normalize_language_codes(value) -> list[str]:\n''',
    '''    return ""\n\n\ndef logical_channel_key(entry: dict) -> str:\n    """\n    Identify a logical channel inside one language/country playlist.\n\n    channel_key() intentionally remains language-agnostic so SD/HD variants\n    and equivalent source metadata still collapse. This helper adds the\n    playlist language only where cross-source grouping needs it.\n    """\n    language_code = (\n        normalize_language_code(\n            str(entry.get("language_code") or "")\n        )\n        or "UNKNOWN"\n    )\n\n    raw_key = str(\n        entry.get("channel_key")\n        or channel_key(entry)\n    )\n\n    prefix = f"{language_code}:"\n    if raw_key.startswith(prefix):\n        return raw_key\n\n    return f"{prefix}{raw_key}"\n\n\ndef normalize_language_codes(value) -> list[str]:\n''',
    "insert logical_channel_key",
)

# Feed numbering must be scoped by language as well.
old_feed_key = '        key = entry.get("channel_key") or channel_key(entry)\n'
feed_key_count = text.count(old_feed_key)
if feed_key_count != 2:
    raise RuntimeError(
        f"feed grouping: expected 2 matches, found {feed_key_count}"
    )
text = text.replace(
    old_feed_key,
    '        key = logical_channel_key(entry)\n',
)

replace_once(
    '        candidate_groups.setdefault(entry["channel_key"], []).append(entry)\n',
    '        candidate_groups.setdefault(logical_channel_key(entry), []).append(entry)\n',
    "candidate grouping",
)

replace_once(
    '''        stable_groups.setdefault(\n            entry["channel_key"],\n            [],\n        ).append(\n''',
    '''        stable_groups.setdefault(\n            logical_channel_key(entry),\n            [],\n        ).append(\n''',
    "stable grouping",
)

replace_once(
    '''        visible_groups.setdefault(\n            entry["channel_key"],\n            [],\n        ).append(\n''',
    '''        visible_groups.setdefault(\n            logical_channel_key(entry),\n            [],\n        ).append(\n''',
    "published grouping",
)

# Main source classification: same raw TVG/name in HU and SK is distinct.
replace_once(
    '''            entry["source_kind"] = kind\n            entry["language_code"] = language_code\n\n            country_name = str(\n''',
    '''            entry["source_kind"] = kind\n            entry["language_code"] = language_code\n            logical_key = logical_channel_key(entry)\n\n            country_name = str(\n''',
    "main logical key",
)

replace_once(
    '            if key not in seen_channels:\n',
    '            if logical_key not in seen_channels:\n',
    "seen channel lookup",
)

replace_once(
    '''                seen_channels[key] = {\n                    "key": key,\n''',
    '''                seen_channels[logical_key] = {\n                    "key": logical_key,\n                    "raw_key": key,\n''',
    "seen channel storage",
)

# Report identity and future change detection should also stay language-scoped.
replace_once(
    '''    by_channel: dict[str, dict] = {}\n    for entry in published_entries:\n        key = entry["channel_key"]\n        record = by_channel.setdefault(key, {\n            "key": key,\n            "name": entry["channel_name"],\n            "tvg_id": entry.get("tvg_id", ""),\n            "sources": [],\n            "stream_count": 0,\n        })\n''',
    '''    by_channel: dict[str, dict] = {}\n    for entry in published_entries:\n        key = logical_channel_key(entry)\n        record = by_channel.setdefault(key, {\n            "key": key,\n            "raw_key": entry.get("channel_key", ""),\n            "language_code": entry.get("language_code", ""),\n            "name": entry["channel_name"],\n            "tvg_id": entry.get("tvg_id", ""),\n            "sources": [],\n            "stream_count": 0,\n        })\n''',
    "report channel identity",
)

replace_once(
    '''    if previous_report:\n        previous_by_key = {\n            str(ch.get("key")): str(ch.get("name") or ch.get("key"))\n            for ch in previous_report.get("channels", [])\n            if ch.get("key")\n        }\n        current_by_key = {ch["key"]: ch["name"] for ch in unique_channels}\n\n''',
    '''    if previous_report:\n        previous_channels = [\n            ch\n            for ch in previous_report.get("channels", [])\n            if ch.get("key")\n        ]\n\n        previous_by_key = {\n            str(ch.get("key")): str(ch.get("name") or ch.get("key"))\n            for ch in previous_channels\n        }\n\n        current_by_key = {\n            ch["key"]: ch["name"]\n            for ch in unique_channels\n        }\n\n        # The first build after this migration compares against a report whose\n        # keys were not language-scoped. Compare raw legacy keys once so the\n        # dashboard does not report every channel as removed and re-added.\n        previous_has_scoped_keys = any(\n            re.fullmatch(\n                r"[A-Z]{2,3}:(?:id|name):.+",\n                key,\n            )\n            for key in previous_by_key\n        )\n\n        if previous_by_key and not previous_has_scoped_keys:\n            current_by_key = {\n                str(ch.get("raw_key") or ch["key"]): ch["name"]\n                for ch in unique_channels\n            }\n\n''',
    "change detection migration",
)

# 2) Strict audit boolean handling.
replace_once(
    '''def validate_audit_items(\n''',
    '''def audit_excluded(item: dict) -> bool:\n    """Return True only for the literal JSON boolean true."""\n    return item.get("exclude_from_playlist") is True\n\n\ndef validate_audit_items(\n''',
    "insert audit_excluded",
)

replace_once(
    '''    if bool(item.get("exclude_from_playlist")):\n''',
    '''    if audit_excluded(item):\n''',
    "calculate audit exclude",
)

replace_once(
    '''        exclude = bool(item.get("exclude_from_playlist"))\n        if exclude and decision_token in {"verified", "tv_verified", "pc_only"}:\n''',
    '''        if (\n            "exclude_from_playlist" in item\n            and not isinstance(\n                item.get("exclude_from_playlist"),\n                bool,\n            )\n        ):\n            errors.append(\n                f"{label}: exclude_from_playlist must be true or false."\n            )\n\n        exclude = audit_excluded(item)\n        if exclude and decision_token in {"verified", "tv_verified", "pc_only"}:\n''',
    "validate audit exclude type",
)

prepared_bool = '            "exclude_from_playlist": bool(item.get("exclude_from_playlist")),\n'
prepared_count = text.count(prepared_bool)
if prepared_count != 2:
    raise RuntimeError(
        f"prepared audit boolean: expected 2 matches, found {prepared_count}"
    )
text = text.replace(
    prepared_bool,
    '            "exclude_from_playlist": audit_excluded(item),\n',
)

replace_once(
    '        exclude = bool(audit.get("exclude_from_playlist")) if audit else False\n',
    '        exclude = audit_excluded(audit) if audit else False\n',
    "candidate audit exclude",
)

replace_once(
    '''        if bool(\n            audit.get(\n                "exclude_from_playlist"\n            )\n        ):\n''',
    '''        if audit_excluded(audit):\n''',
    "stable audit exclude",
)

path.write_text(text, encoding="utf-8")
print("Applied targeted language-scoping and audit-boolean fixes.")
