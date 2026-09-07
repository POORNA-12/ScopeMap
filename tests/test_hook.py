"""Pre-commit hook: staged analysis, installer, fail-on gates."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest
from test_impact import CORE_V1, CORE_V2, SHOP, _init_repo

from scopemap.cli import main
from scopemap.git_diff import staged_files_detailed, untracked_files


def _stage_change(repo: Path) -> None:
    (repo / "pay" / "core.py").write_text(CORE_V2, encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)


def test_staged_records_and_analyze(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _init_repo(tmp_path / "repo", {"pay/core.py": CORE_V1, "shop/app.py": SHOP})
    _stage_change(repo)
    records = staged_files_detailed(repo)
    assert [record.new_path for record in records] == ["pay/core.py"]
    assert main(["analyze", "--repo", str(repo), "--staged"]) == 0
    out = capsys.readouterr().out
    assert "shop.app.checkout" in out


def test_staged_nothing_and_untracked_note(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _init_repo(tmp_path / "repo", {"pay/core.py": CORE_V1})
    (repo / "new.py").write_text("x = 1\n", encoding="utf-8")
    assert untracked_files(repo) == ["new.py"]
    assert main(["analyze", "--repo", str(repo), "--staged"]) == 0
    out = capsys.readouterr().out
    assert "No potentially affected" in out
    assert "untracked" in out


def test_fail_on_impact(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo", {"pay/core.py": CORE_V1, "shop/app.py": SHOP})
    _stage_change(repo)
    assert main(["analyze", "--repo", str(repo), "--staged", "--fail-on", "impact"]) == 1
    assert main(["analyze", "--repo", str(repo), "--staged", "--fail-on", "none"]) == 0


def test_install_hook_lifecycle(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _init_repo(tmp_path / "repo", {"pay/core.py": CORE_V1})
    assert main(["install-hook", "--repo", str(repo)]) == 0
    hook = repo / ".git" / "hooks" / "pre-commit"
    assert hook.is_file()
    assert bool(hook.stat().st_mode & stat.S_IXUSR)
    assert "--staged" in hook.read_text(encoding="utf-8")
    capsys.readouterr()
    assert main(["install-hook", "--repo", str(repo)]) == 1
    assert "exists" in capsys.readouterr().out
    assert main(["install-hook", "--repo", str(repo), "--force", "--fail-on", "impact"]) == 0
    assert "--fail-on impact" in hook.read_text(encoding="utf-8")


def test_install_hook_rejects_non_repo(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["install-hook", "--repo", str(tmp_path)]) == 1
    assert "Not a git repository" in capsys.readouterr().out


def test_hook_script_runs_end_to_end(tmp_path: Path) -> None:
    import scopemap

    repo = _init_repo(tmp_path / "repo", {"pay/core.py": CORE_V1, "shop/app.py": SHOP})
    assert main(["install-hook", "--repo", str(repo)]) == 0
    _stage_change(repo)
    src = str(Path(scopemap.__file__).parent.parent)
    env = {**os.environ, "PYTHONPATH": src}
    completed = subprocess.run(
        [str(repo / ".git" / "hooks" / "pre-commit")], cwd=repo, capture_output=True, text=True, env=env
    )
    assert completed.returncode == 0
    assert "shop.app.checkout" in completed.stdout


def test_install_hook_with_spaces_in_path(tmp_path: Path) -> None:
    import scopemap

    repo = _init_repo(tmp_path / "repo with spaces", {"pay/core.py": CORE_V1, "shop/app.py": SHOP})
    assert main(["install-hook", "--repo", str(repo)]) == 0
    hook = repo / ".git" / "hooks" / "pre-commit"
    assert hook.is_file()
    _stage_change(repo)
    src = str(Path(scopemap.__file__).parent.parent)
    env = {**os.environ, "PYTHONPATH": src}
    completed = subprocess.run([str(hook)], cwd=repo, capture_output=True, text=True, env=env)
    assert completed.returncode == 0
    assert "shop.app.checkout" in completed.stdout
