"""P4.2: interactive explorer, fallback, and CLI contract."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from scopemap.graph_builder import Graph
from scopemap.models import Finding
from scopemap.tree_interactive import (
    build_groups,
    is_interactive_available,
    is_rich_available,
    run_interactive,
    show,
)

SRC = Path(__file__).parent.parent / "src" / "scopemap"


def _graph() -> Graph:
    from scopemap.models import Node

    graph = Graph()
    graph.add_node(
        Node(id="file:shop/app.py", kind="file", name="app.py", qualified_name="shop.app", file="shop/app.py")
    )
    graph.add_node(
        Node(
            id="python:shop.app:checkout",
            kind="function",
            name="checkout",
            qualified_name="shop.app.checkout",
            file="shop/app.py",
        )
    )
    graph.add_node(
        Node(
            id="file:tests/test_app.py",
            kind="file",
            name="test_app.py",
            qualified_name="tests.test_app",
            file="tests/test_app.py",
        )
    )
    graph.finalize()
    return graph


def _finding() -> Finding:
    return Finding(
        analyzer="impact",
        severity="high",
        title="shop.app.calc may affect 2 component(s)",
        description="d",
        evidence=(),
        affected=("python:shop.app:checkout", "file:tests/test_app.py"),
    )


def test_no_top_level_rich_import() -> None:
    tree = ast.parse((SRC / "tree_interactive.py").read_text(encoding="utf-8"))
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            names.extend(entry.name for entry in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    assert not [name for name in names if name.startswith("rich")]


def test_build_groups_deterministic_and_bounded() -> None:
    graph = _graph()
    first = build_groups([_finding()], graph)
    second = build_groups([_finding()], graph)
    assert first == second
    assert [name for name, _ in first[0].groups] == ["Direct callers", "Tests"]
    capped = build_groups([_finding()], graph, max_nodes=1)
    assert capped[0].omitted == 1


def test_run_interactive_quits_on_q(capsys: pytest.CaptureFixture[str]) -> None:
    assert run_interactive([_finding()], _graph(), input_fn=lambda _: "q") == 0
    assert "shop.app.calc may affect" in capsys.readouterr().out


def test_run_interactive_expands_group(capsys: pytest.CaptureFixture[str]) -> None:
    answers = iter(["1", "q"])
    printed: list[str] = []
    assert run_interactive([_finding()], _graph(), input_fn=lambda _: next(answers), print_fn=printed.append) == 0
    assert any("shop.app.checkout" in line for line in printed)


def test_run_interactive_eof_exits_cleanly() -> None:
    def _raise(_: str) -> str:
        raise EOFError

    assert run_interactive([_finding()], _graph(), input_fn=_raise, print_fn=lambda _: None) == 0


def test_run_interactive_empty_findings(capsys: pytest.CaptureFixture[str]) -> None:
    assert run_interactive([], _graph(), input_fn=lambda _: "q") == 0
    assert "No potentially affected" in capsys.readouterr().out


def test_show_fallback_without_tty(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("scopemap.tree_interactive.is_interactive_available", lambda: False)
    assert show([_finding()], _graph()) == 0
    out = capsys.readouterr().out
    assert "showing static tree" in out
    assert "|-- " in out or "`-- " in out
    assert "\x1b[" not in out


def test_show_fallback_without_rich(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    monkeypatch.setitem(sys.modules, "rich", None)
    monkeypatch.setitem(sys.modules, "rich.console", None)
    monkeypatch.setitem(sys.modules, "rich.tree", None)
    assert is_rich_available() is False
    assert is_interactive_available() is False
    assert show([_finding()], _graph()) == 0
    assert "showing static tree" in capsys.readouterr().out


def test_cli_rejects_interactive_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from test_impact import _init_repo

    repo = _init_repo(tmp_path / "repo", {"a.py": "x = 1\n"})
    from scopemap.cli import main

    assert main(["analyze", "--repo", str(repo), "--diff", "HEAD", "--interactive", "--format", "json"]) == 2
    assert "cannot be combined" in capsys.readouterr().out


def test_cli_interactive_falls_back_without_tty(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from test_impact import CORE_V1, CORE_V2, SHOP, _init_repo, _modify

    from scopemap.cli import main

    repo = _init_repo(tmp_path / "repo", {"pay/core.py": CORE_V1, "shop/app.py": SHOP})
    _modify(repo, "pay/core.py", CORE_V2)
    assert main(["analyze", "--repo", str(repo), "--diff", "HEAD", "--interactive"]) == 0
    out = capsys.readouterr().out
    assert "showing static tree" in out
    assert "Changed:" in out


def test_run_interactive_empty_enter_emits_newline_between_findings() -> None:
    finding1 = _finding()
    finding2 = Finding(
        analyzer="impact",
        severity="medium",
        title="shop.app.other may affect 1 component(s)",
        description="d",
        evidence=(),
        affected=("python:shop.app:checkout",),
    )
    answers = iter(["", ""])
    printed: list[str] = []
    assert (
        run_interactive([finding1, finding2], _graph(), input_fn=lambda _: next(answers), print_fn=printed.append) == 0
    )
    assert printed == ["", ""]


def test_run_interactive_invalid_choice_recovers_and_emits_single_newline_on_advance() -> None:
    answers = iter(["11", ""])
    printed: list[str] = []
    assert run_interactive([_finding()], _graph(), input_fn=lambda _: next(answers), print_fn=printed.append) == 0
    assert len(printed) == 2
    assert "Unknown choice '11'" in printed[0]
    assert printed[1] == ""


def test_run_interactive_quit_emits_no_trailing_newline() -> None:
    printed: list[str] = []
    assert run_interactive([_finding()], _graph(), input_fn=lambda _: "q", print_fn=printed.append) == 0
    assert "" not in printed


def test_run_interactive_bucket_expansion_emits_newline_only_on_advance() -> None:
    answers = iter(["1", ""])
    printed: list[str] = []
    assert run_interactive([_finding()], _graph(), input_fn=lambda _: next(answers), print_fn=printed.append) == 0
    assert any("shop.app.checkout" in line for line in printed)
    assert printed[-1] == ""
