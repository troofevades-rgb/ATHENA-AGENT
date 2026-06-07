"""Tests for the differentiated MCP surface (T5-05.3).

Manifest-driven advertisement: a tool whose backing capability
isn't available on the host is NOT included in the descriptor
list. The dispatcher only reaches handlers whose tools were
advertised; an absent capability surfaces as an "isError" result
when called explicitly.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from athena.mcp.differentiated import build_differentiated_tools
from athena.providers.base import Capabilities, Provider

# ---------------------------------------------------------------------------
# Synthetic provider + registry patching
# ---------------------------------------------------------------------------


def _stub_provider(name: str, *, vision: bool, is_local: bool = False):
    class _S(Provider):
        pass

    _S.name = name
    _S.requires_api_key = not is_local
    caps = Capabilities(vision=vision, is_local=is_local)
    _S.static_capabilities = classmethod(lambda cls, model=None: caps)  # type: ignore[method-assign]
    return _S


@pytest.fixture
def empty_registry(monkeypatch):
    """Replace the live provider registry with an empty dict so
    the test controls what providers exist."""
    new: dict[str, type[Provider]] = {}
    monkeypatch.setattr("athena.providers._REGISTRY", new)
    monkeypatch.setattr("athena.media.registry._REGISTRY", new)
    return new


def _cfg(**overrides) -> SimpleNamespace:
    base = {
        "media_backend_prefer": "local",
        "mcp_expose": (),
        "verify_on_write": "diagnose",
        "verify_command": None,
        "verify_auto_rollback": False,
        "verify_auto_retry": False,
        "verify_max_retries": 2,
        "verify_run_timeout_s": 30.0,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# Manifest-driven advertisement
# ---------------------------------------------------------------------------


def test_differentiated_omits_rollback_when_absent(empty_registry, tmp_path):
    """No checkpoint manager → rollback_to + list_checkpoints
    aren't advertised."""
    bundle = build_differentiated_tools(
        workspace=tmp_path,
        cfg=_cfg(),
        checkpoint_manager=None,
    )
    names = [d["name"] for d in bundle.descriptors]
    assert "rollback_to" not in names
    assert "list_checkpoints" not in names
    # verified_write + recall ARE always available.
    assert "verified_write" in names
    assert "recall" in names


def test_differentiated_omits_media_when_no_vision(empty_registry, tmp_path):
    """No vision-declaring provider → analyze_image/video aren't
    advertised."""
    empty_registry["nv"] = _stub_provider("nv", vision=False)
    bundle = build_differentiated_tools(
        workspace=tmp_path,
        cfg=_cfg(),
        checkpoint_manager=object(),  # presence triggers rollback advertise
    )
    names = [d["name"] for d in bundle.descriptors]
    assert "analyze_image" not in names
    assert "analyze_video" not in names


def test_differentiated_advertises_media_when_vision_present(empty_registry, tmp_path):
    empty_registry["v"] = _stub_provider("v", vision=True, is_local=True)
    bundle = build_differentiated_tools(
        workspace=tmp_path,
        cfg=_cfg(),
        checkpoint_manager=None,
    )
    names = [d["name"] for d in bundle.descriptors]
    assert "analyze_image" in names
    assert "analyze_video" in names


def test_recall_always_advertised(empty_registry, tmp_path):
    bundle = build_differentiated_tools(
        workspace=tmp_path,
        cfg=_cfg(),
        checkpoint_manager=None,
    )
    names = [d["name"] for d in bundle.descriptors]
    assert "recall" in names


def test_mcp_expose_whitelist_narrows_surface(empty_registry, tmp_path):
    """Operator-provided mcp_expose whitelist narrows the surface
    even when more tools are technically available."""
    empty_registry["v"] = _stub_provider("v", vision=True, is_local=True)
    bundle = build_differentiated_tools(
        workspace=tmp_path,
        cfg=_cfg(mcp_expose=("verified_write", "recall")),
        checkpoint_manager=object(),  # would normally add rollback tools
    )
    names = [d["name"] for d in bundle.descriptors]
    assert names == ["verified_write", "recall"]


