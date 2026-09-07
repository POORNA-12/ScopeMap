# ScopeMap

> **Understand the full scope and blast-radius of a code change before you merge it.**

ScopeMap is a local-first, deterministic change-impact analysis engine. It extracts syntax-derived dependency graphs with verifiable source code evidence, calculates precise downstream blast-radii across functions, classes, and modules, and enforces architectural boundaries without requiring cloud services or external API keys.

---

## ⚡ Key Highlights

* **100% Stdlib-Only Core:** Zero mandatory runtime dependencies. Built strictly on Python's standard library (`ast`, `pathlib`, `json`, `argparse`, `subprocess`, `hashlib`).
* **Multi-Language Support:** Python AST engine built-in; optional high-performance Tree-sitter parsers for TypeScript (`.ts`, `.tsx`, `.mts`, `.cts`) and JavaScript (`.js`, `.jsx`, `.mjs`, `.cjs`).
* **Deterministic Reverse BFS:** Traces caller and import dependents with visited sets, cycle safety, configurable depth caps, and exact line-level evidence.
* **Visual & Structured Outputs:** Formats impact reports as human-readable text, structured JSON, ASCII trees (`--format tree`), or an interactive TUI explorer (`--interactive`).
* **Zero-Worktree-Mutation Branch Diffs:** Compares branches via `git archive` materialized trees without touching your active working directory.
* **Architecture Boundary Guard:** Enforces layer rules (e.g. `domain` cannot import `adapters`) via `scopemap.toml`.
* **CI & Pre-Commit Ready:** Includes an advisory/blocking Git pre-commit hook installer and a zero-cloud GitHub Action.

---

## 📦 Installation

ScopeMap is distributed as a standard Python package via `pip`:

```bash
# Core installation (Python AST only, zero external runtime dependencies)
pip install scopemap

# With TypeScript/JavaScript Tree-sitter parsers
pip install "scopemap[ts]"
pip install "scopemap[js]"

# With interactive Rich terminal explorer
pip install "scopemap[viz]"

# Full suite (All parsers + interactive visualization)
pip install "scopemap[all]"
```

*Requirements:* Python `>= 3.12`.

---

## 🚀 Quickstart & CLI Commands

### 1. Index a Repository
Scans source files, resolves imports/calls, and generates a deterministic `.scopemap/graph.json` cache:

```bash
scopemap index .
```

### 2. Analyze Changes (Blast-Radius Impact)
Calculates which downstream components and tests are affected by current uncommitted or diffed changes:

```bash
# Analyze uncommitted working tree changes against HEAD
scopemap analyze --repo . --diff HEAD

# Output as an ASCII dependency tree
scopemap analyze --repo . --diff HEAD~1 --format tree

# Interactive terminal explorer (requires scopemap[viz])
scopemap analyze --repo . --diff HEAD~1 --interactive

# Output machine-readable JSON report
scopemap analyze --repo . --diff origin/main...HEAD --format json --output report.json

# Filter to affected test files only
scopemap analyze --repo . --diff HEAD~1 --tests-only
```

### 3. Compare Two Branches or Commits
Computes full differential impact between two git references:

```bash
scopemap compare --repo . --base main --head feature/new-engine
```

### 4. Enforce Architecture Rules
Validates architectural layer boundaries defined in `scopemap.toml`:

```bash
scopemap architecture check --repo .
```


Example `scopemap.toml`:
```toml
[layers]
domain = "src/domain"
services = "src/services"
adapters = "src/adapters"

[[rules]]
name = "domain-cannot-import-adapters"
from = "domain"
deny = ["adapters"]

[[rules]]
name = "services-cannot-import-adapters"
from = "services"
deny = ["adapters"]
```


### 5. Install Git Pre-Commit Hook
Installs a lightweight advisory or blocking pre-commit hook into `.git/hooks/pre-commit`:

```bash
# Advisory hook (warns on commit)
scopemap install-hook --repo .

# Blocking hook (fails commit if impact or architecture violations exist)
scopemap install-hook --repo . --fail-on impact --force
```

---

## 🤖 GitHub Action

Integrate ScopeMap directly into pull request workflows with zero cloud accounts:

```yaml
name: ScopeMap Analysis
on: [pull_request]

jobs:
  impact:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: POORNA-12/ScopeMap@v0.10.0
        with:
          diff-range: ${{ github.event.pull_request.base.sha }}...${{ github.event.pull_request.head.sha }}
          fail-on: none # or impact | architecture
```

---

## 🧠 Optional Privacy-Preserving AI Explanations

ScopeMap can optionally enrich deterministic evidence trails with human-readable change summaries using local (Ollama) or OpenAI-compatible models. **Evidence is strictly sanitized, and no source files are uploaded.**

```bash
# Using local Ollama (100% offline)
scopemap analyze --repo . --diff HEAD~1 --explain ollama --model qwen2.5-coder:7b

# Using OpenAI-compatible endpoint
export SCOPEMAP_OPENAI_API_KEY="sk-..."
scopemap analyze --repo . --diff HEAD~1 --explain openai --model gpt-4o-mini
```

---

## 📄 License

MIT License. See [LICENSE](LICENSE) for details.
