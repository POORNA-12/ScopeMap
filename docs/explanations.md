# ScopeMap — Optional Ollama Explanations

ScopeMap does not require Ollama. The deterministic graph and impact
analyzer run locally. Ollama is an optional explanation provider: it
receives limited finding metadata and returns plain-text sentences.
It never creates nodes, edges, severity, categories, or coverage.

## Setup

```bash
export SCOPEMAP_EXPLAIN_PROVIDER=ollama
export SCOPEMAP_OLLAMA_URL=http://HOST:11434
export SCOPEMAP_OLLAMA_MODEL=MODEL_NAME
export SCOPEMAP_OLLAMA_TIMEOUT=10
```

Precedence: `--explain` / `--model` flags > `SCOPEMAP_*` >
legacy `OLLAMA_HOST` > built-in defaults. For a fast box prefer a
small model (a 3B model answers in seconds where a 7B model takes
much longer); raise the timeout above 10s on slow networks.

```bash
scopemap analyze --repo . --diff HEAD~1 --explain
```

## Privacy boundary

Only finding metadata is sent: title, severity, description,
file paths, line numbers, short call expressions. Never sent:
file contents, repository archives, graph JSON, environment
variables, API keys, secrets. Repository text inside evidence is
treated as untrusted data and cannot override the explanation rules.

## Failure behavior

Unavailable host, wrong port, missing model, timeout, HTTP error,
invalid JSON, empty answer: the explanation becomes empty, the
deterministic report still prints, and the exit code still reflects
deterministic analysis (`--fail-on`). No retries, no hangs.

## Live smoke test (opt-in, never in CI)

```bash
SCOPEMAP_LIVE_OLLAMA=1 SCOPEMAP_OLLAMA_URL=http://HOST:11434 \
  SCOPEMAP_OLLAMA_MODEL=MODEL pytest -q tests/test_explain_live.py
```

No server address is committed; it comes from your shell.
