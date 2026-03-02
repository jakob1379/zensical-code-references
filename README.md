# zensical-code-references

PoC extension for Zensical that makes `pymdownx.snippets` symbol-aware.

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

## Selector behavior

- No selector: full symbol span.
- Method references without selectors include class header + method body (not sibling methods like `__init__`).
- `:start`: from relative line `start` to symbol end.
- `:start:end`: relative span from symbol start.
- Positive values are 1-based (`1` is first line of symbol).
- `0` and negatives are offsets (`0` is symbol start, `-1` is one line above).

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

Markdown usage stays standard:

```text
--8<-- "my_pkg.api:Client.send"
```

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
