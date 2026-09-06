"""P4.0: legacy Python parser functions retain exact behavior."""

from __future__ import annotations

import inspect
from pathlib import Path

from scopemap import python_parser
from scopemap.python_parser import PythonParser, build_module_index, parse_file

FIXTURE = Path(__file__).parent / "fixtures" / "sample_repo"


def test_legacy_signatures_unchanged() -> None:
    assert list(inspect.signature(parse_file).parameters) == ["path", "root", "index"]
    assert list(inspect.signature(build_module_index).parameters) == ["root"]


def test_legacy_parse_file_direct_call() -> None:
    index = build_module_index(FIXTURE)
    nodes, edges = parse_file(FIXTURE / "payments" / "processor.py", FIXTURE, index)
    kinds = {node.kind for node in nodes}
    assert "function" in kinds or "class" in kinds
    assert any(edge.kind in ("DEFINES", "IMPORTS", "CALLS", "CONTAINS") for edge in edges)


def test_adapter_delegates_to_legacy() -> None:
    adapter = PythonParser()
    assert adapter.lang == "python"
    assert adapter.extensions == frozenset({".py"})
    assert adapter.is_available() is True
    index = adapter.build_index(FIXTURE)
    assert index == build_module_index(FIXTURE)
    path = FIXTURE / "payments" / "processor.py"
    assert adapter.parse_file(path, FIXTURE, index) == parse_file(path, FIXTURE, index)


def test_module_still_importable_without_registry() -> None:
    assert callable(python_parser.parse_file)
    assert callable(python_parser.build_module_index)
