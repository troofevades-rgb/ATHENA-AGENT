"""Tests for the approval-callback ContextVar."""
import logging
import threading

from ocode.safety.approval_callback import (
    AUTO_DENY,
    _interactive_approval,
    get_approval_callback,
    reset_approval_callback,
    set_approval_callback,
)


def test_default_callback_is_interactive():
    assert get_approval_callback() is _interactive_approval


def test_set_and_reset_callback():
    def fake(tool_name: str, args: dict) -> str:
        return "allow"

    token = set_approval_callback(fake)
    try:
        assert get_approval_callback() is fake
    finally:
        reset_approval_callback(token)
    assert get_approval_callback() is _interactive_approval


def test_auto_deny_logs_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="ocode.safety.approval_callback"):
        AUTO_DENY("DangerousTool", {"x": 1})
    assert any(
        "fork auto-denied" in rec.message and "DangerousTool" in rec.message
        for rec in caplog.records
    )


def test_auto_deny_returns_deny():
    assert AUTO_DENY("Bash", {"command": "rm -rf /"}) == "deny"


def test_callback_isolated_per_thread():
    """A child thread starts with the default callback regardless of the parent's
    setting, and the parent's callback survives whatever the child installs."""
    def parent_cb(tool_name: str, args: dict) -> str:
        return "parent"

    parent_token = set_approval_callback(parent_cb)
    try:
        seen: dict[str, object] = {}

        def child():
            seen["initial"] = get_approval_callback()
            child_token = set_approval_callback(AUTO_DENY)
            try:
                seen["after_set"] = get_approval_callback()
            finally:
                reset_approval_callback(child_token)

        t = threading.Thread(target=child)
        t.start()
        t.join(timeout=2.0)

        assert seen["initial"] is _interactive_approval
        assert seen["after_set"] is AUTO_DENY
        assert get_approval_callback() is parent_cb
    finally:
        reset_approval_callback(parent_token)
