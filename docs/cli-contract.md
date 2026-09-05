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
