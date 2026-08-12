from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


path = Path("build.py")
text = path.read_text(encoding="utf-8")

# Legacy audit API remains HU/SK/CZ-style even when modern source metadata
# supplies ISO-639-3 hun/slk/ces values.
text = replace_once(
    text,
    '''LANGUAGE_NAME_TO_CODE = {
    "hungarian": "HU",
    "magyar": "HU",

    "slovak": "SK",
    "slovakian": "SK",

    "czech": "CZ",
''',
    '''LANGUAGE_NAME_TO_CODE = {
    "hungarian": "HU",
    "magyar": "HU",
    "hun": "HU",

    "slovak": "SK",
    "slovakian": "SK",
    "slk": "SK",
    "slo": "SK",

    "czech": "CZ",
    "ces": "CZ",
    "cze": "CZ",
''',
    "legacy ISO language aliases",
)

text = replace_once(
    text,
    '''    Audit/source identity and final playlist placement are intentionally
    separate. A technically working stream can be Verified when its observed
    spoken language is supported, and an unambiguous observed language becomes
    the one country/language playlist where that stream is published.

    Unsupported observed languages still reject the stream.
''',
    '''    Audit/source identity, spoken-language acceptance, and publication
    country are intentionally separate. A technically working stream can be
    Verified when its observed spoken language is supported. Publication
    country changes only through an explicit output country or configured
    country-routing rule.

    Unsupported observed languages still reject the stream.
''',
    "audit decision docstring",
)

text = replace_once(
    text,
    '''                    "are currently supported. A single unambiguous "
                    "observed language is published once under that "
                    "language's playlist."
''',
    '''                    "are currently supported. Publication country "
                    "is determined separately by explicit country-routing "
                    "policy."
''',
    "cross-language decision reason",
)

text = replace_once(
    text,
    '''    """Apply audit publication-country decisions without changing spoken language metadata."""
''',
    '''    """Apply country routing and attach verified observed spoken-language metadata."""
''',
    "country router docstring",
)

path.write_text(text, encoding="utf-8")

# Add a regression proving the compatibility boundary explicitly.
test_path = Path("tests/test_country_language_integration.py")
test_text = test_path.read_text(encoding="utf-8")
anchor = '''class CountryLanguageIntegrationTests(unittest.TestCase):
'''
addition = '''class CountryLanguageIntegrationTests(unittest.TestCase):
    def test_legacy_audit_language_api_maps_iso_inputs_to_historical_tokens(self):
        self.assertEqual(
            build.normalize_language_codes(["hun", "slk", "ces"]),
            ["HU", "SK", "CZ"],
        )

'''
test_text = replace_once(
    test_text,
    anchor,
    addition,
    "legacy audit ISO compatibility test",
)
test_path.write_text(test_text, encoding="utf-8")

print("country/language compatibility polish applied")