def test_no_raw_bash_tool_advertised(empty_registry, tmp_path):
    """The T3-02 curation rule: no raw code-exec over MCP. The
    differentiated surface advertises a curated set; nothing
    matching bash/exec/shell appears."""
    empty_registry["v"] = _stub_provider("v", vision=True, is_local=True)
    bundle = build_differentiated_tools(
        workspace=tmp_path,
        cfg=_cfg(),
        checkpoint_manager=object(),
    )
    names = {d["name"] for d in bundle.descriptors}
    forbidden = {"bash", "shell", "exec", "athena_bash", "Bash", "Execute"}
    assert names.isdisjoint(forbidden)


# ---------------------------------------------------------------------------
# verified_write integration
# ---------------------------------------------------------------------------


def test_verified_write_over_mcp_goes_through_verification(empty_registry, tmp_path, monkeypatch):
    """A verified_write call must run the T5-04 loop — the
    response carries the verification result inline."""

    captured_paths: list[str] = []

    class _Verifier:
        def __init__(self, **kw):
            pass

        def verify_write(self, p):
            captured_paths.append(str(p))
            from athena.verify.outcome import VerificationOutcome

            return VerificationOutcome(path=str(p), outcome="passed")

    monkeypatch.setattr("athena.verify.VerifiedExecution", _Verifier)
    # Avoid path_security workspace gate — accept the resolved path.
    monkeypatch.setattr(
        "athena.safety.path_security.validate_path",
        lambda p, intent="write": p,
    )

    bundle = build_differentiated_tools(
        workspace=tmp_path,
        cfg=_cfg(),
        checkpoint_manager=None,
    )
    target = tmp_path / "hello.txt"
    result = bundle.call("verified_write", {"path": str(target), "content": "hi\n"})
    assert "isError" not in result
    text = result["content"][0]["text"]
    assert "created" in text
    assert "verified" in text  # report's passed marker
    assert captured_paths == [str(target)]


def test_verified_write_failure_isError(empty_registry, tmp_path, monkeypatch):
    class _Failing:
        def __init__(self, **kw):
            pass

        def verify_write(self, p):
            from athena.verify.outcome import VerificationOutcome

            return VerificationOutcome(
                path=str(p),
                outcome="failed_diagnostics",
                checkpoint_id="cp-mcp",
                introduced_errors=["bad import"],
            )

    monkeypatch.setattr("athena.verify.VerifiedExecution", _Failing)
    monkeypatch.setattr(
        "athena.safety.path_security.validate_path",
        lambda p, intent="write": p,
    )

    bundle = build_differentiated_tools(
        workspace=tmp_path,
        cfg=_cfg(),
        checkpoint_manager=None,
    )
    target = tmp_path / "x.py"
    result = bundle.call("verified_write", {"path": str(target), "content": "x=1\n"})
    assert result.get("isError") is True
    text = result["content"][0]["text"]
    assert "/rollback-to cp-mcp" in text
    assert "bad import" in text


def test_verified_write_refuses_unsafe_path(empty_registry, tmp_path, monkeypatch):
    """A path the security gate refuses → isError without ever
    touching the verifier."""

    class _MustNotRun:
        def __init__(self, **kw):
            raise AssertionError("verifier must not run on refused path")

    monkeypatch.setattr("athena.verify.VerifiedExecution", _MustNotRun)

    def _refuse(p, intent="write"):
        raise PermissionError("outside workspace")

    monkeypatch.setattr("athena.safety.path_security.validate_path", _refuse)

    bundle = build_differentiated_tools(
        workspace=tmp_path,
        cfg=_cfg(),
        checkpoint_manager=None,
    )
    result = bundle.call("verified_write", {"path": "/etc/passwd", "content": "x"})
    assert result.get("isError") is True
    assert "refused by security" in result["content"][0]["text"]


# ---------------------------------------------------------------------------
# Rollback dispatch
# ---------------------------------------------------------------------------


def test_rollback_to_returns_error_when_manager_absent(empty_registry, tmp_path):
    """The descriptor isn't advertised when checkpoint_manager is
    None, but a malicious client could call by name anyway —
    the handler must return a clean error."""
    bundle = build_differentiated_tools(
        workspace=tmp_path,
        cfg=_cfg(mcp_expose=("rollback_to", "verified_write", "recall")),
        checkpoint_manager=None,
    )
    result = bundle.call("rollback_to", {"checkpoint_id": "cp-x"})
    assert result.get("isError") is True
    assert "no checkpoint manager" in result["content"][0]["text"]


