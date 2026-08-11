from pathlib import Path


p = Path("local_epg.py")
text = p.read_text(encoding="utf-8")

anchor = '''def parse_vasarhely(lines: list[str], reference_date: date) -> list[Programme]:
    variants = hu_long_date_variants(reference_date)
    # Hódpress omits the colon after the weekday.
    variants.add(
        folded(
            f"{reference_date.year}. {HU_MONTHS[reference_date.month]} "
            f"{reference_date.day}. {WEEKDAYS[reference_date.weekday()].casefold()}"
        )
    )
    section = slice_section(
        lines,
        lambda value: folded(value) in variants,
        looks_like_hu_dated_heading,
    )
    return parse_entries(section, reference_date, max_entries=80)


'''
addition = anchor + '''def parse_mako(lines: list[str], reference_date: date) -> list[Programme]:
    def marker(value: date) -> str:
        return folded(
            f"{WEEKDAYS[value.weekday()]} {value.strftime('%m.%d')}."
        )

    section = slice_section(
        lines,
        lambda value: folded(value) == marker(reference_date),
        lambda value: folded(value) == marker(reference_date + timedelta(days=1)),
    )

    normalized: list[str] = []
    for line in section:
        match = re.match(r"^(\\d{1,2})[.:](\\d{2})\\s+(.+)$", clean_title(line))
        if match:
            normalized.append(
                f"{int(match.group(1)):02d}:{match.group(2)} {match.group(3)}"
            )
        else:
            normalized.append(line)

    return parse_entries(normalized, reference_date, max_entries=30)


'''
if anchor not in text:
    raise SystemExit("Vásárhely parser anchor not found")
text = text.replace(anchor, addition, 1)

registry = '    "ozd": parse_ozd,\n    "vasarhely": parse_vasarhely,\n    "tvmustra": parse_tvmustra,\n'
registry_new = '    "ozd": parse_ozd,\n    "vasarhely": parse_vasarhely,\n    "mako": parse_mako,\n    "tvmustra": parse_tvmustra,\n'
if registry not in text:
    raise SystemExit("parser registry anchor not found")
text = text.replace(registry, registry_new, 1)

source_anchor = '''        Source(
            "VasarhelyiTelevizio.hu@SD",
            "Vásárhelyi Televízió",
            "hodpress.hu",
            "vasarhely",
            "https://www.hodpress.hu/vtv-musor/",
            8,
        ),
'''
source_new = source_anchor + '''        Source(
            "MakoiVarosiTelevizio.hu@SD",
            "Makói Városi Televízió",
            "makotv.hu",
            "mako",
            "https://makotv.hu/heti-musor/",
            5,
        ),
'''
if source_anchor not in text:
    raise SystemExit("Vásárhely source anchor not found")
text = text.replace(source_anchor, source_new, 1)
p.write_text(text, encoding="utf-8")


t = Path("tests/test_local_epg.py")
tests = t.read_text(encoding="utf-8")
imports = '    parse_entries,\n    parse_ozd,\n    parse_tvmustra,\n'
imports_new = '    parse_entries,\n    parse_mako,\n    parse_ozd,\n    parse_tvmustra,\n'
if imports not in tests:
    raise SystemExit("test import anchor not found")
tests = tests.replace(imports, imports_new, 1)

test_case = '''
    def test_mako_selects_exact_day_and_accepts_dot_times(self):
        programmes = parse_mako(
            [
                "Hétfő 08.10.",
                "18.00 Monday News",
                "Kedd 08.11.",
                "18.00 Híradó – helyi aktuális hírek",
                "18.15 Időjárás előrejelzés",
                "18.19 Ahogy elődeink arattak Makón",
                "19.45 Híradó – helyi aktuális hírek",
                "20:00 Időjárás előrejelzés",
                "Szerda 08.12.",
                "18.00 Wednesday News",
            ],
            date(2026, 8, 11),
        )
        self.assertEqual(
            [item.title for item in programmes],
            [
                "Híradó – helyi aktuális hírek",
                "Időjárás előrejelzés",
                "Ahogy elődeink arattak Makón",
                "Híradó – helyi aktuális hírek",
                "Időjárás előrejelzés",
            ],
        )
        self.assertTrue(all(item.start.date() == date(2026, 8, 11) for item in programmes))
'''
marker = '\n\nif __name__ == "__main__":\n'
if marker not in tests:
    raise SystemExit("test insertion marker not found")
tests = tests.replace(marker, test_case + marker, 1)
t.write_text(tests, encoding="utf-8")

print("Patched Makó exact-day EPG source and tests.")
