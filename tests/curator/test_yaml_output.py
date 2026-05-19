"""Tests for athena.curator.yaml_output.parse_curator_report."""

from __future__ import annotations

import logging

from athena.curator.yaml_output import parse_curator_report

_MINIMAL = """\
Some intro text.

```yaml-curator-report
runs:
  - skill: foo-bar
    decision: KEEP_AS_IS
    target: null
    rationale: still useful
```

Some trailing summary."""


_FULL = """\
```yaml-curator-report
runs:
  - skill: foo-old
    decision: CONSOLIDATE_INTO
    target: foo-umbrella
    rationale: redundant with foo-umbrella
  - skill: bar-misc
    decision: PRUNE
    target: null
    rationale: one-off
  - skill: new-umbrella
    decision: CREATE_UMBRELLA
    target: testing-patterns
    rationale: three siblings merged
```"""


def test_parses_minimal_report() -> None:
    parsed = parse_curator_report(_MINIMAL)
    assert parsed is not None
    assert len(parsed["runs"]) == 1
    assert parsed["runs"][0]["skill"] == "foo-bar"
    assert parsed["runs"][0]["decision"] == "KEEP_AS_IS"
    assert parsed["runs"][0]["target"] is None


def test_parses_full_report() -> None:
    parsed = parse_curator_report(_FULL)
    assert parsed is not None
    assert len(parsed["runs"]) == 3
    decisions = [r["decision"] for r in parsed["runs"]]
    assert decisions == ["CONSOLIDATE_INTO", "PRUNE", "CREATE_UMBRELLA"]


def test_rejects_missing_runs_key(caplog) -> None:
    text = "```yaml-curator-report\nother_key: 1\n```"
    with caplog.at_level(logging.WARNING, logger="athena.curator.yaml_output"):
        assert parse_curator_report(text) is None
    assert any("runs" in rec.message for rec in caplog.records)


def test_rejects_unknown_decision() -> None:
    text = """\
```yaml-curator-report
runs:
  - skill: x
    decision: BURN_IT_ALL
    target: null
    rationale: bad
```"""
    assert parse_curator_report(text) is None


def test_rejects_consolidate_without_target() -> None:
    text = """\
```yaml-curator-report
runs:
  - skill: x
    decision: CONSOLIDATE_INTO
    target: null
    rationale: where to?
```"""
    assert parse_curator_report(text) is None


def test_rejects_create_umbrella_without_target() -> None:
    text = """\
```yaml-curator-report
runs:
  - skill: x
    decision: CREATE_UMBRELLA
    target: ""
    rationale: needs a target
```"""
    assert parse_curator_report(text) is None


def test_handles_yaml_inside_code_fence() -> None:
    """Variant fence indentation and whitespace must not break parsing."""
    text = """\

```yaml-curator-report
runs:
  - skill: a
    decision: PRUNE
    target:
    rationale: stale
```
"""
    assert parse_curator_report(text) is not None


def test_rejects_empty_input() -> None:
    assert parse_curator_report("") is None
    assert parse_curator_report("just a paragraph, no yaml") is None


def test_accepts_bare_body_without_fence() -> None:
    """Defensive: if the model forgets the fence but emits a runs: block,
    we still accept it. Schema is the firm contract; the fence is convenience."""
    text = """\
runs:
  - skill: alpha
    decision: KEEP_AS_IS
    rationale: fine
"""
    parsed = parse_curator_report(text)
    assert parsed is not None
    assert parsed["runs"][0]["skill"] == "alpha"


def test_run_entry_missing_required_field_rejected() -> None:
    text = """\
```yaml-curator-report
runs:
  - skill: x
    decision: KEEP_AS_IS
```"""
    # missing 'rationale'
    assert parse_curator_report(text) is None


# ---- Retrofit #10: DEMOTE_TO_* decisions ------------------------------


def test_accepts_demote_to_references_with_target() -> None:
    text = """\
```yaml-curator-report
runs:
  - skill: pr-4421-fix
    decision: DEMOTE_TO_REFERENCES
    target: pr-triage-workflow
    rationale: session-specific repro notes
```"""
    parsed = parse_curator_report(text)
    assert parsed is not None
    assert parsed["runs"][0]["decision"] == "DEMOTE_TO_REFERENCES"
    assert parsed["runs"][0]["target"] == "pr-triage-workflow"


