"""P4.0: analyze --format text|json|tree and warning-stream separation."""

from __future__ import annotations

import json
from pathlib import Path

from test_impact import _init_repo, _modify

from scopemap.cli import main

CORE_V1 = "def calc(x):\n    return x + 1\n"
CORE_V2 = "def calc(x):\n    return x + 2\n"
SHOP = "from pay.core import calc\n\n\ndef checkout():\n    return calc(1)\n"


def test_default_text_output_unchanged(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    repo = _init_repo(tmp_path / "repo", {"pay/core.py": CORE_V1, "shop/app.py": SHOP})
    _modify(repo, "pay/core.py", CORE_V2)
    assert main(["analyze", "--repo", str(repo), "--diff", "HEAD"]) == 0
    out = capsys.readouterr().out
    assert "Changed:" in out
    assert "shop.app.checkout" in out


def test_tree_format_renders_tree(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    repo = _init_repo(tmp_path / "repo", {"pay/core.py": CORE_V1, "shop/app.py": SHOP})
    _modify(repo, "pay/core.py", CORE_V2)
    assert main(["analyze", "--repo", str(repo), "--diff", "HEAD", "--format", "tree"]) == 0
    out = capsys.readouterr().out
    assert "ScopeMap impact:" in out
    assert "Changed:" in out
    assert "|-- " in out or "`-- " in out
    assert "\x1b[" not in out


def test_json_format_valid_with_warnings(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    repo = _init_repo(tmp_path / "repo", {"pay/core.py": CORE_V1, "shop/app.py": SHOP})
    _modify(repo, "pay/core.py", CORE_V2)
    assert main(["analyze", "--repo", str(repo), "--diff", "HEAD", "--format", "json"]) == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["format"] == "json"
    assert isinstance(payload["warnings"], list)
    assert payload["summary"]["findings"] >= 1
    assert isinstance(payload["findings"], list)
    assert payload["findings"][0]["title"]


def test_tree_format_to_output_file(tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    repo = _init_repo(tmp_path / "repo", {"pay/core.py": CORE_V1, "shop/app.py": SHOP})
    _modify(repo, "pay/core.py", CORE_V2)
    output = tmp_path / "report.txt"
    assert main(["analyze", "--repo", str(repo), "--diff", "HEAD", "--format", "tree", "--output", str(output)]) == 0
    text = output.read_text(encoding="utf-8")
    assert "Changed:" in text


def test_tree_format_empty_findings_single_line(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    repo = _init_repo(tmp_path / "repo", {"pay/core.py": CORE_V1, "shop/app.py": SHOP})
    assert main(["analyze", "--repo", str(repo), "--diff", "HEAD", "--format", "tree"]) == 0
    out = capsys.readouterr().out
    assert out.count("No potentially affected components found.") == 1

