"""P4.1: JavaScript parser via Tree-sitter (requires js extra)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("tree_sitter")
pytest.importorskip("tree_sitter_javascript")

from scopemap.graph_builder import build_graph  # noqa: E402
from scopemap.js_parser import JAVASCRIPT_PARSER_VERSION, JavaScriptParser  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "js_repo"


def test_is_available_with_extra() -> None:
    assert JavaScriptParser().is_available() is True
    assert JavaScriptParser().extensions == frozenset({".js", ".jsx", ".mjs", ".cjs"})
    assert JAVASCRIPT_PARSER_VERSION == 1


def test_require_and_import_resolved() -> None:
    graph = build_graph(FIXTURE)
    imports = {(e.source, e.target) for e in graph.edges if e.kind == "IMPORTS" and e.resolution == "import-resolved"}
    assert ("file:shop/cart.js", "file:lib/util.js") in imports
    assert ("file:web/page.js", "file:shop/cart.js") in imports


def test_calls_across_require_and_import() -> None:
    graph = build_graph(FIXTURE)
    calls = {(e.source, e.target) for e in graph.edges if e.kind == "CALLS" and e.resolution == "direct"}
    assert ("js:shop/cart.js:total", "js:lib/util.js:format") in calls
    assert ("js:web/page.js:render", "js:shop/cart.js:total") in calls


def test_require_never_a_calls_edge() -> None:
    graph = build_graph(FIXTURE)
    assert not [e for e in graph.edges if e.kind == "CALLS" and e.target == "unknown:require"]


def test_bare_package_import_external(tmp_path: Path) -> None:
    app = tmp_path / "app.js"
    app.write_text(
        'import React from "react";\n\nexport function view() {\n  return React.createElement("div");\n}\n',
        encoding="utf-8",
    )
    graph = build_graph(tmp_path)
    assert "unknown:react" in [e.target for e in graph.edges if e.kind == "IMPORTS"]
    # Calls through external packages are skipped, not invented.
    assert not [e for e in graph.edges if e.kind == "CALLS" and "React" in e.target]


def test_minified_files_skipped(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle.min.js"
    bundle.write_text("function a(){return 1}\n", encoding="utf-8")
    graph = build_graph(tmp_path)
    assert "file:bundle.min.js" in graph.nodes
    assert not [node_id for node_id in graph.nodes if node_id.startswith("js:bundle.min.js:")]
