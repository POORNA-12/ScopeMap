"""Task 3: parser extraction and conservative resolution."""

from __future__ import annotations

from pathlib import Path

from scopemap.models import Edge, Node
from scopemap.python_parser import parse_file

FIXTURE = Path(__file__).parent / "fixtures" / "sample_repo"


def _by_kind(edges: list[Edge], kind: str) -> list[Edge]:
    return [edge for edge in edges if edge.kind == kind]  # type: ignore[comparison-overlap]


def _targets(edges: list[Edge]) -> set[str]:
    return {edge.target for edge in edges}


def test_processor_symbols() -> None:
    nodes, edges = parse_file(FIXTURE / "payments" / "processor.py", FIXTURE)
    ids = {node.id for node in nodes}
    assert "python:payments.processor:PaymentProcessor" in ids
    assert "python:payments.processor:retry_payment" in ids
    assert "python:payments.processor:PaymentProcessor.process_payment" in ids
    defines = _targets(_by_kind(edges, "DEFINES"))
    assert "python:payments.processor:PaymentProcessor" in defines
    calls = _by_kind(edges, "CALLS")
    targets = _targets(calls)
    assert "python:payments.processor:PaymentProcessor" in targets
    assert "python:payments.processor:PaymentProcessor._charge" in targets


def test_checkout_import_and_call() -> None:
    _, edges = parse_file(FIXTURE / "checkout" / "service.py", FIXTURE)
    imports = _by_kind(edges, "IMPORTS")
    assert any(edge.target == "file:payments/processor.py" and edge.resolution == "import-resolved" for edge in imports)
    calls = _by_kind(edges, "CALLS")
    assert "python:payments.processor:PaymentProcessor" in _targets(calls)


def test_orders_alias_stdlib_dynamic() -> None:
    nodes, edges = parse_file(FIXTURE / "orders" / "service.py", FIXTURE)
    assert isinstance(nodes, list)
    imports = _by_kind(edges, "IMPORTS")
    assert all("os" not in edge.target for edge in imports)
    assert any(edge.target == "file:payments/processor.py" for edge in imports)
    calls = _by_kind(edges, "CALLS")
    targets = _targets(calls)
    assert "python:payments.processor:retry_payment" in targets
    assert any(target.startswith("unknown:") for target in targets)


def test_init_reexport_resolves() -> None:
    _, edges = parse_file(FIXTURE / "payments" / "__init__.py", FIXTURE)
    imports = _by_kind(edges, "IMPORTS")
    assert any(edge.target == "file:payments/processor.py" for edge in imports)


def test_syntax_error_yields_file_node_only(tmp_path: Path) -> None:
    bad = tmp_path / "bad.py"
    bad.write_text("def broken(:\n")
    nodes, edges = parse_file(bad, tmp_path)
    assert len(nodes) == 1 and nodes[0].kind == "file"
    assert edges == []


def test_node_ids_stable() -> None:
    first, _ = parse_file(FIXTURE / "payments" / "processor.py", FIXTURE)
    second, _ = parse_file(FIXTURE / "payments" / "processor.py", FIXTURE)
    assert [node.id for node in first] == [node.id for node in second]
    assert all(isinstance(node, Node) for node in first)
