from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

from markdown.extensions import Extension
from markdown.preprocessors import Preprocessor

_SINGLE_SNIPPET_RE = re.compile(
    r'^(?P<prefix>\s*-+8<-+\s+")(?P<target>[^"]+)(?P<suffix>"\s*)$'
)
_BLOCK_FENCE_RE = re.compile(r"^\s*-+8<-+\s*$")
_SEGMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class SymbolicSnippetError(ValueError):
    pass


@dataclass(frozen=True)
class SymbolicReference:
    module: str
    symbol_parts: tuple[str, ...]
    selector_count: int
    start: int | None
    end: int | None


@dataclass(frozen=True)
class ResolvedReference:
    snippet_path: str
    start_line: int
    end_line: int
    line_selector: str


def parse_symbolic_reference(value: str) -> SymbolicReference | None:
    if ":" not in value:
        return None

    module, remainder = value.split(":", 1)
    if not _is_dotted_name(module):
        return None

    parts = remainder.split(":")
    if not parts:
        return None

    symbol = parts[0]
    if not _is_dotted_name(symbol):
        return None

    selector_count = len(parts) - 1
    if selector_count > 2:
        return None

    start: int | None = None
    end: int | None = None
    if selector_count >= 1:
        start = _parse_selector(parts[1], value)
    if selector_count == 2:
        end = _parse_selector(parts[2], value)

    return SymbolicReference(
        module=module,
        symbol_parts=tuple(symbol.split(".")),
        selector_count=selector_count,
        start=start,
        end=end,
    )


def _is_dotted_name(value: str) -> bool:
    return bool(value) and all(_SEGMENT_RE.match(part) for part in value.split("."))


def _parse_selector(value: str, raw: str) -> int | None:
    if value == "":
        return None
    try:
        return int(value)
    except ValueError as error:
        raise SymbolicSnippetError(
            f"Invalid selector in symbolic snippet '{raw}'"
        ) from error


class SymbolResolver:
    def __init__(self, module_roots: list[str], encoding: str = "utf-8") -> None:
        if not module_roots:
            raise SymbolicSnippetError("module_roots must contain at least one path")
        self._roots = [Path(root).resolve() for root in module_roots]
        self._encoding = encoding
        self._ast_cache: dict[Path, tuple[ast.Module, int]] = {}

    def resolve(self, reference: SymbolicReference) -> ResolvedReference:
        module_root, module_file = self._resolve_module_path(reference.module)
        tree, line_count = self._load_ast(module_file)
        symbol_path = self._find_symbol_path_in_body(
            tree.body, reference.symbol_parts, reference
        )
        symbol_node = symbol_path[-1]
        symbol_start, symbol_end = self._get_symbol_bounds(symbol_node)
        start_line, end_line = self._select_line_span(
            reference,
            symbol_start,
            symbol_end,
            line_count,
        )

        line_selector = f"{start_line}:{end_line}"
        if (
            reference.selector_count == 0
            and len(symbol_path) >= 2
            and isinstance(symbol_path[-2], ast.ClassDef)
            and isinstance(symbol_node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ):
            class_node = symbol_path[-2]
            class_start = class_node.lineno
            if class_node.decorator_list:
                class_start = min(
                    class_start,
                    *(decorator.lineno for decorator in class_node.decorator_list),
                )
            class_header_selector = f"{class_start}:{class_node.lineno}"
            method_selector = f"{symbol_start}:{symbol_end}"
            line_selector = f"{class_header_selector},{method_selector}"

        try:
            snippet_path = module_file.relative_to(module_root).as_posix()
        except ValueError:
            snippet_path = module_file.as_posix()

        return ResolvedReference(
            snippet_path=snippet_path,
            start_line=start_line,
            end_line=end_line,
            line_selector=line_selector,
        )

    def _resolve_module_path(self, module: str) -> tuple[Path, Path]:
        module_path = Path(*module.split("."))
        for root in self._roots:
            file_candidate = (root / module_path).with_suffix(".py")
            if file_candidate.is_file():
                return root, file_candidate

            package_candidate = root / module_path / "__init__.py"
            if package_candidate.is_file():
                return root, package_candidate

        raise SymbolicSnippetError(
            f"Could not resolve module '{module}' from module_roots"
        )

    def _load_ast(self, module_file: Path) -> tuple[ast.Module, int]:
        cached = self._ast_cache.get(module_file)
        if cached is not None:
            return cached

        source = module_file.read_text(encoding=self._encoding)
        tree = ast.parse(source, filename=module_file.as_posix())
        line_count = len(source.splitlines())
        self._ast_cache[module_file] = (tree, line_count)
        return tree, line_count

    def _find_symbol_path_in_body(
        self,
        body: list[ast.stmt],
        symbol_parts: tuple[str, ...],
        reference: SymbolicReference,
    ) -> tuple[ast.stmt, ...]:
        symbol_name = symbol_parts[0]
        for node in body:
            if not self._node_matches_symbol(node, symbol_name):
                continue

            if len(symbol_parts) == 1:
                return (node,)

            nested_parts = symbol_parts[1:]
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                nested_path = self._find_symbol_path_in_body(
                    node.body, nested_parts, reference
                )
                return (node, *nested_path)

            raise SymbolicSnippetError(
                f"Symbol path '{'.'.join(reference.symbol_parts)}' in module '{reference.module}' is invalid"
            )

        raise SymbolicSnippetError(
            f"Could not resolve symbol '{'.'.join(reference.symbol_parts)}' in module '{reference.module}'"
        )

    def _node_matches_symbol(self, node: ast.stmt, symbol_name: str) -> bool:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return node.name == symbol_name
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == symbol_name:
                    return True
            return False
        if isinstance(node, ast.AnnAssign):
            return isinstance(node.target, ast.Name) and node.target.id == symbol_name
        return False

    def _get_symbol_bounds(self, node: ast.stmt) -> tuple[int, int]:
        start = node.lineno
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and node.decorator_list
        ):
            start = min(start, *(decorator.lineno for decorator in node.decorator_list))

        end = getattr(node, "end_lineno", None)
        if end is None:
            end = node.lineno
        return start, end

    def _select_line_span(
        self,
        reference: SymbolicReference,
        symbol_start: int,
        symbol_end: int,
        line_count: int,
    ) -> tuple[int, int]:
        if line_count <= 0:
            raise SymbolicSnippetError("Resolved module file is empty")

        if reference.selector_count == 0:
            start = symbol_start
            end = symbol_end
        elif reference.selector_count == 1:
            start = self._selector_to_line(symbol_start, reference.start)
            end = symbol_end
        else:
            start = (
                symbol_start
                if reference.start is None
                else self._selector_to_line(symbol_start, reference.start)
            )
            end = (
                symbol_end
                if reference.end is None
                else self._selector_to_line(symbol_start, reference.end)
            )

        start = max(1, min(line_count, start))
        end = max(1, min(line_count, end))
        if end < start:
            raise SymbolicSnippetError(
                "Snippet selector resolved to an invalid line span"
            )
        return start, end

    def _selector_to_line(self, symbol_start: int, value: int | None) -> int:
        if value is None:
            return symbol_start
        if value > 0:
            return symbol_start + value - 1
        return symbol_start + value


