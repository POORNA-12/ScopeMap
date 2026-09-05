# ScopeMap — Architecture

**Status:** Gate 2 APPROVED
**Core:** Python 3.12+ stdlib only (`ast`, `pathlib`, `json`,
`argparse`, `subprocess`, `dataclasses`, `collections`, `difflib`).
**Dev tools:** `pytest`, `ruff`. No other runtime dependencies in Phase 1.

## 1. System flow

```text
Git CLI (subprocess: ls-files, diff --name-only, rev-parse)
  -> Scanner (pathlib walk, sorted, skip .venv/.git/__pycache__, 500KB cap)
  -> Python Parser (ast: FunctionDef/Async/ClassDef/Method,
                    Import/ImportFrom + alias, Call raw names, INHERITS bases)
  -> Resolver (stdlib ignore, relative -> path, absolute trial,
               __init__ re-export, alias map,
               dynamic -> unresolved/dynamic, third-party -> external,
               missing -> unresolved)
  -> Graph Builder (nodes file:/python:, edges
                    CONTAINS/DEFINES/IMPORTS/INHERITS/CALLS-direct-only)
  -> Graph Store (dict + reverse imported_by/called_by + atomic JSON write)
  -> Analyzers (Phase 2 impact BFS reverse, Phase 3 guard policy match)
  -> CLI (argparse: index / export / stats / analyze)
```

## 2. Layout (single package)

```text
src/scopemap/
  __init__.py, __main__.py, cli.py,
  models.py, scanner.py, python_parser.py,
  graph_builder.py, graph_store.py, git_diff.py, serializers.py
```

No separate `indexer/`, `graph/`, `analyzers/` packages
until code justifies the split (Ponytail rule).

## 3. Key decisions

- `ast` only, no Tree-sitter in Phase 1. Multi-language is Phase 4+.
- `dict + list` graph, no NetworkX in Phase 1. NetworkX optional
  later for cycles/centrality only with demonstrated need.
- `argparse` only, no Typer in Phase 1.
- `subprocess git`, no GitPython/Dulwich in Phase 1.
- JSON file store, atomic tmp+rename, re-runnable index.
- Reverse indexes `imported_by` / `called_by` for O(1) blast-radius lookup.
- BFS with visited set + depth limit 10 (cycle-safe).
- Per-file `parse_error` record, never whole-run crash.
- Explanation via `Protocol` later (Noop/Ollama/OpenAI adapters).
  Core works with no network, no model, no key.

## 4. Invariants

- Single source of truth: the graph.
- Deterministic sorted output: same repo, same JSON.
- Conservative graph: syntax-derived only, not a complete runtime call graph.
- Evidence over scores: `resolution` + `{file,line,expression}`, no invented confidence.
