"""Explanation backends: evidence-only prompts, graceful degradation."""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import pytest
from test_impact import CORE_V1, CORE_V2, SHOP, _init_repo, _modify

from scopemap.cli import main
from scopemap.explain import (
    NoopExplanationProvider,
    OllamaExplanationProvider,
    OpenAICompatibleExplanationProvider,
    build_prompt,
    explain_findings,
)
from scopemap.models import Evidence, Finding

FINDING = Finding(
    analyzer="impact",
    severity="high",
    title="pay.core.charge may affect 1 component(s)",
    description="Potentially affected (1):\nDirect callers (1):\n  - shop.app.checkout",
    evidence=(Evidence(file="shop/app.py", line=5, expression="charge(amount)"),),
)


class _FakeResponse:
    def __init__(self, payload: dict[str, object], status: int = 200) -> None:
        self._payload = payload
        self.status = status

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> bool:
        return False


def test_prompt_uses_only_evidence() -> None:
    prompt = build_prompt(FINDING)
    assert "shop/app.py:5" in prompt
    assert "Do not invent" in prompt
    assert "charge(amount)" in prompt


def test_noop_returns_empty() -> None:
    provider = NoopExplanationProvider()
    assert provider.available() is True
    assert explain_findings([FINDING], provider) == [(FINDING, "")]


def test_ollama_explains_with_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: object, timeout: object = None) -> _FakeResponse:
        url = request.full_url if isinstance(request, urllib.request.Request) else str(request)
        if url.endswith("/api/tags"):
            return _FakeResponse({})
        return _FakeResponse({"response": "Checkout calls charge."})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    provider = OllamaExplanationProvider(model="test-model")
    assert provider.available() is True
    assert provider.explain(FINDING) == "Checkout calls charge."


def test_ollama_unavailable_degrades(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(request: object, timeout: object = None) -> _FakeResponse:
        raise OSError("no server")

    monkeypatch.setattr(urllib.request, "urlopen", fail)
    provider = OllamaExplanationProvider()
    assert provider.available() is False
    assert provider.explain(FINDING) == ""


def test_openai_needs_key_and_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert OpenAICompatibleExplanationProvider().available() is False
    assert OpenAICompatibleExplanationProvider().explain(FINDING) == ""

    def fake_urlopen(request: object, timeout: object = None) -> _FakeResponse:
        return _FakeResponse({"choices": [{"message": {"content": "Review checkout."}}]})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    provider = OpenAICompatibleExplanationProvider(api_key="key")
    assert provider.explain(FINDING) == "Review checkout."


def test_cli_explain_unavailable_still_reports(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _init_repo(tmp_path / "repo", {"pay/core.py": CORE_V1, "shop/app.py": SHOP})
    _modify(repo, "pay/core.py", CORE_V2)
    assert main(["analyze", "--repo", str(repo), "--diff", "HEAD", "--explain", "ollama"]) == 0
    out = capsys.readouterr().out
    assert "unavailable" in out
    assert "shop.app.checkout" in out
