"""JavaScript parser via Tree-sitter (P4.1, optional).

Ownership: ES imports/exports AND CommonJS (``require``,
``module.exports``/``exports``). ``require('...')`` produces IMPORTS
edges; bare ``require`` calls never appear as CALLS findings.

Lazy loading only: importing this module never imports ``tree_sitter``.
``is_available()`` reports whether the optional ``js`` extra is installed.
"""

from __future__ import annotations

from typing import Any

from scopemap.tree_sitter_base import TreeSitterParser

JAVASCRIPT_PARSER_VERSION = 1


class JavaScriptParser(TreeSitterParser):
    """Tree-sitter JavaScript adapter implementing the Parser protocol."""

    lang: str = "js"
    extensions: frozenset[str] = frozenset({".js", ".jsx", ".mjs", ".cjs"})
    commonjs: bool = True
    skip_suffixes: tuple[str, ...] = (".min.js",)
    version: int = JAVASCRIPT_PARSER_VERSION

    def grammar(self) -> Any:
        import tree_sitter_javascript as js_grammar
        from tree_sitter import Language

        return Language(js_grammar.language())

    def __repr__(self) -> str:
        return "JavaScriptParser()"