def test_accepts_demote_to_templates() -> None:
    text = """\
```yaml-curator-report
runs:
  - skill: cron-yaml-bootstrap
    decision: DEMOTE_TO_TEMPLATES
    target: cron-workflow
    rationale: starter file material
```"""
    parsed = parse_curator_report(text)
    assert parsed is not None and parsed["runs"][0]["decision"] == "DEMOTE_TO_TEMPLATES"


def test_accepts_demote_to_scripts() -> None:
    text = """\
```yaml-curator-report
runs:
  - skill: fixture-gen-snippet
    decision: DEMOTE_TO_SCRIPTS
    target: testing-patterns
    rationale: repeatable verification
```"""
    parsed = parse_curator_report(text)
    assert parsed is not None and parsed["runs"][0]["decision"] == "DEMOTE_TO_SCRIPTS"


def test_demote_decisions_require_target() -> None:
    for decision in (
        "DEMOTE_TO_REFERENCES",
        "DEMOTE_TO_TEMPLATES",
        "DEMOTE_TO_SCRIPTS",
    ):
        text = (
            "```yaml-curator-report\n"
            "runs:\n"
            "  - skill: x\n"
            f"    decision: {decision}\n"
            "    target: null\n"
            "    rationale: where?\n"
            "```"
        )
        assert parse_curator_report(text) is None, decision


# ---- Retrofit #6: absorbed_into propagation ---------------------------


def test_absorbed_into_defaults_to_target_for_consolidate() -> None:
    text = """\
```yaml-curator-report
runs:
  - skill: foo-narrow
    decision: CONSOLIDATE_INTO
    target: foo-umbrella
    rationale: redundant
```"""
    parsed = parse_curator_report(text)
    assert parsed is not None
    assert parsed["runs"][0]["absorbed_into"] == "foo-umbrella"


def test_absorbed_into_defaults_to_target_for_demote() -> None:
    text = """\
```yaml-curator-report
runs:
  - skill: foo-misc
    decision: DEMOTE_TO_REFERENCES
    target: foo-umbrella
    rationale: ref material
```"""
    parsed = parse_curator_report(text)
    assert parsed["runs"][0]["absorbed_into"] == "foo-umbrella"


def test_absorbed_into_null_for_create_umbrella() -> None:
    """CREATE_UMBRELLA's target is the new umbrella's NAME — that row
    IS the umbrella, not something being absorbed into another."""
    text = """\
```yaml-curator-report
runs:
  - skill: new-thing
    decision: CREATE_UMBRELLA
    target: testing-patterns
    rationale: 3 siblings will merge in
```"""
    parsed = parse_curator_report(text)
    assert parsed["runs"][0]["absorbed_into"] is None


def test_absorbed_into_null_for_keep_and_prune() -> None:
    text = """\
```yaml-curator-report
runs:
  - skill: a
    decision: KEEP_AS_IS
    target: null
    rationale: fine
  - skill: b
    decision: PRUNE
    target: null
    rationale: stale
```"""
    parsed = parse_curator_report(text)
    assert all(r["absorbed_into"] is None for r in parsed["runs"])


def test_explicit_absorbed_into_overrides_default() -> None:
    """If the model emits absorbed_into explicitly (different from
    target), respect the model's choice — useful for the rare case
    where the absorption target is named via a redirect."""
    text = """\
```yaml-curator-report
runs:
  - skill: x
    decision: CONSOLIDATE_INTO
    target: shim-umbrella
    absorbed_into: real-umbrella
    rationale: redirect
```"""
    parsed = parse_curator_report(text)
    assert parsed["runs"][0]["absorbed_into"] == "real-umbrella"
    assert parsed["runs"][0]["target"] == "shim-umbrella"


# ---- Backward compatibility: legacy 4-decision schema -----------------


def test_legacy_schema_without_absorbed_into_still_parses() -> None:
    """Reports written by athena pre-retrofit don't have absorbed_into
    in the YAML — the parser must fill it in or leave it None."""
    text = """\
```yaml-curator-report
runs:
  - skill: old
    decision: CONSOLIDATE_INTO
    target: umbrella
    rationale: legacy
```"""
    parsed = parse_curator_report(text)
    assert parsed["runs"][0]["absorbed_into"] == "umbrella"  # inferred
