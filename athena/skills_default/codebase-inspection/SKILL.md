---
description: Survey an unfamiliar codebase quickly — size, shape, hotspots, conventions
name: codebase-inspection
created_at: '2026-05-27T00:00:00Z'
last_activity_at: '2026-05-27T00:00:00Z'
pinned: false
state: active
use_count: 0
write_origin: foreground
---
# Codebase Inspection

Disciplined approach to surveying an unfamiliar codebase. The
premise: most "I'll just start coding" attempts in unfamiliar
codebases produce changes that violate local conventions, miss
established patterns, and duplicate existing functionality. A
30-minute inspection upfront avoids days of rework.

## When to use this skill

Use when:
- You're new to a codebase and about to make a non-trivial change
- A coworker asks "can we add X?" and X might already exist
- Doing due diligence before adopting / forking a third-party repo
- Periodically auditing your OWN codebase to spot drift

Skip for codebases you know cold or trivial one-file fixes.

## The inspection pass

Block 30-60 minutes. Don't aim for total understanding — aim for a
working map.

### 1. Size and language mix

```bash
# pygount — counts LOC by language, ignores comments/blanks
pip install pygount
pygount --format=summary .

# or cloc (perl-based, common in Linux distros)
cloc .

# or scc (Rust, fast)
scc .
```

Note: total LOC, language breakdown, comment-to-code ratio. Big
codebase != bad; very small codebase + huge dependency tree is a
warning sign (the actual code might be just glue).

### 2. Layout

```bash
# Top-level layout
ls -la

# Two levels deep
find . -maxdepth 2 -type d -not -path '*/.*'
```

Look for:
- Source root: ``src/``, ``lib/``, ``<projectname>/``
- Tests root: ``tests/``, ``test/``, alongside source
- Docs root: ``docs/``, ``website/``
- Scripts / tooling: ``scripts/``, ``tools/``, ``bin/``
- Build artifacts: ``dist/``, ``build/``, ``.next/`` (don't read
  these — they're generated)

Read README.md if it exists. CONTRIBUTING.md too — that's where
conventions live.

### 3. Dependency map

```bash
# Python
cat requirements.txt    # or pyproject.toml, setup.py

# Node
cat package.json | jq '.dependencies, .devDependencies'

# Rust
cat Cargo.toml

# Go
cat go.mod
```

Count:
- Direct dependencies (small = simple stack; large = thick stack)
- Are dependencies up to date? (old versions = maintenance debt)
- Any obviously unmaintained deps? (e.g., abandoned upstream)

### 4. Entry points

Where does execution start?

- CLI: ``bin/<name>``, ``__main__.py``, ``main.go``,
  ``src/index.ts``
- Web service: ``server.js``, ``app.py``, ``main.go``
- Library: ``__init__.py``, ``index.ts``, ``lib.rs``

Read the entry point top-to-bottom. It usually tells you the
high-level shape: what subsystems exist, how they're wired
together.

### 5. The "explain it in 3 sentences" test

After 30 minutes, you should be able to write 3 sentences:

> "This codebase is a [type of system]. It's structured as
> [top-level shape: monolith, microservices, layered, etc.].
> The main subsystems are [A, B, C], and they talk via
> [pattern]."

If you can't write those sentences, you haven't surveyed enough.
Spend another 15 minutes.

### 6. Find the hotspots

Where does the action happen?

```bash
# Files changed most often in the last 90 days
git log --since="90 days ago" --pretty=format: --name-only \
  | sort | uniq -c | sort -rn | head -20

# Files with the most contributors
git log --since="365 days ago" --pretty=format: --name-only \
  | sort -u | while read f; do
    [[ -f "$f" ]] && echo "$(git log --pretty=format:'%an' "$f" \
      | sort -u | wc -l) $f"
  done | sort -rn | head -20

# Largest files (often signals where complexity lives)
find . -name '*.py' -not -path './*venv*/*' \
  -exec wc -l {} + | sort -rn | head -20
```

The hotspot files are where:
- Most of the bugs live
- Most of the conventions are established (read them to learn the
  style)
- Most of the merge conflicts will be (plan around)

### 7. Convention check

Read 2-3 hotspot files and note:

- **Naming**: camelCase / snake_case / kebab-case for what?
- **Module structure**: classes-heavy or functions-heavy?
- **Error handling**: exceptions / Result types / nullable
  returns?
- **Logging**: print / structured / framework-specific?
- **Tests**: where, how named, what style?
- **Comments**: minimal / prose-heavy / docstrings?

A change that violates these conventions stands out in review.
Match the local style.

## Tools by language

### Python

- ``pygount`` / ``cloc`` — LOC
- ``pydeps`` — dependency graph
- ``vulture`` — dead code detection
- ``ruff`` — show project's linter config (.ruff.toml)

### JavaScript / TypeScript

- ``cloc`` — LOC
- ``madge`` — circular dependency detection
- ``ts-prune`` — unused exports
- ``depcheck`` — unused dependencies

### Go

- ``go doc`` — package documentation
- ``go vet`` — static analysis
- ``cloc``

### Rust

- ``cargo tree`` — dependency tree
- ``cargo bloat`` — what's taking space
- ``cargo expand`` — see post-macro expansion

## Adapting to a new project

After the inspection, write a personal cheat-sheet:

```
PROJECT: athena
LANGUAGE: Python (3.11) + TypeScript (Ink TUI)
TOPLEVEL: athena/ (source), ui-tui/ (Ink), tests/, docs/, ...
ENTRY: athena/__main__.py
HOTSPOTS: agent/core.py, tools/file_ops.py
CONVENTIONS:
  - Python: snake_case, dataclasses, ruff-clean
  - Tests: pytest, tmp_path fixtures, no real network
  - Logging: ui.console.print (gateway-gated) + structured json
  - Errors: domain exceptions, not raw HTTPError
NOTABLES:
  - Two-process model: gateway daemon + agent
  - MCP servers in mcpServers config
  - Skills in ~/.athena/skills/
```

Now you can navigate efficiently. Future you (and any subagent
you delegate to per [[subagent-driven-development]]) needs this.

## Anti-patterns

- **Reading every file**: doesn't scale; loses you the forest for
  the trees. Inspection is about MAP, not full read.
- **Skipping README / CONTRIBUTING**: the authors literally wrote
  down what they want you to know. Read it.
- **Treating LOC as quality**: a 100k-LOC codebase isn't worse
  than a 10k one. Different scale, different patterns. Don't
  conflate size with anything.
- **Ignoring conventions you don't like**: matching the local
  style is more important than your preferred style. Open an ADR
  ([[decision-record]]) if you want to change a convention.
- **Inspection paralysis**: 4 hours of "understanding" and 0
  hours of changing things. Cap the inspection — 30-60 min — and
  start changing once the map is good enough.
