import re
import unittest
from pathlib import Path


class DocumentationNamingTests(unittest.TestCase):
    def test_documentation_does_not_teach_legacy_country_language_fields(self):
        root = Path(__file__).resolve().parents[1]
        paths = [root / "README.md", *sorted((root / "docs").glob("*.md"))]

        forbidden_fields = (
            "default_language_code",
            "language_code",
            "playlist_language_code",
            "output_language_code",
        )

        failures = []
        for path in paths:
            text = path.read_text(encoding="utf-8")
            for field in forbidden_fields:
                if re.search(
                    rf"(?<![A-Za-z0-9_]){re.escape(field)}(?![A-Za-z0-9_])",
                    text,
                ):
                    failures.append(f"{path.relative_to(root)} teaches legacy field {field}")

            for line in text.splitlines():
                for field in ("expected_language_codes", "observed_language_codes"):
                    if field not in line:
                        continue
                    if re.search(r'["`](?:HU|SK|CZ)["`]', line, flags=re.IGNORECASE):
                        failures.append(
                            f"{path.relative_to(root)} uses country-style values for {field}"
                        )

        self.assertEqual(failures, [], "\n".join(failures))


if __name__ == "__main__":
    unittest.main()
