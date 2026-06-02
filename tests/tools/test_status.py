"""ToolStatus taxonomy + status_payload helper, and that the videogen
tools emit valid members.

The type-safety (a typo'd status failing mypy) is enforced by mypy on
the typed call sites; these runtime tests pin the payload shape and
that the real videogen payloads carry valid statuses.
"""

from __future__ import annotations

import json

from athena.tools.status import status_payload


def test_status_payload_shape() -> None:
    d = json.loads(status_payload("not_enabled", reason="x"))
    assert d == {"status": "not_enabled", "reason": "x"}


def test_status_payload_minimal() -> None:
    assert json.loads(status_payload("done")) == {"status": "done"}


def test_videogen_payloads_use_valid_statuses() -> None:
    from athena.videogen.tools import _disabled_payload, _no_backend_payload, _rejected

    assert json.loads(_disabled_payload())["status"] == "not_enabled"
    assert json.loads(_no_backend_payload())["status"] == "not_configured"
    assert json.loads(_rejected("bad input"))["status"] == "rejected"
