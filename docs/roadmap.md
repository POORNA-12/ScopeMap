# ScopeMap — Roadmap

## Phase 0 — Docs (this task, no code)

Freeze product-spec, architecture, graph-model, cli-contract,
verification-plan, license-and-attribution, roadmap.
Gate 2 APPROVED.

## Phase 1 — Core (stdlib only)

Scanner, parser, resolver, graph, store, git_diff (subprocess),
CLI index/export/stats, fixture + tests.
DoD: stable counts + JSON round-trip + ruff/pytest green.

## Phase 2 — Impact

`analyze --diff HEAD~1`: diff -> symbols -> reverse BFS ->
affected + evidence. Cautious language only.
DoD: fixture blast-radius matches expected chains.

## Phase 3 — Architecture Guard

`scopemap.yaml` layers/rules, IMPORTS-edge policy match.
DoD: violation Finding with source/target/line evidence.
No new indexer needed.

## Phase 4+ — Deferred

Tree-sitter (multi-lang), NetworkX (advanced algorithms),
Typer (large CLI), Dulwich, Pydantic/FastAPI, RQ/Redis,
PostgreSQL, GitHub App, dashboard, Ollama ExplanationProvider.
Each needs demonstrated need + Gate 2 re-review.
Rule: a dependency must solve a demonstrated problem
and have a clear removal boundary.
