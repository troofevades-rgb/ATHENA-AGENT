# `hermes_skill_examples/` — Hermes-format SKILL.md samples

Anonymized SKILL.md files in the Hermes Agent format, used by Phase 1
tests to verify that ocode's skill loader and the `ocode import-from-hermes`
tool handle the full surface area of real-world skills: normal cases,
edge cases (long descriptions, multi-section bodies, unicode), and
malformed frontmatter (missing fields, invalid YAML, conflicting keys).

## Layout

```
hermes_skill_examples/
├── normal/         # Well-formed skills representative of typical use
├── edge_cases/     # Valid but unusual: long fields, unicode, deep nesting
└── malformed/      # Invalid frontmatter; tests assert specific error modes
```

Each sample is one SKILL.md file. Multi-file skills (with attached
`resources/`, scripts, etc.) are stored as a directory containing
SKILL.md plus the accompanying assets, mirroring the on-disk layout
Hermes expects.

## Naming

`<descriptive-slug>.md` for single-file samples; `<slug>/` directory
for skills with attached assets. Slugs are kebab-case and describe
what the sample exercises, not what the skill does:
`missing-description-field.md`, `unicode-in-name.md`, not
`my-cool-tool.md`.

## Adding a new sample

1. Anonymize (see provenance rules below).
2. Place in the appropriate subdirectory (`normal/`, `edge_cases/`, or
   `malformed/`).
3. Append a one-line note to this README under "Inventory" describing
   what the sample exercises.
4. Update the relevant test in `tests/migration/` or `tests/skills/`
   to assert against it.

## Provenance

Samples may come from:

- The user's own `~/.hermes/skills/` (preferred for realistic coverage)
- Anonymized snippets pulled from public Hermes documentation or example
  repositories
- Synthetic skills hand-written to exercise specific code paths

**Anonymization rules** (apply before committing):

- Replace any path under `/Users/`, `/home/`, or `C:\Users\` with
  `/path/to/`
- Replace personal names, emails, and identifiers with `example`,
  `user`, `team-name`
- Strip API keys, OAuth tokens, webhook URLs entirely (replace with
  `<REDACTED>` and note in the description that the sample exists to
  test redaction)
- Replace real organization/repository names with `acme-corp/example-repo`

## Inventory

_To be filled in as samples are added._
