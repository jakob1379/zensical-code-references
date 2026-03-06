from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import markdown
import pytest

from zensical_code_references.symbolic_snippets import (
    SymbolResolver,
    SymbolicSnippetError,
    SymbolicSnippetsExtension,
    parse_symbolic_reference,
)


@pytest.fixture
def docs_workspace(tmp_path):
    package_dir = tmp_path / "example_pkg"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    module_file = package_dir / "module.py"
    module_file.write_text(
        textwrap.dedent(
            """\
            before = "before"
            TARGET = "value"
            after = "after"

            def alpha():
                first = 1
                second = 2
                return first + second

            class Greeter:
                prefix = "hi"

                def __init__(self, prefix="hi"):
                    self.prefix = prefix

                def say(self, name):
                    message = f"{self.prefix} {name}"
                    return message
            """
        ),
        encoding="utf-8",
    )
    (tmp_path / "changelog.md").write_text(
        textwrap.dedent(
            """\
            # Changelog

            --8<-- [start:intro]
            Legacy intro snippet content for compatibility checks.
            --8<-- [end:intro]

            This line should not be included by the intro selector.
            """
        ),
        encoding="utf-8",
    )
    return tmp_path, module_file


def _render(markdown_text: str, module_root, fail_on_unresolved: bool = True) -> str:
    md = markdown.Markdown(
        extensions=[
            SymbolicSnippetsExtension(
                module_roots=[str(module_root)],
                fail_on_unresolved=fail_on_unresolved,
            ),
            "pymdownx.snippets",
        ],
        extension_configs={
            "pymdownx.snippets": {
                "base_path": [str(module_root)],
                "check_paths": False,
            }
        },
    )
    return md.convert(markdown_text)


def test_parse_symbolic_reference_accepts_supported_shape():
    reference = parse_symbolic_reference("example_pkg.module:Greeter.say:1:2")

    assert reference is not None
    assert reference.module == "example_pkg.module"
    assert reference.symbol_parts == ("Greeter", "say")
    assert reference.selector_count == 2
    assert reference.start == 1
    assert reference.end == 2


def test_parse_symbolic_reference_rejects_non_symbolic_targets():
    assert parse_symbolic_reference("docs/example.md:1:5") is None
    assert parse_symbolic_reference("example_pkg/module.py") is None


def test_resolver_returns_file_and_lines_for_symbol(docs_workspace):
    module_root, _ = docs_workspace
    resolver = SymbolResolver(module_roots=[str(module_root)])
    reference = parse_symbolic_reference("example_pkg.module:alpha")
    assert reference is not None

    resolved = resolver.resolve(reference)

    assert resolved.snippet_path == "example_pkg/module.py"
    assert resolved.start_line == 5
    assert resolved.end_line == 8


def test_resolver_includes_class_context_for_method(docs_workspace):
    module_root, _ = docs_workspace
    resolver = SymbolResolver(module_roots=[str(module_root)])
    reference = parse_symbolic_reference("example_pkg.module:Greeter.say")
    assert reference is not None

    resolved = resolver.resolve(reference)

    assert resolved.snippet_path == "example_pkg/module.py"
    assert resolved.start_line == 16
    assert resolved.end_line == 18
    assert resolved.line_selector == "10:10,16:18"


def test_single_line_snippet_includes_function(docs_workspace):
    module_root, _ = docs_workspace

    html = _render('--8<-- "example_pkg.module:alpha"', module_root)

    assert "def alpha():" in html
    assert "return first + second" in html


def test_single_line_snippet_includes_method(docs_workspace):
    module_root, _ = docs_workspace

    html = _render('--8<-- "example_pkg.module:Greeter.say"', module_root)

    assert "class Greeter:" in html
    assert "__init__" not in html
    assert "def say(self, name):" in html
    assert "return message" in html


def test_symbolic_selector_supports_function_subranges(docs_workspace):
    module_root, _ = docs_workspace

    html = _render('--8<-- "example_pkg.module:alpha:1:2"', module_root)

    assert "def alpha():" in html
    assert "first = 1" in html
    assert "return first + second" not in html


