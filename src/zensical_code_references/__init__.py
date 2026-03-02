from importlib.metadata import version

from .symbolic_snippets import SymbolicSnippetsExtension

__version__ = version("zensical-code-references")

__all__ = ["SymbolicSnippetsExtension", "__version__"]
