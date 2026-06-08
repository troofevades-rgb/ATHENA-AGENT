---
description: Branch → commit → PR → review → merge lifecycle on GitHub
name: github-pr-workflow
created_at: '2026-05-27T00:00:00Z'
last_activity_at: '2026-05-27T00:00:00Z'
pinned: false
state: active
use_count: 0
write_origin: foreground
---
# GitHub PR Workflow

Disciplined GitHub PR lifecycle, from branch creation to merge.
The premise: most PR pain comes from skipping steps — pushing
without context, opening a PR without a description, asking for
review before CI passes. Discipline eliminates the avoidable
friction.

## When to use this skill

Use when contributing to a GitHub repo via PRs. Skip for solo
repos with no review (just push to main), and for one-line
hot-fixes that need to merge faster than the workflow allows.

Pairs with [[git-commit-style]] (commit message format) and
[[requesting-code-review]] (pre-submit gates).

## The lifecycle

### 1. Pick or create the issue

For non-trivial work, an issue should exist before the PR:

- Defines the problem in shared terms
- Captures discussion before code is written
- Gives the PR a place to link from / to

```bash
gh issue list --assignee @me
gh issue create --title "..." --body "..."
```

If the work is trivial and self-evident (typo, broken link, small
bug), skip the issue. Otherwise: issue first.

### 2. Branch

Branch off main with a descriptive name:

```bash
git checkout main
git pull --ff-only
git checkout -b <type>/<short-description>
```

Where ``<type>`` is one of:
- ``feat`` — new functionality
- ``fix`` — bug fix
- ``refactor`` — restructure without behavior change
- ``docs`` — documentation only
- ``test`` — test changes only
- ``chore`` — tooling, CI, build, deps

Example: ``feat/owl-banner-rendering``,
``fix/confirm-reply-routing``.

### 3. Commit as you go

Small commits, each meaningful. Follow [[git-commit-style]]:

```
<type>: <short summary in imperative mood>

<one-paragraph body explaining WHY this commit exists, not WHAT
it does — the diff shows what>
```

DON'T:
- Squash 20 unrelated changes into one commit
- Push commits with messages like "wip", "fix", "..."
- Force-push to a shared branch (only force-push to your own
  feature branch when nobody else is collaborating on it)

### 4. Self-review before push

Before ``git push``:

```bash
git diff main...HEAD              # full diff vs main
git log main..HEAD --oneline       # commit list
```

See [[requesting-code-review]] for the full seven-gate
pre-submit checklist.

### 5. Push and open PR

```bash
git push -u origin HEAD
gh pr create --title "..." --body "$(cat <<'EOF'
## Summary
...

## Why
Fixes #123 (or "addresses the user-reported issue ...").

## How
...

## Testing
...
EOF
)"
```

PR title: short (<70 chars), descriptive, matches commit-style
prefix (``feat: add owl banner``).

PR body: see [[requesting-code-review]] for the full template.

### 6. Wait for CI; don't skip

CI exists to catch what you missed. If it's red:

- Read the failure carefully
- Reproduce locally
- Fix and push a new commit (don't amend if reviewers have
  already seen the branch)

If CI is FLAKY (unrelated test failures):

- Re-run that one job once
- If it fails twice, treat as a real failure and investigate
- Don't merge with red CI just because "it's probably flake"

### 7. Request review

When CI is green AND self-review is done:

- Mark PR ready (if it was draft)
- Assign reviewers
- Add labels (``needs-review``, ``priority: high``, etc.)

Tag intentionally — see [[requesting-code-review]].

### 8. Respond to feedback

Every reviewer comment gets a response — either "fixed in <sha>"
or "discussed: keeping because <reason>." Resolve threads as you
address them.

When you push changes after review feedback:
- Use new commits (not amend), so reviewers can see what
  changed since their pass
- Don't force-push until ready to merge — reviewers' "view
  changes since I last reviewed" link breaks on force-push

### 9. Merge

When approved + CI green:

- **Squash and merge**: collapses your N commits into one. Good
  for small PRs where the individual commits are sloppy WIP.
- **Rebase and merge**: keeps your individual commits. Good when
  each commit is a meaningful, well-described step (per
  [[refactor-safely]]).
- **Merge commit**: preserves the branch history. Default in some
  repos; rarely the best choice unless your team values it.

Follow your repo's convention. Check ``CONTRIBUTING.md`` or ask.

### 10. Clean up

```bash
git checkout main
git pull --ff-only
git branch -d <feature-branch>
git push origin --delete <feature-branch>
```

(Or let GitHub auto-delete the branch on merge if that's
configured.)

If the PR closes an issue, GitHub does that automatically when you
use ``Fixes #123`` syntax in the body.

## Special situations

### Hotfixes

Production is on fire. The normal flow is too slow.

- Branch off main (or a release branch)
- Make the SMALLEST possible fix
- PR with a clear "hotfix" tag and a brief explanation
- Tag reviewer with explicit urgency in the PR title:
  ``hotfix(urgent): patch SSRF in /download``
- Merge as soon as one approval + CI green; ship
- File a follow-up issue for the proper fix if the hotfix was
  duct-tape

### Stacked PRs

When you need to ship a sequence of dependent changes:

- PR #1 targets ``main``
- PR #2 targets ``feature-1-branch``
- PR #3 targets ``feature-2-branch``

Each PR is independently reviewable. Merge in order; the later
PRs auto-rebase as the earlier ones merge.

GitHub doesn't have first-class stacked-PR support, but tools
like ``ghstack`` or ``Graphite`` help.

### Draft PRs

Open as draft when you want early feedback on direction but
aren't ready for a full review:

```bash
gh pr create --draft --title "..." --body "..."
```

Add a "WIP: looking for direction feedback on X" note. Convert
to ready when the implementation is complete.

## Anti-patterns

- **PRs of 1000+ lines**: nobody can review them properly.
  Split.
- **PRs with no description**: forces reviewers to read code AND
  context simultaneously.
- **Merging your own PR without review**: if your project requires
  review, get review. If you genuinely have no reviewers,
  document why and merge.
- **Reopening rejected PRs**: if your PR was rejected with
  feedback, address the feedback and open a NEW PR with
  references to the old one. Don't reopen and continue
  arguing.
- **Force-pushing during review**: breaks reviewer "view changes
  since I last saw it" links.
