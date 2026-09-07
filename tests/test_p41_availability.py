"""P4.1: lazy optional deps, unavailable-parser warnings, extras validity."""

from __future__ import annotations

import ast
from pathlib import Path

from scopemap.graph_builder import build_graph
from scopemap.parser_registry import get_parser_for_path, register_parser

SRC = Path(__file__).parent.parent / "src" / "scopemap"


def _top_level_imports(module: str) -> list[str]:
    tree = ast.parse((SRC / f"{module}.py").read_text(encoding="utf-8"))
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            names.extend(entry.name for entry in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def test_no_top_level_treesitter_import() -> None:
    for module in ("tree_sitter_base", "ts_parser", "js_parser", "parser_registry", "graph_builder"):
        assert not [name for name in _top_level_imports(module) if name.startswith("tree_sitter")], module


def test_core_imports_without_optional_deps(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import sys

    blocked = ("tree_sitter", "tree_sitter_typescript", "tree_sitter_javascript")
    for name in blocked:
        monkeypatch.setitem(sys.modules, name, None)
    for module in ("scopemap.tree_sitter_base", "scopemap.ts_parser", "scopemap.js_parser"):
        monkeypatch.delitem(sys.modules, module, raising=False)
    from scopemap.js_parser import JavaScriptParser
    from scopemap.ts_parser import TypeScriptParser

    assert TypeScriptParser().is_available() is False
    assert JavaScriptParser().is_available() is False


def test_unavailable_parser_warns_and_skips(tmp_path: Path) -> None:
    from scopemap.parser_api import Parser

    class DeadParser(Parser):
        lang = "dead"
        extensions = frozenset({".zzx"})

        def is_available(self) -> bool:
            return False

        def build_index(self, root: Path) -> dict:
            return {}

        def parse_file(self, path: Path, root: Path, index: object) -> tuple:
            raise AssertionError("must never be called")

    register_parser(DeadParser())
    target = tmp_path / "ghost.zzx"
    target.write_text("zzz\n", encoding="utf-8")
    graph = build_graph(tmp_path)
    warnings = graph.meta["warnings"]
    assert isinstance(warnings, list)
    assert any("dead parser unavailable" in str(warning) and "1 file(s)" in str(warning) for warning in warnings)
    parsers = graph.meta["parsers"]
    assert isinstance(parsers, dict)
    assert parsers["dead"]["files_skipped"] == 1
    assert "file:ghost.zzx" not in graph.nodes


def test_unknown_extension_never_indexed(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("hi\n", encoding="utf-8")
    assert get_parser_for_path(tmp_path / "notes.txt") is None
    graph = build_graph(tmp_path)
    assert graph.nodes == {}


def test_extras_explicit_no_nesting() -> None:
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]
    project = tomllib.loads((Path(__file__).parent.parent / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    extras = project["optional-dependencies"]
    assert set(extras) == {"ts", "js", "viz", "all"}
    for name, pinned in extras.items():
        assert pinned, name
        assert not [item for item in pinned if "scopemap[" in item], name
    assert not project.get("dependencies"), "core must stay stdlib-only"
