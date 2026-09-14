"""Go parser tests via Tree-sitter (requires go extra)."""

from __future__ import annotations

from pathlib import Path

import pytest

tree_sitter = pytest.importorskip("tree_sitter")
pytest.importorskip("tree_sitter_go")

from scopemap.go_parser import GO_PARSER_VERSION, GoParser  # noqa: E402
from scopemap.graph_builder import build_graph  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "go_repo"


def test_is_available_with_extra() -> None:
    assert GoParser().is_available() is True
    assert GoParser().extensions == frozenset({".go"})
    assert GO_PARSER_VERSION == 1


def test_declarations_and_methods() -> None:
    graph = build_graph(FIXTURE)
    assert "go:pay/core.go:Calc" in graph.nodes
    assert "go:pay/core.go:Processor" in graph.nodes
    assert "go:pay/core.go:Processor.Run" in graph.nodes
    assert "go:pay/core.go:Priced" in graph.nodes  # interface recorded as class/type node
    assert "go:shop/app.go:Checkout" in graph.nodes
    assert "go:shop/helper.go:ApplyDiscount" in graph.nodes


def test_module_import_resolved() -> None:
    graph = build_graph(FIXTURE)
    imports = {(e.source, e.target) for e in graph.edges if e.kind == "IMPORTS" and e.resolution == "import-resolved"}
    assert ("file:shop/app.go", "file:pay/core.go") in imports


def test_cross_package_and_intra_package_calls() -> None:
    graph = build_graph(FIXTURE)
    calls = {(e.source, e.target) for e in graph.edges if e.kind == "CALLS" and e.resolution == "direct"}
    # Cross-package call: shop/app.go -> pay/core.go:Calc
    assert ("go:shop/app.go:Checkout", "go:pay/core.go:Calc") in calls
    # Intra-package call across files in same package: shop/app.go -> shop/helper.go:ApplyDiscount
    assert ("go:shop/app.go:Checkout", "go:shop/helper.go:ApplyDiscount") in calls
    # Method call: Processor.Run -> Calc
    assert ("go:pay/core.go:Processor.Run", "go:pay/core.go:Calc") in calls


def test_node_ids_prefixed() -> None:
    graph = build_graph(FIXTURE)
    symbol_ids = [node_id for node_id in graph.nodes if not node_id.startswith("file:")]
    assert symbol_ids and all(node_id.startswith("go:") for node_id in symbol_ids)


def test_missing_import_and_stdlib_preserved_unresolved(tmp_path: Path) -> None:
    lonely = tmp_path / "lonely.go"
    lonely.write_text(
        'package main\n\nimport "fmt"\nimport "./missing"\n\nfunc Run() {\n\tfmt.Println("hi")\n\tmissing.Do()\n}\n',
        encoding="utf-8",
    )
    graph = build_graph(tmp_path)
    unknowns = [e.target for e in graph.edges if e.target.startswith("unknown:")]
    assert "unknown:fmt" in unknowns
    assert "unknown:./missing" in unknowns
    assert "unknown:fmt.Println" in unknowns
    assert "unknown:missing.Do" in unknowns