class SymbolicSnippetPreprocessor(Preprocessor):
    def __init__(self, md, resolver: SymbolResolver, fail_on_unresolved: bool) -> None:
        super().__init__(md)
        self._resolver = resolver
        self._fail_on_unresolved = fail_on_unresolved

    def run(self, lines: list[str]) -> list[str]:
        output: list[str] = []
        in_block = False

        for line in lines:
            if _BLOCK_FENCE_RE.match(line):
                in_block = not in_block
                output.append(line)
                continue

            if in_block:
                output.append(self._transform_block_line(line))
                continue

            output.append(self._transform_single_line(line))

        return output

    def _transform_single_line(self, line: str) -> str:
        match = _SINGLE_SNIPPET_RE.match(line)
        if not match:
            return line

        target = match.group("target")
        resolved = self._resolve_target(target)
        if resolved is None:
            return line

        return f"{match.group('prefix')}{resolved}{match.group('suffix')}"

    def _transform_block_line(self, line: str) -> str:
        stripped = line.strip()
        if not stripped or stripped.startswith(";"):
            return line

        resolved = self._resolve_target(stripped)
        if resolved is None:
            return line

        indent = line[: len(line) - len(line.lstrip())]
        return f"{indent}{resolved}"

    def _resolve_target(self, target: str) -> str | None:
        reference = parse_symbolic_reference(target)
        if reference is None:
            return None

        try:
            resolved = self._resolver.resolve(reference)
        except SymbolicSnippetError:
            if self._fail_on_unresolved:
                raise
            return None

        return f"{resolved.snippet_path}:{resolved.line_selector}"


class SymbolicSnippetsExtension(Extension):
    def __init__(self, **kwargs) -> None:
        self.config = {
            "module_roots": [["."], "Paths where dotted modules should resolve from"],
            "encoding": ["utf-8", "Encoding used when reading Python source modules"],
            "fail_on_unresolved": [
                True,
                "Fail the build when module or symbol resolution fails",
            ],
        }
        super().__init__(**kwargs)

    def extendMarkdown(self, md) -> None:
        module_roots = self.getConfig("module_roots")
        if isinstance(module_roots, str):
            normalized_roots = [module_roots]
        else:
            normalized_roots = list(module_roots)

        resolver = SymbolResolver(
            module_roots=normalized_roots,
            encoding=self.getConfig("encoding"),
        )
        md.preprocessors.register(
            SymbolicSnippetPreprocessor(
                md,
                resolver=resolver,
                fail_on_unresolved=self.getConfig("fail_on_unresolved"),
            ),
            "zensical-symbolic-snippets",
            40,
        )


def makeExtension(**kwargs) -> SymbolicSnippetsExtension:
    return SymbolicSnippetsExtension(**kwargs)
