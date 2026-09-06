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

Backends: `ollama` (model: `--model` > `SCOPEMAP_OLLAMA_MODEL`;
URL: `SCOPEMAP_OLLAMA_URL` > legacy `OLLAMA_HOST` > `http://localhost:11434`;
timeout: `SCOPEMAP_OLLAMA_TIMEOUT`, default 10s), `openai` (OPENAI_API_KEY,
OpenAI-compatible `/chat/completions`). `--explain` defaults to
`SCOPEMAP_EXPLAIN_PROVIDER`, else none. Prompts carry
finding metadata only, never file contents. Unreachable backends print
a note and the deterministic report still succeeds. See `docs/explanations.md`.

## 5. Report formats and interactive explorer (Phase 4)

```bash
python -m scopemap analyze --repo . --diff HEAD --format text   # default, unchanged
python -m scopemap analyze --repo . --diff HEAD --format json   # machine-readable
python -m scopemap analyze --repo . --diff HEAD --format tree   # static ASCII tree
python -m scopemap analyze --repo . --diff HEAD --interactive   # Rich explorer (implies tree)
```

Rules:

- `text` output is byte-identical to pre-Phase-4 output when no warnings exist.
- `json` stdout is always valid JSON; warnings live inside the payload
  (`{"summary", "warnings", "findings"}`), never as stray lines.
- `tree` renders a bounded (`max depth 8`, `max nodes 500`), deterministic,
  cycle-safe ASCII tree with explicit omission notices. Piped output carries
  zero ANSI codes.
- `--interactive` needs a TTY plus the `viz` extra; otherwise it prints a note
  and the static tree. `--interactive --format json` exits 2 (conflict).
  `--output` with `--interactive` captures the static tree to the file.

Optional extras (core stays stdlib-only; TS/JS parsers lazy-load):

```bash
pip install scopemap[ts]   # TypeScript (.ts/.tsx/.mts/.cts, skips .d.ts)
pip install scopemap[js]   # JavaScript (.js/.jsx/.mjs/.cjs, skips *.min.js)
pip install scopemap[viz]  # Rich interactive explorer
pip install scopemap[all]  # everything above
```

Limitations (v0.10): no TS/JS `extends` mapping, no default-import call
resolution, no cross-language resolution (preserved as `unresolved`
evidence, never guessed), Go/Rust not supported.
