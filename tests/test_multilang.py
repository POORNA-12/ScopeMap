"""P4.1: mixed-language indexing, no collisions, no cross-lang guessing."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

pytest.importorskip("tree_sitter")
pytest.importorskip("tree_sitter_typescript")
pytest.importorskip("tree_sitter_javascript")

from scopemap.cli import main
from scopemap.graph_builder import build_graph

PY_FIXTURE = Path(__file__).parent / "fixtures" / "sample_repo"
TS_FIXTURE = Path(__file__).parent / "fixtures" / "ts_repo"
JS_FIXTURE = Path(__file__).parent / "fixtures" / "js_repo"


def _mixed_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    for fixture in (PY_FIXTURE, TS_FIXTURE, JS_FIXTURE):
        for path in fixture.rglob("*"):
            if path.is_file():
                target = repo / fixture.name.replace("_repo", "") / path.relative_to(fixture)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(path, target)
    # A TS file referencing a Python-only module name: must stay unresolved.
    bridge = repo / "ts" / "shop" / "bridge.ts"
    bridge.write_text(
        'import { x } from "../../py/payments/processor";\n\nexport function go(): number {\n  return 1;\n}\n',
        encoding="utf-8",
    )
    return repo


def test_languages_and_counts(tmp_path: Path) -> None:
    graph = build_graph(_mixed_repo(tmp_path))
    assert graph.meta["languages"] == ["js", "python", "ts"]
    assert graph.meta["parsers"]["python"]["files_indexed"] == 5
    assert graph.meta["parsers"]["ts"]["files_indexed"] == 3
    assert graph.meta["parsers"]["js"]["files_indexed"] == 3


def test_no_id_collisions(tmp_path: Path) -> None:
    graph = build_graph(_mixed_repo(tmp_path))
    prefixes = {node_id.split(":")[0] for node_id in graph.nodes}
    assert prefixes <= {"file", "python", "ts", "js"}


def test_cross_language_never_guessed(tmp_path: Path) -> None:
    graph = build_graph(_mixed_repo(tmp_path))
    assert "unknown:../../py/payments/processor" in [e.target for e in graph.edges if e.kind == "IMPORTS"]
    # No edge may connect symbol namespaces across languages.
    for edge in graph.edges:
        if edge.kind in ("CALLS", "CONTAINS", "DEFINES"):
            source_lang = edge.source.split(":")[0]
            if edge.target.startswith(("python:", "ts:", "js:")):
                assert edge.target.split(":")[0] == source_lang or edge.source.startswith("file:")


def test_mixed_index_per_language_counts(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from scopemap.cli import main

    repo = _mixed_repo(tmp_path)
    assert main(["index", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "Files scanned: 11" in out
    assert "Python files: 5" in out
    assert "TypeScript files: 3" in out
    assert "JavaScript files: 3" in out


def _git(repo: Path, *args: str) -> None:
    import subprocess

    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def test_mixed_analyze_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    import json

    repo = _mixed_repo(tmp_path)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "init")
    target = repo / "ts" / "pay" / "core.ts"
    target.write_text(target.read_text(encoding="utf-8").replace("x + 1", "x + 2"), encoding="utf-8")
    _git(repo, "add", ".")
    assert main(["analyze", "--repo", str(repo), "--diff", "HEAD", "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["findings"] >= 1
