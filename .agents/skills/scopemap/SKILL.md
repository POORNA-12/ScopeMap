---
name: scopemap
description: Deterministic change-impact analysis engine for Python, TypeScript, and JavaScript codebases. Use to analyze blast radius of code changes, enforce architecture boundary guardrails, run targeted pytest suites, and generate interactive visual HTML blast radius reports.
---

# ScopeMap AI Agent Skill

This skill allows AI Coding Assistants (Antigravity, Gemini, Claude, OpenAI, Cursor) to run deterministic change-impact analysis, blast radius mapping, architecture boundary enforcement, and targeted test execution.

## When to Use This Skill

Activate this skill when:
- **PR Audit / Code Review:** Determining what components, functions, or tests are impacted by a set of file changes before merging.
- **Targeted Test Execution:** Running only the tests affected by a code modification rather than running the full test suite.
- **Architecture Validation:** Checking `scopemap.toml` layer boundaries to prevent forbidden imports between modules.
- **Visual Impact Reporting:** Generating standalone, dark-themed interactive HTML reports (`--format html`).
- **Interactive Tree Inspection:** Visualizing caller/dependent trees in the terminal (`scopemap tree`).

---

## Core Capabilities & Workflows

### 1. Change-Impact Analysis (Blast Radius)

Analyze changes in the current working tree against `HEAD~1`, `main`, or any git ref:

```bash
# Basic impact summary on current repository against main branch
scopemap analyze --repo . --diff main

# Get impact report in JSON format for automated agent parsing
scopemap analyze --repo . --diff HEAD~1 --format json
```

### 2. Targeted Test Execution (Fast Feedback Loop)

Instead of running all unit tests, execute only the tests affected by your edits:

```bash
# Output targeted pytest CLI command
scopemap analyze --repo . --diff main --format pytest

# Execute targeted tests directly in shell
pytest $(scopemap analyze --repo . --diff main --format pytest-args)
```

### 3. Visual Offline HTML Report Generation

Generate a rich, single-file, dark-mode visual HTML dashboard featuring interactive SVG graph visualizations:

```bash
# Generate HTML report saved to scopemap_report.html
scopemap analyze --repo . --diff main --format html --output scopemap_report.html
```

### 4. Architectural Boundary Enforcement (`scopemap.toml`)

Validate import boundary rules across architectural layers (e.g. `domain` cannot import `infrastructure`):

```bash
# Run architecture guard checks
scopemap guard --repo .
```

### 5. Interactive CLI Dependency Tree

Inspect caller trees and dependency hierarchies directly in the CLI:

```bash
# Render interactive ASCII tree for a target file
scopemap tree --repo . --file src/scopemap/html_report.py
```

---

## Agent Integration Patterns

### Pre-PR Review Pattern
1. Run `scopemap analyze --repo . --diff main --format json`
2. Parse high-severity findings and affected test counts.
3. Summarize risk levels in the PR description.

### Test-Driven Editing Pattern
1. Edit a source file.
2. Run `pytest $(scopemap analyze --repo . --diff HEAD --format pytest-args)`.
3. Verify affected tests pass before proceeding.

### License & Safety
- Permissively licensed under **MIT License**.
- Zero runtime dependencies required for standard Python graph extraction and impact mapping.
