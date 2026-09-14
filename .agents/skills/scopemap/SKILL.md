---
name: scopemap
description: Deterministic change-impact analysis engine for Python, TypeScript, JavaScript, and Go codebases. Use to analyze blast radius of code changes, enforce architecture boundary guardrails, run targeted test suites, and generate interactive visual HTML blast radius reports.
---

# ScopeMap AI Agent Skill

This skill allows AI Coding Assistants (Antigravity, Gemini, Claude, OpenAI, Cursor) to run deterministic change-impact analysis, blast radius mapping, architecture boundary enforcement, and targeted test execution across **Python, TypeScript, JavaScript, and Go** repositories.

## When to Use This Skill

Activate this skill when:
- **PR Audit / Code Review:** Determining what components, functions, or tests are impacted by a set of file changes before merging.
- **Targeted Test Execution:** Running only the tests affected by a code modification (`--tests-only`) rather than running the full test suite.
- **Architecture Validation:** Checking `scopemap.toml` layer boundaries to prevent forbidden imports between modules (`scopemap architecture check`).
- **Visual Impact Reporting:** Generating standalone, dark-themed interactive HTML reports (`--format html`, `--renderer bokeh`).
- **Interactive Tree Inspection:** Visualizing caller/dependent trees in the terminal (`scopemap analyze --format tree`).

---

## ScopeMap Installation

ScopeMap can be installed either directly from **GitHub (Git)** or via **PyPI (`pip`)**:

```bash
# Option 1: Core stdlib Python installation
pip install scopemap

# Option 2: Individual language / visualizer extras
pip install "scopemap[go]"     # Go Tree-sitter parser
pip install "scopemap[ts]"     # TypeScript Tree-sitter parser
pip install "scopemap[js]"     # JavaScript Tree-sitter parser
pip install "scopemap[bokeh]"  # Interactive Bokeh network visualizer
pip install "scopemap[viz]"    # Rich terminal TUI interactive explorer

# Option 3: Full suite (All parsers + visualizers)
pip install "scopemap[all] @ git+https://github.com/POORNA-12/ScopeMap.git"
```

---

## Core Capabilities & Workflows

### 1. Change-Impact Analysis (Blast Radius)

Analyze changes in the current working tree against `HEAD~1`, `main`, or any git ref:

```bash
# Basic impact summary on current repository against main branch
scopemap analyze --repo . --diff main

# Get impact report in JSON format for automated agent parsing
scopemap analyze --repo . --diff HEAD~1 --format json

# Filter specifically to affected test files
scopemap analyze --repo . --diff HEAD~1 --tests-only
```

### 2. Targeted Test Execution (Fast Feedback Loop)

Filter down impact findings to only the test files affected by your edits:

```bash
# List only affected test files
scopemap analyze --repo . --diff HEAD --tests-only

# Run tests on the affected files
pytest $(scopemap analyze --repo . --diff HEAD --tests-only --format json | jq -r '.findings[].affected[].file' | sort -u)
```

### 3. Visual Offline HTML Report Generation

Generate a rich, single-file, dark-mode visual HTML dashboard featuring interactive SVG or Bokeh graph visualizations:

```bash
# Generate HTML report with SVG graph
scopemap analyze --repo . --diff main --format html --output scopemap_report.html

# Generate HTML report with dual-layout Bokeh network graph
scopemap analyze --repo . --diff main --format html --renderer bokeh --output scopemap_report.html
```

### 4. Architectural Boundary Enforcement (`scopemap.toml`)

Validate import boundary rules across architectural layers (e.g. `domain` cannot import `infrastructure`):

```bash
# Run architecture guard checks
scopemap architecture check --repo .
```

### 5. Interactive Dependency Tree

Inspect caller trees and dependency hierarchies directly in the terminal:

```bash
# Render ASCII tree for affected changes
scopemap analyze --repo . --diff HEAD~1 --format tree
```

---

## Agent Integration Patterns

### Pre-PR Review Pattern
1. Run `scopemap analyze --repo . --diff main --format json`
2. Parse high-severity findings and affected test counts.
3. Summarize risk levels and blast radius in the PR description.

### Test-Driven Editing Pattern
1. Edit a source file.
2. Run `scopemap analyze --repo . --diff HEAD --tests-only`.
3. Execute affected tests to verify fast feedback.

### License & Safety
- Permissively licensed under **MIT License**.
- Zero runtime dependencies required for standard Python graph extraction and impact mapping.
