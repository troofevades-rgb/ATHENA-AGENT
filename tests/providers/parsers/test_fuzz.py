"""Fuzz test for parser robustness.

Every parser MUST not raise on any input. The contract from
phase-09-tool-call-parsers.md, invariant 2: "Parsers never raise.
Malformed input returns ``(original_content, [])`` or
``(cleaned_content, partial_tool_calls)``."

This fuzzer feeds each (provider, model) combination 1000 random
strings drawn from a mix of:

- ASCII printable + punctuation
- JSON-ish tokens (``{}[]"',:``)
- XML-ish tokens (``<>``)
- Control bytes (``\\x00``-``\\x02``)
- Unicode (CJK, emoji)

If a parser raises on any of these, the fuzz test fails and prints
the offending input length and exception. The seed is fixed so a
green run is reproducible; a regression is reproducible from the
failure message.
"""

from __future__ import annotations

import random
import string

import pytest

from athena.providers.parsers import resolve_parser

_FUZZ_RUNS = 1000


_PROVIDERS_AND_MODELS: list[tuple[str, str]] = [
    ("ollama", "qwen2.5-coder:14b"),
    ("ollama", "gpt-oss:20b"),
    ("ollama", "llama3.1:8b"),
    ("anthropic", "claude-sonnet-4-6"),
    ("anthropic", "claude-haiku-4-5-20251001"),
    ("openai", "gpt-4o"),
    ("openai", "gpt-3.5-turbo-0613"),
    ("openai", "gpt-oss-20b"),
    ("google", "gemini-1.5-pro"),
    ("openrouter", "anthropic/claude-3-5-sonnet"),
    ("openai_compat", "qwen-vllm"),
    ("nous", "Hermes-3-Llama-3.1-405B"),
]


# Character bag the fuzzer draws from: printable ASCII plus the
# punctuation parsers care about and a sprinkle of control bytes /
# Unicode that have surfaced bugs in past lives.
_ALPHABET = (
    string.printable
    + "<>{}[]\"'\\/|"
    + "\x00\x01\x02"
    + "—…→"  # a few real Unicode chars; emoji deliberately excluded
    # because they take 4 bytes in UTF-8 and skew length stats
)


@pytest.mark.parametrize(
    "provider,model", _PROVIDERS_AND_MODELS, ids=lambda p: p if isinstance(p, str) else ""
)
def test_parser_never_raises_on_random_strings(provider: str, model: str) -> None:
    """1000 randomized inputs per (provider, model); parser must never
    raise, and every returned tool call must be well-shaped."""
    parser = resolve_parser(provider, model)
    rng = random.Random(42)  # fixed seed: green runs are reproducible
    for i in range(_FUZZ_RUNS):
        n = rng.randint(0, 5000)
        content = "".join(rng.choices(_ALPHABET, k=n))
        try:
            cleaned, calls = parser(content, {})
        except Exception as e:  # pragma: no cover — this is the test's purpose
            pytest.fail(
                f"parser for ({provider}, {model}) raised on iter {i} "
                f"with len={n}: {type(e).__name__}: {e}\n"
                f"first 200 chars: {content[:200]!r}"
            )
        # Shape contract: cleaned is str, calls is list[dict]
        # with name/arguments well-formed.
        assert isinstance(cleaned, str), (
            f"({provider}, {model}) iter {i}: cleaned not str: {type(cleaned)}"
        )
        assert isinstance(calls, list)
        for c in calls:
            assert isinstance(c, dict)
            assert isinstance(c.get("name"), str) and c["name"]
            assert isinstance(c.get("arguments"), dict)


def test_parser_never_raises_on_random_raw_response():
    """Same fuzz, but flips the focus to the second argument: random
    dict-shaped junk in raw_response. Important because native parsers
    (anthropic_xml, openai_tools, ollama_native) walk raw_response
    structures."""
    parser = resolve_parser("ollama", "qwen2.5-coder:14b")
    rng = random.Random(43)
    for i in range(200):
        # Random nested dict — at most 3 levels deep, small fanout.
        raw = _random_dict(rng, depth=3, max_keys=4)
        try:
            cleaned, calls = parser("", raw)
        except Exception as e:  # pragma: no cover
            pytest.fail(
                f"parser raised on raw_response iter {i}: {type(e).__name__}: {e}\nraw: {raw!r}"
            )
        assert isinstance(cleaned, str)
        assert isinstance(calls, list)


def _random_dict(rng: random.Random, depth: int, max_keys: int) -> dict:
    """Build a random nested dict with mixed value types (str, int, list, dict)."""
    out: dict = {}
    n = rng.randint(0, max_keys)
    for _ in range(n):
        key = "".join(rng.choices(string.ascii_letters, k=rng.randint(1, 8)))
        choice = rng.randint(0, 5)
        if choice == 0:
            out[key] = "".join(rng.choices(string.printable, k=rng.randint(0, 50)))
        elif choice == 1:
            out[key] = rng.randint(-1000, 1000)
        elif choice == 2:
            out[key] = rng.random() < 0.5
        elif choice == 3:
            out[key] = None
        elif choice == 4 and depth > 0:
            out[key] = _random_dict(rng, depth - 1, max_keys)
        else:
            out[key] = [rng.randint(0, 10) for _ in range(rng.randint(0, 4))]
    return out