def test_symbolic_selector_supports_context_around_variables(docs_workspace):
    module_root, _ = docs_workspace

    html = _render('--8<-- "example_pkg.module:TARGET:-1:2"', module_root)

    assert 'before = "before"' in html
    assert 'TARGET = "value"' in html
    assert 'after = "after"' in html


def test_block_snippet_mode_transforms_symbolic_reference(docs_workspace):
    module_root, _ = docs_workspace

    html = _render(
        textwrap.dedent(
            """\
            --8<--
            example_pkg.module:Greeter.say
            --8<--
            """
        ),
        module_root,
    )

    assert "def say(self, name):" in html


def test_symbol_reference_stays_valid_when_symbol_moves(docs_workspace):
    module_root, module_file = docs_workspace
    first_render = _render('--8<-- "example_pkg.module:alpha"', module_root)

    module_file.write_text(
        textwrap.dedent(
            """\
            before = "before"
            TARGET = "value"
            after = "after"

            def helper():
                return "helper"

            class Extra:
                pass

            def alpha():
                first = 1
                second = 2
                return first + second
            """
        ),
        encoding="utf-8",
    )

    second_render = _render('--8<-- "example_pkg.module:alpha"', module_root)

    assert "def alpha():" in first_render
    assert "def alpha():" in second_render
    assert "return first + second" in second_render


def test_unresolved_symbol_raises_error(docs_workspace):
    module_root, _ = docs_workspace

    with pytest.raises(SymbolicSnippetError):
        _render('--8<-- "example_pkg.module:missing"', module_root)


def test_dotted_file_style_target_is_not_treated_as_symbolic(docs_workspace):
    module_root, _ = docs_workspace

    html = _render('--8<-- "changelog.md:intro"', module_root)

    assert "Legacy intro snippet content for compatibility checks." in html
    assert "This line should not be included" not in html


def test_line_range_target_is_not_treated_as_symbolic(docs_workspace):
    module_root, _ = docs_workspace

    html = _render('--8<-- "example_pkg/module.py:5:8"', module_root)

    assert "def alpha():" in html
    assert "first = 1" in html
    assert "second = 2" in html
    assert "return first + second" in html


def test_invalid_symbolic_selector_syntax_passes_through(docs_workspace):
    module_root, _ = docs_workspace

    html = _render('--8<-- "example_pkg.module:alpha:start"', module_root)

    assert html == ""


def test_unresolved_symbol_can_be_ignored(docs_workspace):
    module_root, _ = docs_workspace

    html = _render(
        '--8<-- "example_pkg.module:missing"',
        module_root,
        fail_on_unresolved=False,
    )

    assert html == ""


def test_zensical_build_renders_symbolic_snippets_from_this_module(tmp_path):
    pytest.importorskip("zensical")

    repo_root = Path(__file__).resolve().parents[1]
    source_root = repo_root / "src"
    docs_dir = tmp_path / "docs"
    site_dir = tmp_path / "site"
    docs_dir.mkdir()

    (docs_dir / "index.md").write_text(
        textwrap.dedent(
            """\
            # Zensical proof

            ```py
            --8<-- "zensical_code_references.symbolic_snippets:parse_symbolic_reference"
            ```
            """
        ),
        encoding="utf-8",
    )

    config_file = tmp_path / "zensical.toml"
    config_file.write_text(
        textwrap.dedent(
            f'''\
            [project]
            site_name = "Symbolic snippets proof"
            docs_dir = "docs"
            site_dir = "site"

            [project.markdown_extensions.zensical_symbolic_snippets]
            module_roots = ["{source_root.as_posix()}"]
            fail_on_unresolved = true

            [project.markdown_extensions.pymdownx.highlight]
            anchor_linenums = true
            line_spans = "__span"
            pygments_lang_class = true

            [project.markdown_extensions.pymdownx.snippets]
            base_path = ["{source_root.as_posix()}"]
            check_paths = true

            [project.markdown_extensions.pymdownx.superfences]
            '''
        ),
        encoding="utf-8",
    )

    subprocess.run(
        [
            sys.executable,
            "-m",
            "zensical",
            "build",
            "--config-file",
            str(config_file),
        ],
        check=True,
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )

    html = (site_dir / "index.html").read_text(encoding="utf-8")
    assert "parse_symbolic_reference" in html
    assert "language-py highlight" in html
    assert "```" not in html
