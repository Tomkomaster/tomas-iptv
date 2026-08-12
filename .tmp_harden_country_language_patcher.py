from pathlib import Path

path = Path('.tmp_country_language_refactor.py')
text = path.read_text(encoding='utf-8')

old = '''def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)
'''
new = '''def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        if label == "audit output row country fields" and count > 0:
            return text.replace(old, new, 1)
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)
'''
if text.count(old) != 1:
    raise SystemExit('replace_once helper anchor changed')
text = text.replace(old, new, 1)

old = '''def replace_region(text: str, start: str, end: str, new: str, label: str) -> str:
    start_i = text.find(start)
    if start_i < 0:
        raise SystemExit(f"{label}: start marker not found")
    end_i = text.find(end, start_i)
    if end_i < 0:
        raise SystemExit(f"{label}: end marker not found")
    return text[:start_i] + new.rstrip() + "\\n\\n" + text[end_i:]
'''
new = '''def replace_region(text: str, start: str, end: str, new: str, label: str) -> str:
    start_i = text.find(start)
    if start_i < 0 and start.endswith("(\\n"):
        start_i = text.find(start[:-1])
    if start_i < 0:
        raise SystemExit(f"{label}: start marker not found")
    end_i = text.find(end, start_i)
    if end_i < 0 and end.endswith("(\\n"):
        end_i = text.find(end[:-1], start_i)
    if end_i < 0:
        raise SystemExit(f"{label}: end marker not found")
    return text[:start_i] + new.rstrip() + "\\n\\n" + text[end_i:]
'''
if text.count(old) != 1:
    raise SystemExit('replace_region helper anchor changed')
text = text.replace(old, new, 1)

text = text.replace(
    'text = text.replace("route_candidates_to_verified_languages(\\n", "route_candidates_to_verified_countries(\\n")',
    'text = text.replace("    route_candidates_to_verified_languages(\\n", "    route_candidates_to_verified_countries(\\n")',
)

path.write_text(text, encoding='utf-8')
print('primary patcher hardened')
