from pathlib import Path

path = Path('build.py')
text = path.read_text(encoding='utf-8')

old = '''    country_stats = summarize_country_stats(published_entries, source_stats)\n    language_stats = summarize_language_stats(published_entries, source_stats)\n\n    source_concentration = build_source_concentration(\n        published_entries,\n        cfg,\n        generated_at=generated,\n    )\n    (public_dir / "source-concentration.json").write_text(\n        json.dumps(source_concentration, indent=2, ensure_ascii=False) + "\\n",\n        encoding="utf-8",\n    )\n\n    previous_report = load_previous_report(cfg.get("previous_report_url"))\n'''
new = '''    country_stats = summarize_country_stats(published_entries, source_stats)\n    language_stats = summarize_language_stats(published_entries, source_stats)\n\n    previous_report = load_previous_report(cfg.get("previous_report_url"))\n'''
if text.count(old) != 1:
    raise RuntimeError(f'expected one early concentration block, found {text.count(old)}')
text = text.replace(old, new, 1)

anchor = '''    generated = datetime.now(\n        timezone.utc\n    ).strftime(\n        "%Y-%m-%d %H:%M:%S UTC"\n    )\n\n'''
insert = anchor + '''    source_concentration = build_source_concentration(\n        published_entries,\n        cfg,\n        generated_at=generated,\n    )\n    (public_dir / "source-concentration.json").write_text(\n        json.dumps(source_concentration, indent=2, ensure_ascii=False) + "\\n",\n        encoding="utf-8",\n    )\n\n'''
if text.count(anchor) != 1:
    raise RuntimeError(f'expected one generated timestamp anchor, found {text.count(anchor)}')
text = text.replace(anchor, insert, 1)
path.write_text(text, encoding='utf-8')
