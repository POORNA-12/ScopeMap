# How to Use ScopeMap as an AI Agent Skill

ScopeMap is built to seamlessly integrate into AI coding agents (Antigravity, Gemini CLI, Claude Code, Cursor, AutoGPT). By registering ScopeMap as a **Skill**, your AI agent can deterministically calculate blast radius, run targeted test suites, enforce architectural boundary rules, and generate visual HTML reports.

---

## 1. Quick Skill Registration

### For Antigravity / Gemini CLI Agents
Copy the [`SKILL.md`](file:///.agents/skills/scopemap/SKILL.md) file into your project's `.agents/skills/scopemap/` directory:

```bash
mkdir -p .agents/skills/scopemap
cp /path/to/ScopeMap/.agents/skills/scopemap/SKILL.md .agents/skills/scopemap/SKILL.md
```

### For Claude / Cursor / Custom Agent Systems
Add the following system instructions or prompt block to your agent configuration:

```markdown
When reviewing pull requests, modifying code, or running tests:
1. Use `scopemap analyze --repo . --diff main` to inspect blast radius.
2. Run targeted tests with `pytest $(scopemap analyze --repo . --diff main --format pytest-args)`.
3. Check architectural boundary compliance with `scopemap guard --repo .`.
4. Generate offline HTML reports with `scopemap analyze --repo . --diff main --format html`.
```

---

## 2. Command Cheat Sheet for Agents

| Task | Command |
|---|---|
| **Impact Summary** | `scopemap analyze --repo . --diff main` |
| **JSON Export** | `scopemap analyze --repo . --diff main --format json` |
| **Targeted Pytest Command** | `scopemap analyze --repo . --diff main --format pytest` |
| **Targeted Pytest File List** | `scopemap analyze --repo . --diff main --format pytest-args` |
| **Visual HTML Dashboard** | `scopemap analyze --repo . --diff main --format html --output report.html` |
| **Architecture Boundary Guard** | `scopemap guard --repo .` |
| **Interactive Terminal Tree** | `scopemap tree --repo . --file <filepath>` |

---

## 3. License & Compliance

- **License:** MIT License (100% Permissive, Commercial & Open Source Safe).
- **Dependencies:** Standard library Python only for core graph extraction. Optional extras available for TypeScript (`scopemap[ts]`), JavaScript (`scopemap[js]`), and Bokeh network visualization (`scopemap[bokeh]`).
