#!/usr/bin/env python3
from pathlib import Path


def replace_exact(path: str, old: str, new: str, expected: int = 1) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != expected:
        raise SystemExit(f"{path}: expected {expected} marker(s), found {count}")
    target.write_text(text.replace(old, new), encoding="utf-8")


# The first run proved production grouping was correct; the new test helper simply
# forgot to copy its logo argument into the entry dict (it only put it in EXTINF).
replace_exact(
    "tests/test_logo_quality.py",
    '        "canonical_id": canonical_id,\n        "country_code": country,\n',
    '        "canonical_id": canonical_id,\n        "logo": logo,\n        "country_code": country,\n',
)

# Surface the quality score in CI/build logs as soon as the normal playlist build
# creates the generated logo report.
replace_exact(
    "iptv/build_core.py",
    '    write_logo_quality_outputs(\n        logo_quality,\n        output_path=public_dir / "logo-quality.json",\n        missing_csv_path=public_dir / "missing-logos.csv",\n    )\n\n    source_concentration = build_source_concentration(\n',
    '    write_logo_quality_outputs(\n        logo_quality,\n        output_path=public_dir / "logo-quality.json",\n        missing_csv_path=public_dir / "missing-logos.csv",\n    )\n    logo_summary = logo_quality.get("summary") or {}\n    print(\n        "Logo coverage: "\n        f"{logo_summary.get(\'with_logo\', 0)}/"\n        f"{logo_summary.get(\'stable_logical_channels\', 0)} available "\n        f"({float(logo_summary.get(\'logo_availability_percent\') or 0):.1f}%); "\n        f"{logo_summary.get(\'canonical_logo\', 0)} canonical, "\n        f"{logo_summary.get(\'source_fallback\', 0)} source fallback, "\n        f"{logo_summary.get(\'missing_logo\', 0)} missing."\n    )\n\n    source_concentration = build_source_concentration(\n',
)

print("Fixed logo-quality test fixture and added build summary output.")
