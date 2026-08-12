#!/usr/bin/env python3
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build.py"
TEMPLATE = ROOT / "templates" / "dashboard.html"
STATIC = ROOT / "static"
DASHBOARD = ROOT / "dashboard.py"
TEST = ROOT / "tests" / "test_dashboard_presentation.py"


def find_dashboard(tree: ast.Module) -> tuple[ast.FunctionDef, ast.Return]:
    fn = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "make_dashboard"
    )
    returns = [node for node in ast.walk(fn) if isinstance(node, ast.Return)]
    for node in returns:
        if not isinstance(node.value, ast.JoinedStr):
            continue
        constants = "".join(
            part.value
            for part in node.value.values
            if isinstance(part, ast.Constant) and isinstance(part.value, str)
        )
        if "<!doctype html>" in constants.lower():
            return fn, node
    raise RuntimeError("Could not find the dashboard HTML f-string return.")


def template_from_joined(value: ast.JoinedStr) -> tuple[str, list[tuple[str, str]]]:
    chunks: list[str] = []
    expressions: list[tuple[str, str]] = []
    token_by_expr: dict[str, str] = {}

    for part in value.values:
        if isinstance(part, ast.Constant):
            if not isinstance(part.value, str):
                raise RuntimeError("Unexpected non-string dashboard f-string constant.")
            chunks.append(part.value)
            continue
        if not isinstance(part, ast.FormattedValue):
            raise RuntimeError(f"Unexpected dashboard f-string node: {type(part).__name__}")
        if part.conversion != -1 or part.format_spec is not None:
            raise RuntimeError("Dashboard f-string conversion/format spec needs manual migration.")
        expr = ast.unparse(part.value)
        token = token_by_expr.get(expr)
        if token is None:
            token = f"V{len(token_by_expr):03d}"
            token_by_expr[expr] = token
            expressions.append((token, expr))
        chunks.append(f"@@{token}@@")

    return "".join(chunks), expressions


def extract_assets(page: str) -> tuple[str, str, str]:
    style_open = "<style>"
    style_close = "</style>"
    script_open = "<script>"
    script_close = "</script>"

    style_start = page.index(style_open)
    style_body_start = style_start + len(style_open)
    style_end = page.index(style_close, style_body_start)
    css = page[style_body_start:style_end].strip("\n") + "\n"
    page = (
        page[:style_start]
        + '<link rel="stylesheet" href="static/dashboard.css">'
        + page[style_end + len(style_close):]
    )

    script_start = page.rindex(script_open)
    script_body_start = script_start + len(script_open)
    script_end = page.index(script_close, script_body_start)
    js = page[script_body_start:script_end].strip("\n") + "\n"
    page = (
        page[:script_start]
        + '<script src="static/dashboard.js" defer></script>'
        + page[script_end + len(script_close):]
    )

    if "<style>" in page or "<script>" in page:
        raise RuntimeError("Inline dashboard style/script remained after extraction.")
    return page, css, js


def build_renderer(
    source: str,
    fn: ast.FunctionDef,
    ret: ast.Return,
    expressions: list[tuple[str, str]],
) -> str:
    lines = source.splitlines(keepends=True)
    prefix = "".join(lines[fn.lineno - 1 : ret.lineno - 1])
    prefix = prefix.replace("def make_dashboard(", "def render_dashboard(", 1)
    signature_tail = "    audit_ambiguity_warnings: list[str],\n) -> str:\n"
    replacement_tail = (
        "    audit_ambiguity_warnings: list[str],\n"
        "    *,\n"
        "    is_tested_status,\n"
        "    format_language_codes,\n"
        ") -> str:\n"
    )
    if signature_tail not in prefix:
        raise RuntimeError("Dashboard signature changed; extraction helper needs updating.")
    prefix = prefix.replace(signature_tail, replacement_tail, 1)

    context = ["    context = {"]
    for token, expr in expressions:
        context.append(f'        "{token}": str({expr}),')
    context.extend([
        "    }",
        "    return _render_dashboard_template(context)",
        "",
    ])

    header = '''#!/usr/bin/env python3
from __future__ import annotations

import html
import shutil
from pathlib import Path


MODULE_ROOT = Path(__file__).resolve().parent
DASHBOARD_TEMPLATE = MODULE_ROOT / "templates" / "dashboard.html"
DASHBOARD_STATIC = MODULE_ROOT / "static"
DASHBOARD_ASSETS = ("dashboard.css", "dashboard.js")


def _render_dashboard_template(context: dict[str, str]) -> str:
    rendered = DASHBOARD_TEMPLATE.read_text(encoding="utf-8")
    for key, value in context.items():
        rendered = rendered.replace(f"@@{key}@@", value)
    if "@@V" in rendered:
        raise RuntimeError("Dashboard template still contains an unresolved value token.")
    return rendered


def copy_dashboard_assets(public_dir: Path) -> None:
    target = public_dir / "static"
    target.mkdir(parents=True, exist_ok=True)
    for name in DASHBOARD_ASSETS:
        shutil.copyfile(DASHBOARD_STATIC / name, target / name)


'''
    return header + prefix + "\n".join(context)


