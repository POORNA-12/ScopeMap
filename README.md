# ScopeMap

Understand the scope of a change before you merge it.

Local-first Python change-impact tool using a deterministic
dependency graph with evidence. Stdlib-only core, offline,
zero mandatory paid services. MIT.

Gate 2 APPROVED. Phase 0 docs in `docs/`.
Phase 1: `python -m scopemap index ./example` (stdlib:
ast, pathlib, json, argparse, subprocess).

Phase 4 adds optional TypeScript/JavaScript indexing (Tree-sitter),
`analyze --format text|json|tree`, and `analyze --interactive`
(Rich explorer with static-tree fallback). Core stays stdlib-only:

```bash
pip install scopemap        # Python only, zero runtime dependencies
pip install scopemap[all]   # + TS/JS parsers + interactive explorer
```

See `docs/cli-contract.md` (section 5) for formats, extras, and
limitations.

## GitHub Action

```yaml
- uses: actions/checkout@v4
  with:
    fetch-depth: 0
- uses: <owner>/ScopeMap@v0.6
  with:
    diff-range: origin/main...HEAD
    fail-on: none # or impact | architecture
```

Posts the impact report as a PR comment and writes
`scopemap-report.md`. Same engine as the CLI; no cloud service.

