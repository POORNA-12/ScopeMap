# ScopeMap — Graph Model

Conservative, syntax-derived dependency graph. Not a complete
Python runtime call graph.

## 1. Node

```json
{
  "id": "python:src.auth:login",
  "kind": "function",
  "name": "login",
  "qualified_name": "src.auth.login",
  "file": "src/auth.py",
  "line_start": 10,
  "line_end": 24
}
```

Kinds: `file | function | class | method`.
File node: `{ "id": "file:src/auth.py", "kind": "file", "path": "src/auth.py" }`.
IDs stable across runs. Paths repo-relative.

## 2. Edge

```json
{
  "source": "python:src.api:endpoint",
  "target": "python:src.auth:login",
  "kind": "CALLS",
  "resolution": "direct",
  "evidence": { "file": "src/api.py", "line": 42, "expression": "auth.login()" }
}
```

Kinds Phase 1: `CONTAINS | DEFINES | IMPORTS | INHERITS | CALLS`.
`CALLS` direct-resolvable only in Phase 1
(e.g. `from auth import login` + `login()` in same scope).

Resolution values:

```text
direct            same-file or directly imported name called plainly
import-resolved   import string resolved to a repo file
same-module       def and call in same module
unresolved        target unknown or external package, preserved as unknown:<name>
dynamic           importlib / getattr / registry / import * / variable target
external          reserved for future package-level resolution; third-party imports currently emit unknown:<name> with unresolved
```


Unresolved example (preserved, never dropped):

```json
{
  "source": "python:src.api:endpoint",
  "target": "unknown:login",
  "kind": "CALLS",
  "resolution": "unresolved",
  "evidence": { "file": "src/api.py", "line": 44 }
}
```

## 3. Finding (output contract, no confidence)

```json
{
  "analyzer": "impact",
  "severity": "high",
  "title": "login may affect endpoint",
  "description": "src/auth.py:login changed; src/api.py:endpoint calls it",
  "evidence": [
    { "file": "src/api.py", "line": 42, "expression": "auth.login()" }
  ]
}
```

Severity rubric: `high` = cross-module/public,
`medium` = same-module, `low` = test-only.
Language: "potentially affected", "observed import",
"resolved call", "unresolved dynamic call".
Never "definitely breaks" or "all impacted files".
