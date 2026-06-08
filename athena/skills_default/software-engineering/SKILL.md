---
description: General-purpose software engineering guidance for writing, refactoring,
  debugging, and reviewing code
name: software-engineering
created_at: '2026-05-24T02:17:37Z'
last_activity_at: '2026-05-24T02:17:37Z'
pinned: false
state: active
use_count: 0
write_origin: foreground
---
# Software Engineering

General-purpose software engineering guidance for athena when writing,
refactoring, debugging, or reviewing code.

## When to use this skill

Use when the user asks you to:
- Write new code in any language
- Refactor existing code for clarity or performance
- Debug an issue or error
- Review code for quality, security, or best practices
- Explain how a codebase works

## Core principles

### Code quality

1. **Readability first**: Clear names, small functions, minimal nesting.
   A future reader should understand your intent without guessing.

2. **Minimal is enough**: Don't add abstractions until you have
   evidence they're needed. Three similar lines is better than a
   premature abstraction.

3. **Fail fast**: Validate early, return on errors, avoid deep nesting.
   Use guards (`if not x: return`) instead of `if x: ... else: ...`.

4. **No magic**: Avoid hidden behavior, dynamic tricks, or confusing
   one-liners. Make data flow and control flow explicit.

### Security

1. **Sanitize inputs**: Never trust user input. Validate at every
   boundary (API, CLI, file, DB).

2. **Least privilege**: Run with minimal permissions. Don't use root
   unless required. Don't load secrets into memory longer than needed.

3. **Safe defaults**: Default-deny. If unsure, assume hostile input.

4. **No secrets in code**: Use credential managers, env vars, or
   secure vaults. Never commit `.env` files or API keys.

### Testing

1. **Test the behavior, not the implementation**: Tests should describe
   what the code does, not how it does it.

2. **Fast and isolated**: Unit tests should run quickly and not depend
   on external systems (DB, network, filesystem) unless explicitly
   testing integration.

3. **Deterministic**: No randomness, no time-based logic in tests.
   Use mocks or fixtures for external dependencies.

## Workflow

### For new features

1. **Understand the context**: Read existing code, tests, and docs.
   Identify the module's responsibilities and conventions.

2. **Start small**: Implement the minimal change that works.
   Prefer incremental commits over a single large diff.

3. **Add tests**: Write tests that fail before the feature works.
   Run the test suite to confirm.

4. **Review yourself**: Check for typos, unused imports, dead code,
   and obvious bugs. Run linters and type checkers.

### For debugging

1. **Reproduce**: Confirm the bug is reproducible. Note the exact
   steps, inputs, and environment.

2. **Isolate**: Create a minimal test case. Remove unrelated code.
   Narrow the search space.

3. **Hypothesize**: Form a hypothesis about the root cause. Design
   a test to confirm or refute it.

4. **Fix and verify**: Apply the minimal fix. Run existing tests.
   Add a regression test if possible.

### For code review

1. **Understand the intent**: Read the commit message, PR description,
   and conversation. What was the author trying to do?

2. **Check the contract**: Does the code match the expected behavior?
   Are inputs/outputs documented and validated?

3. **Look for patterns**: Repeated logic, similar bugs, or missed
   opportunities for abstraction.

4. **Be specific**: Cite line numbers. Explain the problem and suggest
   a fix. Reference relevant docs or standards.

## Pitfalls

- **Premature optimization**: Don't optimize for performance until you
  have a measured bottleneck. Profile first.

- **Over-engineering**: Don't add features or abstractions that solve
  problems you don't have yet.

- **Ignoring tests**: Don't skip tests to "save time." Untested code
  is technical debt.

- **Assuming correctness**: Don't assume external APIs, libraries, or
  dependencies behave as documented. Verify.

- **Neglecting docs**: Don't leave code undocumented. A good name
  explains what; a short comment explains why.

## Output format

When explaining code or giving guidance, use this structure:

```
## What I found

Brief summary of the issue, feature, or code behavior.

## Analysis

Detailed breakdown of root cause, constraints, or tradeoffs.

## Recommendation

Concrete steps to take. Include code snippets if helpful.

## Verification

How to confirm the fix or feature works.
```

For code changes, prefer `Edit` over `Write` when modifying existing
files. Include enough context in `old_string` to avoid partial matches.

## Integration with athena tools

- Use `Read` before editing. Never guess file contents.
- Use `Edit` for surgical changes. Use `Write` for new files or
  complete replacements.
- Use `Grep` to find symbols, callers, or patterns.
- Use `Glob` to locate files by name.
- Use `Bash` for tests, builds, git, or package managers.
- Use `Diagnose` for linting and type checking.

## Example

User: "Fix the bug in `user_service.py`."

Agent:
1. `Read(user_service.py)` to understand the code.
2. `Grep("user_service", pattern="def.*error")` to find related functions.
3. Run tests to reproduce the bug.
4. Identify the root cause and propose a fix.
5. `Edit(user_service.py, old_string="...", new_string="...")`.
6. Run tests to verify.
7. Report the fix with before/after context.
