# ScopeMap — Product Specification

**Status:** Gate 2 APPROVED
**Codename:** ScopeMap (final name pending domain/package check before public launch)
**Tagline:** Understand the scope of a change before you merge it.

## 1. Problem

Python developers merging PRs cannot answer from the repo itself:

- What calls the changed function?
- What files import the changed module?
- Did the change cross an architecture layer boundary?
- What should be inspected or tested?

AI reviewers guess. ScopeMap proves it deterministically.

## 2. Users

- Solo Python developer working locally (Phase 1–2).
- Later: PR reviewer via GitHub comment (Phase 4+). Not in MVP.

## 3. Product promise

> A local-first tool that explains what a Python change may affect,
> using a deterministic dependency graph with evidence.

Principles:

- Deterministic analysis first, AI explanation optional and never in core.
- Conservative claims: "potentially affected", never "definitely breaks".
- Unresolved/dynamic relationships preserved, never silently dropped.
- Offline operation: no API keys, no network, no paid services required.
- Zero mandatory paid services to develop or run locally.

## 4. MVP definition (Phase 1)

`python -m scopemap index ./example` succeeds:

```text
Files: 12, Python files: 9, Nodes: 84, Edges: 137,
Imports: 41, Calls resolved: 28, Calls unresolved: 19
```

Plus `export --output graph.json` and `stats` round-trip.

Phase 2 adds first value: `analyze --diff HEAD~1` lists
potentially affected files/symbols with evidence chains.

## 5. Non-goals (Phase 1–2 blocked)

GitHub App, web dashboard, cloud service, auth, database,
background workers, Celery, Redis, PostgreSQL, RQ,
NetworkX (optional later), Typer (argparse only),
Ollama/AI in core, TypeScript/multi-language,
complete runtime call graph, test-gap prediction,
vulnerability detection, auto code modification.

## 6. Success criteria

- Fixture repo produces stable, asserted counts.
- Resolver handles relative/alias/init re-export/stdlib-ignore.
- Syntax error in one file never crashes whole scan.
- `ruff check` + `pytest -q` green.
- Chandra Gate 5 adversarial audit passes.
