"""Opt-in live Ollama smoke test. Skipped unless SCOPEMAP_LIVE_OLLAMA=1.

No server address is hardcoded: URL and model come from the
environment of the machine running the test.

Run from a network that reaches the server, e.g.:

    SCOPEMAP_LIVE_OLLAMA=1 SCOPEMAP_OLLAMA_URL=http://HOST:11434 \
      SCOPEMAP_OLLAMA_MODEL=qwen2.5:3b pytest -q tests/test_explain_live.py
"""

from __future__ import annotations

import os

import pytest

from scopemap.explain import OllamaExplanationProvider
from scopemap.models import Evidence, Finding

pytestmark = pytest.mark.skipif(os.environ.get("SCOPEMAP_LIVE_OLLAMA") != "1", reason="opt-in live Ollama test")

FINDING = Finding(
    analyzer="impact",
    severity="high",
    title="pay.core.charge may affect 1 component(s)",
    description="Potentially affected (1):\nDirect callers (1):\n  - shop.app.checkout",
    evidence=(Evidence(file="shop/app.py", line=5, expression="charge(amount)"),),
)


def test_live_explains() -> None:
    provider = OllamaExplanationProvider()
    assert provider.available(), "server unreachable; check SCOPEMAP_OLLAMA_URL"
    text = provider.explain(FINDING)
    assert isinstance(text, str) and text.strip(), "empty explanation"
