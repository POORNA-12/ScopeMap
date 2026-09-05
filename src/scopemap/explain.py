"""Optional natural-language explanations for deterministic findings.

The graph is the source of truth: providers receive only finding
metadata (titles, paths, line numbers, short expressions), never file
contents. When no provider is available the analysis still succeeds;
explanations are decoration, never evidence.
"""

from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass
from typing import Protocol

from scopemap.models import Finding

TIMEOUT_SECONDS = 10


class ExplanationProvider(Protocol):
    """Explain one finding in plain language."""

    def explain(self, finding: Finding) -> str:
        """Return an explanation, or "" when unavailable."""
        ...

    def available(self) -> bool:
        """True when the backend is reachable."""
        ...


def build_prompt(finding: Finding) -> str:
    """Render the evidence-only prompt; no source contents included."""
    lines = [
        "Explain this code-change impact finding for a developer.",
        "Use ONLY the evidence below. Do not invent dependencies, files, or severity.",
        f"Title: {finding.title}",
        f"Severity: {finding.severity}",
        f"Details: {finding.description}",
        "Evidence:",
    ]
    for item in finding.evidence:
        location = f"{item.file}:{item.line}" if item.line else item.file
        lines.append(f"- {location} {item.expression}".rstrip())
    lines.append("Keep it under 5 sentences.")
    return "\n".join(lines)


@dataclass(frozen=True)
class NoopExplanationProvider:
    """Default provider: no explanations, deterministic output only."""

    def explain(self, finding: Finding) -> str:
        _ = finding
        return ""

    def available(self) -> bool:
        return True


def _post_json(url: str, payload: dict[str, object], headers: dict[str, str]) -> dict[str, object]:
    request = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        body = response.read().decode("utf-8")
    data = json.loads(body)
    if not isinstance(data, dict):
        raise ValueError("provider returned a non-object response")
    return data


@dataclass(frozen=True)
class OllamaExplanationProvider:
    """Local Ollama backend. Host from OLLAMA_HOST or localhost:11434."""

    model: str = "llama3.1"
    host: str = ""

    def _base(self) -> str:
        return self.host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")

    def available(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self._base()}/api/tags", timeout=TIMEOUT_SECONDS) as response:
                return response.status == 200
        except (OSError, ValueError):
            return False

    def explain(self, finding: Finding) -> str:
        try:
            data = _post_json(
                f"{self._base()}/api/generate",
                {"model": self.model, "prompt": build_prompt(finding), "stream": False},
                {"Content-Type": "application/json"},
            )
        except (OSError, ValueError, KeyError):
            return ""
        response = data.get("response", "")
        return str(response).strip()


@dataclass(frozen=True)
class OpenAICompatibleExplanationProvider:
    """Any OpenAI-compatible chat API. Key from OPENAI_API_KEY."""

    model: str = "gpt-4o-mini"
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""

    def _key(self) -> str:
        return self.api_key or os.environ.get("OPENAI_API_KEY", "")

    def available(self) -> bool:
        return bool(self._key())

    def explain(self, finding: Finding) -> str:
        if not self._key():
            return ""
        try:
            data = _post_json(
                f"{self.base_url.rstrip('/')}/chat/completions",
                {
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": "You explain code-review findings using only given evidence."},
                        {"role": "user", "content": build_prompt(finding)},
                    ],
                },
                {"Content-Type": "application/json", "Authorization": f"Bearer {self._key()}"},
            )
        except (OSError, ValueError, KeyError):
            return ""
        try:
            choices = data["choices"]
            assert isinstance(choices, list) and choices
            message = choices[0]["message"]["content"]
            return str(message).strip()
        except (KeyError, IndexError, TypeError, AssertionError):
            return ""


def explain_findings(findings: list[Finding], provider: ExplanationProvider) -> list[tuple[Finding, str]]:
    """Pair each finding with its explanation (possibly empty)."""
    return [(finding, provider.explain(finding)) for finding in findings]