def test_rollback_to_dispatches_to_manager(empty_registry, tmp_path):
    class _Mgr:
        def rollback_to(self, cp_id: str):
            return SimpleNamespace(id=cp_id, label="prelaunch")

        def list(self):
            return []

    bundle = build_differentiated_tools(
        workspace=tmp_path,
        cfg=_cfg(),
        checkpoint_manager=_Mgr(),
    )
    result = bundle.call("rollback_to", {"checkpoint_id": "cp-abc"})
    assert "isError" not in result
    assert "rolled back" in result["content"][0]["text"]
    assert "cp-abc" in result["content"][0]["text"]


# ---------------------------------------------------------------------------
# Vision dispatch
# ---------------------------------------------------------------------------


def test_analyze_image_resolves_backend(empty_registry, tmp_path):
    empty_registry["v"] = _stub_provider("v", vision=True, is_local=True)
    bundle = build_differentiated_tools(
        workspace=tmp_path,
        cfg=_cfg(),
        checkpoint_manager=None,
    )
    result = bundle.call("analyze_image", {"image_path": "/tmp/a.png", "prompt": "what is this?"})
    assert "isError" not in result
    text = result["content"][0]["text"]
    assert "v" in text  # backend name surfaced


def test_analyze_image_errors_when_no_vision_backend(empty_registry, tmp_path):
    bundle = build_differentiated_tools(
        workspace=tmp_path,
        cfg=_cfg(mcp_expose=("analyze_image",)),
        checkpoint_manager=None,
    )
    result = bundle.call("analyze_image", {"image_path": "x.png"})
    assert result.get("isError") is True
    assert "no vision backend" in result["content"][0]["text"]


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def test_unknown_tool_returns_error(empty_registry, tmp_path):
    bundle = build_differentiated_tools(
        workspace=tmp_path,
        cfg=_cfg(),
        checkpoint_manager=None,
    )
    result = bundle.call("definitely_not_a_real_tool", {})
    assert result.get("isError") is True
    assert "unknown" in result["content"][0]["text"]


def test_invalid_arguments_surface_cleanly(empty_registry, tmp_path):
    """Missing required arg → isError with a useful message, not
    a 500."""
    bundle = build_differentiated_tools(
        workspace=tmp_path,
        cfg=_cfg(),
        checkpoint_manager=None,
    )
    result = bundle.call("verified_write", {})  # no path, no content
    assert result.get("isError") is True


# ---------------------------------------------------------------------------
# recall — FTS5 session search (regression: imported the removed
# athena.sessions.search and always failed "recall unavailable")
# ---------------------------------------------------------------------------


def test_recall_returns_matching_session_content(empty_registry, tmp_path, monkeypatch) -> None:

    from athena.sessions.store import SessionMeta, SessionStore, new_session_id

    pdir = tmp_path / "profiles" / "default"
    pdir.mkdir(parents=True)
    ws = str(tmp_path / "proj")
    store = SessionStore(pdir)
    sid = new_session_id()
    store.open_session(SessionMeta(session_id=sid, profile="default", model="qwen", workspace=ws))
    store.append_turn(sid, {"role": "user", "content": "find the needle here"})
    store.close()

    # _recall resolves the store via `from ..config import profile_dir`.
    monkeypatch.setattr("athena.config.profile_dir", lambda profile="default": pdir)
    bundle = build_differentiated_tools(
        workspace=Path(ws),
        cfg=_cfg(profile="default"),
        checkpoint_manager=None,
    )
    res = bundle.call("recall", {"query": "needle"})
    assert res.get("isError") is not True
    text = " ".join(c["text"] for c in res["content"])
    assert "needle" in text.lower()
    assert sid[:8] in text


def test_recall_no_matches_message(empty_registry, tmp_path, monkeypatch) -> None:

    from athena.sessions.store import SessionStore

    pdir = tmp_path / "profiles" / "default"
    pdir.mkdir(parents=True)
    SessionStore(pdir).close()  # empty store, no sessions
    monkeypatch.setattr("athena.config.profile_dir", lambda profile="default": pdir)
    bundle = build_differentiated_tools(
        workspace=Path(str(tmp_path / "proj")),
        cfg=_cfg(profile="default"),
        checkpoint_manager=None,
    )
    res = bundle.call("recall", {"query": "nothingmatchesthisquery"})
    assert res.get("isError") is not True
    assert "no matches" in res["content"][0]["text"].lower()
