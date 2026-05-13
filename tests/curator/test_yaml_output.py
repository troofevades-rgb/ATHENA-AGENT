"""Tests for ocode.curator.yaml_output.parse_curator_report."""
from __future__ import annotations

import logging

from ocode.curator.yaml_output import parse_curator_report


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
    with caplog.at_level(logging.WARNING, logger="ocode.curator.yaml_output"):
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
