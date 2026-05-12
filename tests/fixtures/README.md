# Test fixture corpora

This directory holds real-world and synthetic test data referenced by
ocode's test suite. Every subdirectory is a *corpus*: a named collection
of samples with a consistent format, used by one or more test modules.

Each corpus subdirectory has its own `README.md` documenting its purpose,
layout, naming convention, how to add new samples, and provenance rules.
**Read the subdirectory README before adding to any corpus** — the
provenance and anonymization rules are corpus-specific.

## Current corpora

| Corpus | Used by | Status |
|--------|---------|--------|
| [`hermes_skill_examples/`](hermes_skill_examples/README.md) | Phase 1 skill format tests | scaffolded; samples land with Phase 1 |
| [`hermes_memory_db_sample/`](hermes_memory_db_sample/README.md) | Phase 1 migration tests | scaffolded; samples land with Phase 1 |
| [`sessions_v1/`](sessions_v1/README.md) | Phase 2 session-store + Phase 1 migration | scaffolded; samples land when needed |
| [`tool_call_outputs/`](tool_call_outputs/README.md) | Phase 9 parser tests | scaffolded; samples accumulate across Phase 8 + 9 |

## Adding a new corpus

If a phase needs a kind of test data that doesn't fit any existing corpus,
create a new subdirectory here with its own README following the format
described in `CONVENTIONS.md` § "Test-fixture corpora". Add a row to the
table above in the same commit.

## Hard rules

- **No real credentials, tokens, or personally-identifying information**
  anywhere under this tree, ever. If a sample comes from a real source,
  anonymize per that corpus's rules before committing.
- **Samples are inputs, not source code.** They live here, not in `ocode/`.
- **Each sample is a contract.** Changing a sample changes the assertion
  it was checking; do it deliberately and document the reason in the
  commit message.
