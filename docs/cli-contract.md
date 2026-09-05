# ScopeMap — CLI Contract

Phase 1 proves the core. Phase 2 proves value. No other commands in MVP.

## 1. index

```bash
python -m scopemap index ./example
```

Builds graph, writes `.scopemap/graph.json` (atomic tmp+rename).

Output:

```text
Repository: ./example
Files scanned: 12
Python files: 9
Nodes: 84
Edges: 137
Imports: 41
Calls resolved: 28
Calls unresolved: 19
```

Exit 0 on success, non-zero with per-file errors listed but
scan continues past single-file syntax errors.

## 2. export

```bash
python -m scopemap export ./example --output graph.json
```

Dumps stable sorted JSON `{files, symbols, imports, edges}`.
Reload must rebuild identical reverse indexes.

## 3. stats

```bash
python -m scopemap stats ./example
```

Reads stored JSON, prints same counts as index without rescanning.

## 4. analyze (Phase 2, not Phase 1)

```bash
python -m scopemap analyze --repo ./example --diff HEAD~1
```

Flow: git diff -> changed files -> changed symbols ->
reverse lookup (imported_by/called_by, BFS, visited, depth 10) ->
affected symbols/files/tests -> Findings.

Output:

```text
Changed:
  src/auth.py:login

Potentially affected:
  src/api.py:endpoint
  src/jobs/session_refresh.py:refresh_session
  tests/test_auth.py:test_login

Evidence:
  src/api.py:42 imports and calls auth.login
  src/jobs/session_refresh.py:18 calls auth.login
```

Exit 0 always (advisory). `--strict` for CI later.

Filters: `--depth N`, `--tests-only`, `--direct-only`.

Optional coverage (`coverage.py` JSON, never required):

```bash
python -m scopemap analyze --repo . --diff HEAD~1 --coverage coverage.json
```

Appends a suite-level sentence per finding
(`Coverage (suite): 2/3 changed lines executed (uncovered: 14)`);
per-test names appear only when the report carries line contexts.
Missing/invalid reports exit 1 with a message instead of guessing.

Staged analysis (pre-commit flow):

```bash
python -m scopemap analyze --staged --repo .
python -m scopemap install-hook --repo . [--fail-on impact|architecture] [--force]
```

`--staged` reads the git index instead of a diff range and notes
untracked files it cannot see. `--fail-on` exits 1 on findings
(advisory `none` by default; `architecture` needs `scopemap.toml`).
`install-hook` writes an executable `.git/hooks/pre-commit`;
refuses to overwrite without `--force`.

Optional explanations (never required, never evidence):

```bash
python -m scopemap analyze --repo . --diff HEAD~1 --explain ollama [--model llama3.1]
```

Backends: `ollama` (OLLAMA_HOST or localhost:11434), `openai`
(OPENAI_API_KEY, OpenAI-compatible `/chat/completions`). Prompts carry
finding metadata only, never file contents. Unreachable backends print
a note and the deterministic report still succeeds.
