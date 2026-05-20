"""Tests for the T5-04.4 post-write verify hook in file_ops.

The hook fires from Write + Edit after a successful write (i.e.
after the lint_after_write gate). On the green path the tool
return string stays clean — verification appends nothing. On a
failed verification (failed_diagnostics / failed_run), the
outcome's report is appended so the model sees the rollback hint
inline.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from athena.tools import file_ops


def _cfg(**overrides) -> SimpleNamespace:
    base = {
        "verify_on_write": "diagnose",
        "verify_command": None,
        "verify_auto_rollback": False,
        "verify_auto_retry": False,
        "verify_max_retries": 2,
        "verify_run_timeout_s": 30.0,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    file_ops.set_workspace(tmp_path, max_read=1_000_000)
    # Auto-approve any path-security prompts during the test.
    monkeypatch.setattr(
        "athena.safety.path_security.validate_path",
        lambda p, intent="write": Path(p),
    )
    return tmp_path


# ---------------------------------------------------------------------------
# Off path
# ---------------------------------------------------------------------------


def test_verify_off_means_no_tail(workspace, monkeypatch):
    monkeypatch.setattr("athena.config.load_config", lambda: _cfg(verify_on_write="off"))
    out = file_ops.Write(file_path="hello.txt", content="hi\n")
    assert "created" in out
    assert "✓" not in out
    assert "✗" not in out


# ---------------------------------------------------------------------------
# Green path: no tail
# ---------------------------------------------------------------------------


def test_passing_verification_appends_nothing(workspace, monkeypatch):
    monkeypatch.setattr("athena.config.load_config", lambda: _cfg())

    # Stub the verifier's diagnose to return clean — no errors.
    class _PassingVerifier:
        def __init__(self, **kw):
            pass

        def verify_write(self, p):
            from athena.verify.outcome import VerificationOutcome

            return VerificationOutcome(path=str(p), outcome="passed")

    monkeypatch.setattr("athena.verify.VerifiedExecution", _PassingVerifier)

    out = file_ops.Write(file_path="ok.py", content="x = 1\n")
    assert "created" in out
    # green path = quiet
    assert "✓" not in out
    assert "✗" not in out


# ---------------------------------------------------------------------------
# Failure: tail surfaces report
# ---------------------------------------------------------------------------


def test_failed_verification_appends_report(workspace, monkeypatch):
    monkeypatch.setattr("athena.config.load_config", lambda: _cfg())

    class _FailingVerifier:
        def __init__(self, **kw):
            pass

        def verify_write(self, p):
            from athena.verify.outcome import VerificationOutcome

            return VerificationOutcome(
                path=str(p),
                outcome="failed_diagnostics",
                checkpoint_id="cp-abc",
                introduced_errors=["line 1:1 syntax bonk"],
            )

    monkeypatch.setattr("athena.verify.VerifiedExecution", _FailingVerifier)
    monkeypatch.setattr("athena.tools.file_ops.lint_after_write", lambda p, c: None)

    out = file_ops.Write(file_path="bad.py", content="x = 1\n")
    # The write itself succeeded
    assert "created" in out
    # But the report tail is appended
    assert "✗" in out
    assert "syntax bonk" in out
    assert "/rollback-to cp-abc" in out


def test_lint_failure_short_circuits_before_verify(workspace, monkeypatch):
    """If lint_after_write rejects the write, the verify hook
    shouldn't run — the model already gets a "fix the syntax"
    message."""
    monkeypatch.setattr("athena.config.load_config", lambda: _cfg())

    def boom_verify(p):
        raise AssertionError("verify must not run when lint failed")

    class _ShouldNotRun:
        def __init__(self, **kw):
            pass

        verify_write = staticmethod(boom_verify)

    monkeypatch.setattr("athena.verify.VerifiedExecution", _ShouldNotRun)
    monkeypatch.setattr(
        "athena.tools.file_ops.lint_after_write",
        lambda p, content: "invalid syntax (synthetic)",
    )

    out = file_ops.Write(file_path="syn.py", content="def x(\n")
    assert "failed validation" in out
    assert "✗" not in out


# ---------------------------------------------------------------------------
# Verifier exception → silent
# ---------------------------------------------------------------------------


def test_verifier_exception_does_not_break_write(workspace, monkeypatch):
    monkeypatch.setattr("athena.config.load_config", lambda: _cfg())

    class _BrokenVerifier:
        def __init__(self, **kw):
            raise RuntimeError("verifier construction blew up")

    monkeypatch.setattr("athena.verify.VerifiedExecution", _BrokenVerifier)
    out = file_ops.Write(file_path="x.py", content="x=1\n")
    # Write succeeds without tail; the verifier's bug is debug-logged only.
    assert "created" in out
    assert "✗" not in out


# ---------------------------------------------------------------------------
# Edit path: tail appended on failure
# ---------------------------------------------------------------------------


def test_edit_invokes_verify_on_replace(workspace, monkeypatch):
    """Edit's normal-replace branch should also call the verify
    hook and append the report on failure."""
    target = workspace / "edit_me.py"
    target.write_text("old = 1\n", encoding="utf-8")

    monkeypatch.setattr("athena.config.load_config", lambda: _cfg())

    class _FailingVerifier:
        def __init__(self, **kw):
            pass

        def verify_write(self, p):
            from athena.verify.outcome import VerificationOutcome

            return VerificationOutcome(
                path=str(p),
                outcome="failed_diagnostics",
                checkpoint_id="cp-edit",
                introduced_errors=["bad import"],
            )

    monkeypatch.setattr("athena.verify.VerifiedExecution", _FailingVerifier)
    monkeypatch.setattr("athena.tools.file_ops.lint_after_write", lambda p, c: None)

    out = file_ops.Edit(
        file_path=str(target),
        old_string="old",
        new_string="new",
    )
    assert "edited" in out
    assert "/rollback-to cp-edit" in out
    assert "bad import" in out
