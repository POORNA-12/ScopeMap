"""TypeScript parser via Tree-sitter (P4.1, optional).

Ownership: ES imports/exports and TypeScript module syntax
(function, class, method, interface). CommonJS ``require()`` calls in
``.ts`` files are NOT treated as imports; they stay unresolved CALLS
edges (see ``js_parser`` for CommonJS ownership).

Lazy loading only: importing this module never imports ``tree_sitter``.
``is_available()`` reports whether the optional ``ts`` extra is installed.
"""

from __future__ import annotations

from typing import Any

from scopemap.tree_sitter_base import TreeSitterParser

TYPESCRIPT_PARSER_VERSION = 1


class TypeScriptParser(TreeSitterParser):
    """Tree-sitter TypeScript adapter implementing the Parser protocol."""

    lang: str = "ts"
    extensions: frozenset[str] = frozenset({".ts", ".tsx", ".mts", ".cts"})
    commonjs: bool = False
    skip_suffixes: tuple[str, ...] = (".d.ts",)
    version: int = TYPESCRIPT_PARSER_VERSION

    def grammar(self) -> Any:
        import tree_sitter_typescript as ts_grammar
        from tree_sitter import Language

        return Language(ts_grammar.language_typescript())

    def __repr__(self) -> str:
        return "TypeScriptParser()"
