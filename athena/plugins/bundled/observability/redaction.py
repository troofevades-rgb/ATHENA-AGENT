"""Redact secrets and truncate long strings before they reach spans.

Two layers of defense:

1. **Pattern-based scrubbing** for common credential shapes that
   slip into tool arguments (API keys in env vars,
   ``Authorization`` headers in HTTP tool calls, GitHub PATs in
   ``Bash`` invocations).
2. **Length truncation** so a tool that reads a 100 KB file
   doesn't produce a 100 KB span attribute (OTLP exporters
   complain, and large attributes blow up trace UIs).

The patterns are matched literally — we don't try to detect
"things that look secret-y" beyond known shapes. A new credential
format added by some provider next year won't auto-redact; users
should set custom patterns via plugin config when they need them.

Keys preserved in the output dict so the trace UI shows what
arguments existed; values get redacted/truncated as needed.
"""
from __future__ import annotations

import re
from typing import Any


REDACTED = "<redacted>"
MAX_LEN = 200


# Pattern → match-group-replace shape. Each pattern matches the
# secret in-line so we can replace just the credential while
# preserving the rest of the string ("--token sk-..." → "--token <redacted>").
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    # OpenAI / OpenAI-compat (sk-..., sk-proj-..., sk-org-...). At
    # least 20 url-safe chars after the prefix so we don't match
    # random "sk-..." inside conversational text.
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    # Anthropic. Distinct shape from OpenAI; explicit so a leak in
    # a config file gets caught.
    re.compile(r"sk-ant-[A-Za-z0-9_-]{30,}"),
    # Google Cloud / Maps / etc.
    re.compile(r"AIza[A-Za-z0-9_-]{30,}"),
    # GitHub Personal Access Tokens (classic + fine-grained).
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    # Generic Bearer tokens in headers. Catches "Authorization:
    # Bearer <token>" plus loose "Bearer <token>" anywhere.
    re.compile(r"[Bb]earer\s+[A-Za-z0-9._~+/=-]+"),
    # Slack tokens (bot + app + user; all share the xoxp/xoxb/xoxa
    # prefix structure).
    re.compile(r"xox[abprs]-[A-Za-z0-9-]{10,}"),
)


def redact_string(text: str) -> str:
    """Apply every secret pattern then truncate to :data:`MAX_LEN`.

    Returns ``text`` unchanged when nothing matches and length is
    inside the budget. Truncation appends ``"…"`` so the trace UI
    shows the value was cut, not just short.
    """
    if not text:
        return text
    out = text
    for pat in _SECRET_PATTERNS:
        out = pat.sub(REDACTED, out)
    if len(out) > MAX_LEN:
        out = out[:MAX_LEN] + "…"
    return out


def redact_value(value: Any) -> Any:
    """Per-value redaction for span attribute construction.

    Scalars (int / float / bool) pass through — there's no useful
    secret hiding in ``True``. Strings get scrubbed + truncated.
    Anything else gets ``repr()``'d and treated as a string; this
    catches list / dict / object payloads that shouldn't flow into
    a span as-is anyway (OTel attribute types are restricted).
    """
    if isinstance(value, (bool, int, float)):
        return value
    if value is None:
        return ""
    if isinstance(value, str):
        return redact_string(value)
    return redact_string(repr(value))


def redact_args(args: dict[str, Any] | None) -> dict[str, Any]:
    """Apply :func:`redact_value` to every entry in ``args``,
    re-keyed under the ``athena.tool_arg.`` namespace so span UIs
    can group them.

    ``None`` / non-dict inputs return an empty dict — tool wrappers
    sometimes pass missing args as ``None`` and we don't want to
    surface a TypeError into the agent loop just because a span
    attribute construction blew up.
    """
    if not args or not isinstance(args, dict):
        return {}
    out: dict[str, Any] = {}
    for key, value in args.items():
        out[f"athena.tool_arg.{key}"] = redact_value(value)
    return out
