"""Drift-guard: the README quickstart section references the
operator-facing surfaces this audit pass shipped.

Adds the audit's P3 "quickstart" finding as a regression pin so a
future README edit can't accidentally drop the dogfood wisdom (run
``athena doctor`` first; ``~/.athena/crashes/`` for bug reports;
hosted-model picker + no-tools marker; the OpenRouter prefix
gotcha).

These pins are intentionally LOOSE substring checks -- the doc can
be rephrased freely as long as the load-bearing operator entry
points stay referenced.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).parent.parent
_README = _REPO_ROOT / "README.md"


@pytest.fixture(scope="module")
def readme_text() -> str:
    """Read the README once for the whole module -- the file
    rarely changes across tests."""
    return _README.read_text(encoding="utf-8")


def test_quickstart_section_exists(readme_text: str) -> None:
    """The audit's P3 ask was a quickstart (install -> first prompt
    -> first tool use). Header presence is the load-bearing check;
    the body can be rephrased."""
    assert "## Quickstart" in readme_text


def test_quickstart_references_athena_doctor(readme_text: str) -> None:
    """The dogfood pattern this audit pass produced: ``athena
    doctor`` is the canonical "is anything broken" probe. The
    quickstart MUST reference it so new operators don't repeat the
    "is my key set? is Ollama running?" trial-and-error sequence."""
    assert "athena doctor" in readme_text


def test_quickstart_references_crash_log_for_bug_reports(
    readme_text: str,
) -> None:
    """When athena crashes, a JSON record lands at
    ``~/.athena/crashes/`` (secrets scrubbed). Operators need to
    know that file exists and what to attach to a bug report."""
    assert "~/.athena/crashes/" in readme_text


def test_quickstart_covers_hosted_providers(readme_text: str) -> None:
    """The original README assumed Ollama-only. Hosted providers
    are a major operator surface (this whole audit session was
    driven by OpenRouter / Anthropic dogfood). The quickstart
    must walk through adding a hosted key + switching to a hosted
    model via the picker."""
    assert "providers add-key" in readme_text
    assert "/model" in readme_text


def test_quickstart_warns_about_no_tools_openrouter_models(
    readme_text: str,
) -> None:
    """A real dogfood trap this audit caught: picking
    ``nousresearch/hermes-4-70b`` from the OpenRouter catalog 404s
    on every prompt because the model doesn't list ``tools`` in
    its supported_parameters. The picker marks those entries
    ``[no-tools]``. The quickstart MUST mention this so operators
    learn what the marker means before they hit the wall."""
    assert "no-tools" in readme_text


def test_quickstart_links_doctor_json_for_bug_reports(
    readme_text: str,
) -> None:
    """``athena doctor --json`` is the right thing to paste into
    a bug report -- machine-readable, captures the operator's full
    runtime state in one blob."""
    assert "athena doctor --json" in readme_text
