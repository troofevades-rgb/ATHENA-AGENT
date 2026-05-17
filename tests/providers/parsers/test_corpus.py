"""Fixture-corpus driven parser tests.

Walks ``tests/fixtures/tool_call_outputs/<provider>/<model>/<category>/``
and asserts that ``resolve_parser(provider, model)`` produces the
expected output for each sample.

Each fixture is a triple:

- ``<slug>.txt`` — raw assistant content (the parser's first argument).
- ``<slug>.raw.json`` — optional. Full raw_response dict (the second
  argument). Defaults to ``{}`` if absent. Native-format parsers
  (anthropic_xml, openai_tools) need this; content-leak parsers can
  usually skip it.
- ``<slug>.expected.json`` — required. Sidecar with
  ``{"cleaned_content": str, "tool_calls": [{name, arguments, id}, ...]}``.

Real samples can be dropped in over time; the corpus structure is the
same. The model directory name must match what the provider reports for
that model (e.g. ``claude-sonnet-4-6``, ``qwen2.5-coder-14b``).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from athena.providers.parsers import resolve_parser


_CORPUS_ROOT = (
    Path(__file__).resolve().parents[2]
    / "fixtures" / "tool_call_outputs"
)


def _walk_fixtures() -> list[Path]:
    """Return every .expected.json under the corpus."""
    if not _CORPUS_ROOT.is_dir():
        return []
    return sorted(_CORPUS_ROOT.rglob("*.expected.json"))


def _fixture_id(path: Path) -> str:
    """Build a human-readable test id from the fixture path."""
    rel = path.relative_to(_CORPUS_ROOT).with_suffix("").with_suffix("")
    return "__".join(rel.parts)


@pytest.mark.parametrize(
    "expected_path",
    _walk_fixtures(),
    ids=[_fixture_id(p) for p in _walk_fixtures()],
)
def test_corpus_fixture(expected_path: Path) -> None:
    base = expected_path.with_suffix("").with_suffix("")  # strip .expected.json
    rel = expected_path.relative_to(_CORPUS_ROOT)
    # rel = <provider>/<model>/<category>/<slug>.expected.json
    provider = rel.parts[0]
    model = rel.parts[1]

    # Content: <slug>.txt (may be missing/empty for native-format fixtures).
    content_path = base.with_suffix(".txt")
    content = content_path.read_text(encoding="utf-8") if content_path.exists() else ""
    # Strip the single trailing newline most editors add. Tests that need
    # to assert on trailing whitespace can use a different fixture shape.
    if content.endswith("\n"):
        content = content[:-1]

    # raw_response: <slug>.raw.json (optional).
    raw_path = base.with_suffix(".raw.json")
    raw: dict = (
        json.loads(raw_path.read_text(encoding="utf-8"))
        if raw_path.exists() else {}
    )

    expected = json.loads(expected_path.read_text(encoding="utf-8"))

    parser = resolve_parser(provider, model)
    cleaned, tool_calls = parser(content, raw)

    assert cleaned == expected["cleaned_content"], (
        f"cleaned_content mismatch for {rel}\n"
        f"  expected: {expected['cleaned_content']!r}\n"
        f"  got:      {cleaned!r}"
    )
    assert tool_calls == expected["tool_calls"], (
        f"tool_calls mismatch for {rel}\n"
        f"  expected: {expected['tool_calls']!r}\n"
        f"  got:      {tool_calls!r}"
    )


def test_corpus_root_is_present():
    """A degenerate test that exists to make sure the corpus isn't
    accidentally empty. If _walk_fixtures returns nothing,
    parametrize collected zero tests and we'd ship a green run for
    free."""
    fixtures = _walk_fixtures()
    assert fixtures, (
        f"no fixtures found under {_CORPUS_ROOT}. Phase 9 ships with "
        "synthetic seeds; if you removed them, restore some."
    )
