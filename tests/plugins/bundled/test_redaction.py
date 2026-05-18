"""Span attribute redaction — secret patterns + truncation."""
from __future__ import annotations

from athena.plugins.bundled.observability.redaction import (
    MAX_LEN,
    REDACTED,
    redact_args,
    redact_string,
    redact_value,
)


# ---- secret patterns -----------------------------------------------


def test_openai_key_redacted() -> None:
    out = redact_string("--key sk-abcdef0123456789ABCDEF01234567890123")
    assert "sk-" not in out
    assert REDACTED in out


def test_openai_proj_key_redacted() -> None:
    """sk-proj-... is one of OpenAI's newer prefixes; the regex
    covers any sk-<urlsafe> form."""
    out = redact_string("API key: sk-proj-rocketship1234567890abcdef")
    assert REDACTED in out


def test_anthropic_key_redacted() -> None:
    out = redact_string("Authorization: sk-ant-api03-abcDEF1234567890qwerTYUIOPasdFGHjkl")
    assert "sk-ant-" not in out
    assert REDACTED in out


def test_google_key_redacted() -> None:
    out = redact_string("?key=AIzaSyDexample1234567890abcdefghijklmnop")
    assert "AIza" not in out
    assert REDACTED in out


def test_github_pat_classic_redacted() -> None:
    out = redact_string("git clone https://ghp_abcdef0123456789ABCDEF01234567890123@github.com")
    assert "ghp_" not in out
    assert REDACTED in out


def test_github_pat_fine_grained_redacted() -> None:
    """ghu_ / ghs_ / ghr_ / gho_ all share the same shape."""
    for prefix in ("ghu", "ghs", "ghr", "gho"):
        out = redact_string(f"token {prefix}_abcdef0123456789ABCDEF01234567890123")
        assert prefix + "_" not in out


def test_bearer_token_redacted() -> None:
    out = redact_string('"Authorization: Bearer my-super-secret-token-value=="')
    assert "my-super-secret" not in out
    assert REDACTED in out


def test_bearer_case_insensitive() -> None:
    out = redact_string("bearer abcdefghijk")
    assert "abcdefghijk" not in out


def test_slack_token_redacted() -> None:
    out = redact_string("Slack: xoxb-1234567890-abcdefghij")
    assert "xoxb-" not in out


def test_non_secret_passes_through() -> None:
    """A normal string with no matching pattern stays unchanged."""
    plain = "git status"
    assert redact_string(plain) == plain


def test_partial_prefix_not_matched() -> None:
    """A bare 'sk-' or 'sk-abc' (under length minimum) doesn't trip
    the pattern — keeps regex false-positive rate low."""
    # The OpenAI pattern requires 20+ chars after sk-.
    short = "sk-short"
    assert redact_string(short) == short


# ---- truncation ---------------------------------------------------


def test_long_string_truncated() -> None:
    long = "x" * (MAX_LEN + 100)
    out = redact_string(long)
    assert len(out) == MAX_LEN + 1  # +1 for the ellipsis
    assert out.endswith("…")


def test_string_at_limit_not_truncated() -> None:
    """MAX_LEN exactly fits; no ellipsis."""
    s = "x" * MAX_LEN
    assert redact_string(s) == s


def test_truncation_after_redaction() -> None:
    """A long string containing a secret gets redacted FIRST, then
    measured — so the truncation length is on the post-redaction
    string."""
    body = "prefix " + ("y" * 300) + " sk-abcdef0123456789ABCDEF01234567890123"
    out = redact_string(body)
    # Secret is gone…
    assert "sk-" not in out
    # …and the truncation kicked in.
    assert "…" in out


# ---- redact_value -------------------------------------------------


def test_redact_value_passes_scalars() -> None:
    assert redact_value(42) == 42
    assert redact_value(3.14) == 3.14
    assert redact_value(True) is True
    assert redact_value(False) is False


def test_redact_value_none_becomes_empty_string() -> None:
    assert redact_value(None) == ""


def test_redact_value_redacts_strings() -> None:
    assert redact_value("sk-abcdef0123456789ABCDEF01234567890123") == REDACTED


def test_redact_value_repr_unknown_types() -> None:
    """Non-scalar non-string values get repr()'d and treated as strings."""
    out = redact_value([1, 2, 3])
    assert isinstance(out, str)
    # The repr "[1, 2, 3]" passes through clean (no secret pattern).
    assert out == "[1, 2, 3]"


def test_redact_value_inside_complex_repr() -> None:
    """A dict containing a credential gets redacted via repr."""
    payload = {"token": "ghp_abcdef0123456789ABCDEF01234567890123"}
    out = redact_value(payload)
    assert "ghp_" not in out
    assert REDACTED in out


# ---- redact_args --------------------------------------------------


def test_redact_args_keys_under_namespace() -> None:
    out = redact_args({"path": "/etc/hosts", "limit": 10})
    assert out == {
        "athena.tool_arg.path": "/etc/hosts",
        "athena.tool_arg.limit": 10,
    }


def test_redact_args_redacts_values() -> None:
    out = redact_args({"cmd": "curl -H 'Authorization: Bearer secrettoken123' x"})
    val = out["athena.tool_arg.cmd"]
    assert "secrettoken123" not in val
    assert REDACTED in val


def test_redact_args_handles_none() -> None:
    assert redact_args(None) == {}


def test_redact_args_handles_non_dict() -> None:
    """Defensive: a tool wrapper that passes a list instead of dict
    shouldn't crash the span construction."""
    assert redact_args(["a", "b"]) == {}  # type: ignore[arg-type]


def test_redact_args_empty_dict() -> None:
    assert redact_args({}) == {}
