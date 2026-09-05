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


def _parse_source(tmp_path: Path, files: dict[str, str], target: str) -> tuple[list[Node], list[Edge]]:
    for relative, content in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return parse_file(tmp_path / target, tmp_path)


def test_constructor_call_same_file(tmp_path: Path) -> None:
    source = "class Worker:\n    def run(self):\n        return 1\n\n\ndef start():\n    return Worker().run()\n"
    _, edges = _parse_source(tmp_path, {"svc.py": source}, "svc.py")
    calls = [edge for edge in edges if edge.kind == "CALLS" and edge.target.endswith(":Worker.run")]
    assert len(calls) == 1
    assert calls[0].resolution == "constructor-resolved"


def test_constructor_call_imported_class_is_class_level(tmp_path: Path) -> None:
    _, edges = _parse_source(
        tmp_path,
        {
            "lib.py": "class Engine:\n    def run(self):\n        return 1\n",
            "app.py": "from lib import Engine\n\n\ndef start():\n    return Engine().run()\n",
        },
        "app.py",
    )
    calls = [edge for edge in edges if edge.kind == "CALLS"]
    targets = {edge.target for edge in calls}
    assert "python:lib:Engine" in targets
    assert any(edge.target == "python:lib:Engine" and edge.resolution == "constructor-resolved" for edge in calls)


def test_variable_bound_call(tmp_path: Path) -> None:
    _, edges = _parse_source(
        tmp_path,
        {
            "svc.py": (
                "class Worker:\n    def run(self):\n        return 1\n"
                "\n\ndef start():\n    worker = Worker()\n    return worker.run()\n"
            )
        },
        "svc.py",
    )
    calls = [edge for edge in edges if edge.kind == "CALLS" and edge.target.endswith(":Worker.run")]
    assert len(calls) == 1
    assert calls[0].resolution == "constructor-resolved"


def test_variable_bound_unknown_stays_unresolved(tmp_path: Path) -> None:
    _, edges = _parse_source(
        tmp_path,
        {"svc.py": "def start(get_handler):\n    handler = get_handler()\n    return handler(1)\n"},
        "svc.py",
    )
    calls = [edge for edge in edges if edge.kind == "CALLS"]
    assert any(edge.target == "unknown:handler" and edge.resolution == "unresolved" for edge in calls)


def test_registry_dict_call_resolves(tmp_path: Path) -> None:
    source = "def login():\n    return 1\n\nHANDLERS = {'go': login}\n\n\ndef dispatch():\n"
    source += "    return HANDLERS['go']()\n"
    _, edges = _parse_source(tmp_path, {"svc.py": source}, "svc.py")
    calls = [edge for edge in edges if edge.kind == "CALLS"]
    assert any(edge.target.endswith(":login") and edge.resolution == "direct" for edge in calls)


def test_registry_unknown_key_stays_unresolved(tmp_path: Path) -> None:
    source = "def login():\n    return 1\n\nHANDLERS = {'go': login}\n\n\ndef dispatch(key):\n"
    source += "    return HANDLERS[key]()\n"
    _, edges = _parse_source(tmp_path, {"svc.py": source}, "svc.py")
    calls = [edge for edge in edges if edge.kind == "CALLS"]
    assert any(edge.target.startswith("unknown:") for edge in calls)
