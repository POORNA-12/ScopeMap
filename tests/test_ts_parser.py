"""P4.1: TypeScript parser via Tree-sitter (requires ts extra)."""

from __future__ import annotations

from pathlib import Path

import pytest

tree_sitter = pytest.importorskip("tree_sitter")
pytest.importorskip("tree_sitter_typescript")

from scopemap.graph_builder import build_graph  # noqa: E402
from scopemap.ts_parser import TYPESCRIPT_PARSER_VERSION, TypeScriptParser  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "ts_repo"


def test_is_available_with_extra() -> None:
    assert TypeScriptParser().is_available() is True
    assert TypeScriptParser().extensions == frozenset({".ts", ".tsx", ".mts", ".cts"})
    assert TYPESCRIPT_PARSER_VERSION == 1


def test_declarations_and_methods() -> None:
    graph = build_graph(FIXTURE)
    assert "ts:pay/core.ts:calc" in graph.nodes
    assert "ts:pay/core.ts:Processor" in graph.nodes
    assert "ts:pay/core.ts:Processor.run" in graph.nodes
    assert "ts:pay/core.ts:Priced" in graph.nodes  # interface recorded
    assert "ts:shop/app.ts:checkout" in graph.nodes


def test_relative_import_resolved() -> None:
    graph = build_graph(FIXTURE)
    imports = {(e.source, e.target) for e in graph.edges if e.kind == "IMPORTS" and e.resolution == "import-resolved"}
    assert ("file:shop/app.ts", "file:pay/core.ts") in imports


def test_named_and_namespace_calls_resolved() -> None:
    graph = build_graph(FIXTURE)
    calls = {(e.source, e.target) for e in graph.edges if e.kind == "CALLS" and e.resolution == "direct"}
    assert ("ts:shop/app.ts:checkout", "ts:pay/core.ts:calc") in calls
    assert ("ts:pay/core.ts:Processor.run", "ts:pay/core.ts:calc") in calls


def test_node_ids_prefixed() -> None:
    graph = build_graph(FIXTURE)
    symbol_ids = [node_id for node_id in graph.nodes if not node_id.startswith("file:")]
    assert symbol_ids and all(node_id.startswith("ts:") for node_id in symbol_ids)


def test_dts_files_skipped(tmp_path: Path) -> None:
    stub = tmp_path / "types.d.ts"
    stub.write_text("export function ghost(): void;\n", encoding="utf-8")
    graph = build_graph(tmp_path)
    assert "file:types.d.ts" in graph.nodes
    assert not [node_id for node_id in graph.nodes if node_id.startswith("ts:types.d.ts:")]


def test_missing_import_preserved_unresolved(tmp_path: Path) -> None:
    lonely = tmp_path / "lonely.ts"
    lonely.write_text(
        'import { x } from "./missing";\n\nexport function use(): number {\n  return x(1);\n}\n', encoding="utf-8"
    )
    graph = build_graph(tmp_path)
    unknowns = [e.target for e in graph.edges if e.target.startswith("unknown:")]
    assert "unknown:./missing" in unknowns
    assert "unknown:x" in unknowns  # call preserved, never guessed
