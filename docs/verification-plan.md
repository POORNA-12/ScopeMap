# ScopeMap — Verification Plan

Gate 3.5 / Gate 4 / Gate 5 entry criteria.

## 1. Fixture repo (exam)

`tests/fixtures/sample_repo/` must contain:

- `payments/processor.py` <- `checkout/service.py`, `orders/service.py`
  (known direct + indirect edges)
- relative import, alias import, `__init__` re-export
- stdlib import (ignored, no edge)
- circular import A<->B (traversal terminates)
- dynamic `importlib` / `getattr` (marked unresolved/dynamic)
- syntax-error file (recorded, scan continues)
- one test file under `tests/`

Expected counts hardcoded in tests
(files/symbols/edges/resolved/unresolved).

## 2. Unit suites

- `test_scanner.py`: discovery, skips, caps, sorted order.
- `test_python_parser.py`: one test per resolver rule
  (relative, alias, init, stdlib, dynamic, missing).
- `test_graph_builder.py`: CONTAINS/IMPORTS/CALLS-direct,
  reverse index correctness, cycle visited-set.
- `test_graph_store.py`: JSON round-trip identical, atomic write.
- `test_git_diff.py`: `--name-only` matches real git output.

## 3. Gates

- Gate 3.5: `ruff check + pytest -q` clean. Any warning = FAIL, loop.
- Gate 4: re-run 3.5 + CLI golden output
  (`index` counts match fixture, `export` reloads).
- Gate 5 (Chandra): empty repo, 500KB+ file, symlink escape,
  two concurrent runs, deep chain depth-limit,
  evidence present on every Finding, no absolute language.

## 4. DoD

- Phase 1 DONE: index/export/stats green on fixture + real repo.
- Phase 2 DONE: analyze shows affected with evidence chains.
- No NetworkX/Typer/GitPython needed to pass.
