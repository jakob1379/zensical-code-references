# zensical-code-references

PoC extension for Zensical that makes `pymdownx.snippets` symbol-aware.

## What this gives you

Markdown usage stays standard:

```text
--8<-- "my_pkg.api:Client.send"
```

You reference symbols instead of brittle line ranges, so snippets stay correct
when code moves.

## Backward compatibility

Existing `pymdownx.snippets` syntax continues to work unchanged. Symbolic
resolution is only applied when the target matches a real Python module under
`module_roots`.

```text
--8<-- "docs/intro.md"
--8<-- "docs/intro.md:intro"
--8<-- "src/my_pkg/api.py:12:20"
--8<-- "my_pkg.api:Client.send"
```

## Install

```bash
uv add zensical-code-references
```

Or:

```bash
pip install zensical-code-references
```

`zensical` is optional. This package works as a Python-Markdown extension without
`zensical`; install `zensical` only if you want to run Zensical builds.

## Why this exists

Raw line ranges are brittle. If code moves, references like `file.py:88:121` rot.

This extension allows snippet references by Python symbol and resolves them to
real line spans at build time using AST.

## Symbol reference format

`<module.path>:<symbol>(.<nested>)[:start[:end]]`

Examples:

- `my_pkg.api:build_payload`
- `my_pkg.api:Client.send`
- `my_pkg.config:DEFAULT_TIMEOUT:-1:2`

Resolved output is rewritten to standard snippets format:

`path/to/file.py:start:end`

For method references without selectors, output uses a multi-range selector so
the class header and method body are included together:

`path/to/file.py:class_header_start:class_header_end,method_start:method_end`

## Selector behavior

- If you don't add a selector, the whole symbol is used.
- For method references with no selector, the selection includes the class declaration line(s) and that method's body, but not other methods in the class (for example, not `__init__`).
- `:start` means "start at this line (relative to the symbol) and go to the end of the symbol."
- `:start:end` means "use only this relative line range inside the symbol."
- Positive numbers are 1-based: `1` is the first line of the symbol.
- `0` and negative numbers are offsets: `0` is the symbol start, `-1` is one line above the symbol start.
- If `start` or `end` goes past the file limits, values are clamped to valid file bounds.
- If the range is invalid (`end < start`), resolution fails.

## Ecosystem comparison

Research summary across `pymdown-extensions`, `mkdocs`, `mkdocs-material`, and
common include plugins:

| Tool / project | Symbol path include (`module:Class.method`) | AST/introspection-based resolution | Generic snippet include | Equivalent to this project |
| --- | --- | --- | --- | --- |
| [`pymdownx.snippets`](https://facelessuser.github.io/pymdown-extensions/extensions/snippets/) | No | No | Yes (file, line ranges, named marker sections) | No |
| [`mkdocs`](https://www.mkdocs.org/user-guide/configuration/#markdown_extensions) | No | No | Not in core (delegates to extensions/plugins) | No |
| [`mkdocs-material`](https://squidfunk.github.io/mkdocs-material/reference/code-blocks/#embedding-external-files) | No | No | Yes via upstream `pymdownx.snippets` | No |
| [`mkdocstrings/python`](https://mkdocstrings.github.io/python/usage/configuration/general/#show_source) | Partial (API object rendering) | Yes (object collection) | No (not a general snippets include engine) | Partial |
| [`mkdocs-codeinclude-plugin`](https://github.com/rnorth/mkdocs-codeinclude-plugin) | No | No | Yes (token/brace-targeted blocks) | No |
| [`mkdocs-include-markdown-plugin`](https://github.com/mondeja/mkdocs-include-markdown-plugin) | No | No | Yes (delimiter-based includes) | No |
| `zensical-code-references` (this project) | Yes | Yes | Yes (rewrites to `pymdownx.snippets` line spans) | Yes |

Bottom line: existing options either slice by lines/markers or render API docs;
none provide first-class symbol-addressed snippet transclusion in the same
workflow as `pymdownx.snippets`.

## Python-Markdown configuration

Use it as a normal Python-Markdown extension, placed before
`pymdownx.snippets`:

```python
import markdown

md = markdown.Markdown(
    extensions=[
        "zensical_symbolic_snippets",
        "pymdownx.snippets",
    ],
    extension_configs={
        "zensical_symbolic_snippets": {
            "module_roots": ["src"],
            "fail_on_unresolved": True,
        },
        "pymdownx.snippets": {
            "base_path": ["src"],
            "check_paths": True,
        },
    },
)
```

## Zensical configuration (`zensical.toml`)

```toml
[project.markdown_extensions.zensical_symbolic_snippets]
module_roots = ["src"]
fail_on_unresolved = true

[project.markdown_extensions.pymdownx.highlight]
anchor_linenums = true
line_spans = "__span"
pygments_lang_class = true

[project.markdown_extensions.pymdownx.snippets]
base_path = ["src"]
check_paths = true

[project.markdown_extensions.pymdownx.superfences]
```

If you define `project.markdown_extensions` explicitly, include all extensions
you rely on. Leaving out `pymdownx.superfences`/`pymdownx.highlight` causes
fenced blocks to render as plain text.

## Included proof project

This repo includes a working Zensical example that references this package's
own source to prove behavior:

- Config: `examples/zensical/zensical.toml`
- Docs page: `examples/zensical/docs/index.md`

Build it:

```bash
uv run zensical build --config-file examples/zensical/zensical.toml
```

Tiny output example (from `examples/zensical/site/index.html`):

```py
def parse_symbolic_reference(value: str) -> SymbolicReference | None:
    if ":" not in value:
        return None
```

## Tests

Run:

```bash
uv run pytest
```

The suite includes parser/resolver tests plus an E2E Zensical build test that
asserts resolved symbols are rendered in generated HTML.

## Release automation

GitHub Actions is configured to publish to PyPI on strict semver tags:

- CI workflow: `.github/workflows/ci.yml`
- Release workflow: `.github/workflows/release.yml`
- Trigger: push tag matching `vX.Y.Z`
- Guardrails: tag must be strict semver and must match `project.version` in `pyproject.toml`
- Gate: test matrix (`3.13`, `3.14`) must pass before publish

One-time GitHub setup for trusted publishing:

1. Create environment `pypi` in repository settings.
2. Configure PyPI Trusted Publisher for this repository/workflow.

Release command:

```bash
git tag v0.1.0
git push upstream v0.1.0
```
