---
name: git-commit-style
description: Write commit messages using a Conventional-Commits-style prefix (feat, fix, refactor, docs, test) plus a one-paragraph body explaining WHY the change was needed, not WHAT changed. Body lines should be wrapped at 72 characters.
write_origin: foreground
---

# Commit message convention

Athena follows a hybrid of Conventional Commits and the long-form
body style popularized by the Linux kernel.

## Subject line

Pattern: `<type>(<scope>): <imperative short description>`

Types:

- `feat` — a wholly new capability the user can invoke
- `fix` — a bug fix; reference the symptom that surfaced it
- `refactor` — restructure without behavior change
- `docs` — anything in `docs/`, READMEs, or inline docstrings only
- `test` — adding/strengthening tests for existing behavior
- `chore` — build, deps, CI, formatting

## Body

Always write a body. Bodies explain WHY, not WHAT. The reader can
read the diff for what; they can't read the codebase author's head
for why. Anchor every commit to the motivating problem.

Wrap lines at 72 characters.

## Examples

```
feat(safety): content-addressed snapshot store (Phase 17.1)

Every agent-driven mutation now snapshots its pre-state before
the edit lands, so any change is byte-exact rollback-able and
forensically attributable. Tarball naming includes a sha[:12] so
identical pre-states under the same write_origin at the same
second collapse to one artifact on disk.
```