def build_wrapper() -> str:
    return '''def make_dashboard(
    cfg: dict,
    generated: str,
    final_entries: list[dict],
    unique_channels: list[dict],
    source_stats: list[dict],
    language_stats: list[dict],
    duplicate_rows: list[dict],
    changes: dict,
    audit_rows: list[dict],
    audit_ambiguity_warnings: list[str],
) -> str:
    """Render the dashboard through the standalone presentation layer."""
    return render_dashboard(
        cfg=cfg,
        generated=generated,
        final_entries=final_entries,
        unique_channels=unique_channels,
        source_stats=source_stats,
        language_stats=language_stats,
        duplicate_rows=duplicate_rows,
        changes=changes,
        audit_rows=audit_rows,
        audit_ambiguity_warnings=audit_ambiguity_warnings,
        is_tested_status=is_tested_status,
        format_language_codes=format_language_codes,
    )


'''


def main() -> None:
    source = BUILD.read_text(encoding="utf-8")
    tree = ast.parse(source)
    fn, ret = find_dashboard(tree)
    if not isinstance(ret.value, ast.JoinedStr):
        raise AssertionError

    page, expressions = template_from_joined(ret.value)
    page, css, js = extract_assets(page)
    renderer = build_renderer(source, fn, ret, expressions)

    lines = source.splitlines(keepends=True)
    before = "".join(lines[: fn.lineno - 1])
    after = "".join(lines[fn.end_lineno :])
    source = before + build_wrapper() + after

    import_marker = "from pathlib import Path\n"
    dashboard_import = "from dashboard import copy_dashboard_assets, render_dashboard\n"
    if dashboard_import not in source:
        if import_marker not in source:
            raise RuntimeError("Could not locate pathlib import in build.py")
        source = source.replace(import_marker, import_marker + dashboard_import, 1)

    index_marker = '    (public_dir / "index.html").write_text(\n'
    if "copy_dashboard_assets(public_dir)" not in source:
        if index_marker not in source:
            raise RuntimeError("Could not locate dashboard output write in build.py")
        source = source.replace(
            index_marker,
            "    copy_dashboard_assets(public_dir)\n\n" + index_marker,
            1,
        )

    TEMPLATE.parent.mkdir(parents=True, exist_ok=True)
    STATIC.mkdir(parents=True, exist_ok=True)
    TEMPLATE.write_text(page, encoding="utf-8")
    (STATIC / "dashboard.css").write_text(css, encoding="utf-8")
    (STATIC / "dashboard.js").write_text(js, encoding="utf-8")
    DASHBOARD.write_text(renderer, encoding="utf-8")
    BUILD.write_text(source, encoding="utf-8")

    TEST.write_text(
        '''import tempfile
import unittest
from pathlib import Path

import build
from dashboard import copy_dashboard_assets


class DashboardPresentationTests(unittest.TestCase):
    def test_dashboard_presentation_is_outside_build(self):
        source = Path("build.py").read_text(encoding="utf-8")
        self.assertNotIn("<!doctype html>", source.lower())
        self.assertNotIn("<style>", source.lower())
        self.assertNotIn("function renderEpgCountryCoverage", source)
        self.assertIn("from dashboard import copy_dashboard_assets, render_dashboard", source)

    def test_dashboard_template_references_external_assets(self):
        template = Path("templates/dashboard.html").read_text(encoding="utf-8")
        self.assertIn('href="static/dashboard.css"', template)
        self.assertIn('src="static/dashboard.js"', template)
        self.assertNotIn("<style>", template.lower())
        self.assertNotIn("<script>", template.lower())
        self.assertIn("EPG coverage by country", template)
        self.assertIn("Needs attention", template)
        self.assertIn("Automated stream health", template)

    def test_dashboard_assets_are_publishable(self):
        with tempfile.TemporaryDirectory() as tmp:
            public = Path(tmp)
            copy_dashboard_assets(public)
            for name in ("dashboard.css", "dashboard.js"):
                generated = public / "static" / name
                source = Path("static") / name
                self.assertTrue(generated.is_file())
                self.assertEqual(generated.read_bytes(), source.read_bytes())

    def test_existing_build_api_still_exposes_make_dashboard(self):
        self.assertTrue(callable(build.make_dashboard))


if __name__ == "__main__":
    unittest.main()
''',
        encoding="utf-8",
    )

    print(f"Extracted {len(css.splitlines())} CSS lines and {len(js.splitlines())} JS lines.")
    print(f"Dashboard template uses {len(expressions)} dynamic expressions.")


if __name__ == "__main__":
    main()
