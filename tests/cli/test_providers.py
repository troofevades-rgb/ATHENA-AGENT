"""athena providers CLI — list / add-key / remove-key / test."""
from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

import athena.cli.providers as providers_cli
from athena.providers.credential_pool import Credential, CredentialPool


def _run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            rc = providers_cli.main(argv)
        except SystemExit as e:
            if isinstance(e.code, str):
                err.write(e.code + "\n")
                rc = 2
            else:
                rc = int(e.code or 0)
    return rc, out.getvalue(), err.getvalue()


@pytest.fixture
def pool_path(tmp_path: Path) -> Path:
    return tmp_path / "credentials.json"


# ---- list ---------------------------------------------------------------


def test_list_empty_shows_every_registered_provider_with_zero_keys(pool_path: Path):
    rc, stdout, _ = _run(["--pool-path", str(pool_path), "list"])
    assert rc == 0
    # Every built-in provider should appear, all with 0 keys.
    for name in ("ollama", "anthropic", "openai", "google",
                 "openai_compat", "openrouter", "nous"):
        assert name in stdout
    assert "0 key(s)" in stdout


def test_list_shows_credential_counts_and_suffixes(pool_path: Path):
    pool = CredentialPool(pool_path)
    pool.add_credential("anthropic", Credential(key="sk-ant-abc1234"))
    pool.add_credential("anthropic", Credential(key="sk-ant-def5678"))
    rc, stdout, _ = _run(["--pool-path", str(pool_path), "list"])
    assert rc == 0
    # Both suffixes appear in redacted form.
    assert "...1234" in stdout
    assert "...5678" in stdout
    assert "2 key(s)" in stdout


def test_list_flags_cooldown_credentials(pool_path: Path):
    pool = CredentialPool(pool_path)
    pool.add_credential("openai", Credential(key="k-abcd"))
    pool.mark_429("openai", "k-abcd")
    rc, stdout, _ = _run(["--pool-path", str(pool_path), "list"])
    assert rc == 0
    assert "cooldown" in stdout


# ---- add-key ------------------------------------------------------------


def test_add_key_writes_to_pool(pool_path: Path):
    rc, stdout, _ = _run([
        "--pool-path", str(pool_path),
        "add-key", "anthropic", "sk-ant-mynewkey",
        "--label", "personal",
    ])
    assert rc == 0
    assert "...wkey" in stdout
    assert "personal" in stdout

    pool = CredentialPool(pool_path)
    listed = pool.list_credentials("anthropic")["anthropic"]
    assert len(listed) == 1
    assert listed[0]["label"] == "personal"


def test_add_key_warns_on_unknown_provider(pool_path: Path):
    rc, _, err = _run([
        "--pool-path", str(pool_path),
        "add-key", "definitely-not-real", "some-key",
    ])
    # Warns but still writes (forward-compat with plugin-provided providers).
    assert rc == 0
    assert "not a registered provider" in err


def test_add_key_idempotent_for_exact_match(pool_path: Path):
    _run(["--pool-path", str(pool_path), "add-key", "openai", "sk-test"])
    _run(["--pool-path", str(pool_path), "add-key", "openai", "sk-test"])
    pool = CredentialPool(pool_path)
    assert len(pool.list_credentials("openai")["openai"]) == 1


# ---- remove-key ---------------------------------------------------------


def test_remove_key_by_exact_match(pool_path: Path):
    _run(["--pool-path", str(pool_path), "add-key", "openai", "sk-aaa"])
    _run(["--pool-path", str(pool_path), "add-key", "openai", "sk-bbb"])
    rc, stdout, _ = _run([
        "--pool-path", str(pool_path), "remove-key", "openai", "sk-aaa",
    ])
    assert rc == 0
    assert "removed 1" in stdout
    pool = CredentialPool(pool_path)
    listed = pool.list_credentials("openai")["openai"]
    assert len(listed) == 1
    assert listed[0]["key_suffix"] == "...-bbb"


def test_remove_key_by_unambiguous_prefix(pool_path: Path):
    _run(["--pool-path", str(pool_path), "add-key", "openai", "sk-12345"])
    _run(["--pool-path", str(pool_path), "add-key", "openai", "sk-67890"])
    rc, stdout, _ = _run([
        "--pool-path", str(pool_path), "remove-key", "openai", "sk-123",
    ])
    assert rc == 0
    assert "removed 1" in stdout


def test_remove_key_ambiguous_prefix_errors(pool_path: Path):
    _run(["--pool-path", str(pool_path), "add-key", "openai", "sk-abc-1"])
    _run(["--pool-path", str(pool_path), "add-key", "openai", "sk-abc-2"])
    rc, _, err = _run([
        "--pool-path", str(pool_path), "remove-key", "openai", "sk-abc",
    ])
    assert rc == 2
    assert "ambiguous" in err or "no credential matched" in err


def test_remove_key_unknown_provider_errors(pool_path: Path):
    rc, _, err = _run([
        "--pool-path", str(pool_path), "remove-key", "openai", "anything",
    ])
    assert rc == 2


# ---- test --------------------------------------------------------------


def test_test_ollama_skips_credential_check(monkeypatch, pool_path: Path):
    """Ollama doesn't need credentials; the probe just calls list_models."""
    captured: dict = {}

    class _StubOllama:
        def __init__(self, host=None, **_):
            captured["host"] = host
        def list_models(self):
            return ["qwen2.5-coder:14b", "llama3.1:8b"]
        def close(self):
            pass

    from athena.providers import _REGISTRY
    monkeypatch.setitem(_REGISTRY, "ollama", _StubOllama)
    rc, stdout, _ = _run([
        "--pool-path", str(pool_path), "test", "--provider", "ollama",
    ])
    assert rc == 0
    assert "ok" in stdout
    assert "reachable" in stdout
    assert "2 local models" in stdout


def test_test_hosted_provider_reports_no_credential(monkeypatch, pool_path: Path):
    rc, stdout, _ = _run([
        "--pool-path", str(pool_path), "test", "--provider", "anthropic",
    ])
    assert rc == 1
    assert "FAIL" in stdout
    assert "no credential" in stdout


def test_test_unknown_provider_errors(pool_path: Path):
    rc, _, err = _run([
        "--pool-path", str(pool_path), "test", "--provider", "not-real",
    ])
    assert rc == 2
    assert "not registered" in err


def test_test_openai_compat_needs_host(pool_path: Path):
    rc, stdout, _ = _run([
        "--pool-path", str(pool_path), "test", "--provider", "openai_compat",
    ])
    assert rc == 1
    assert "not configured" in stdout.lower() or "FAIL" in stdout


# ---- models -------------------------------------------------------------


def test_models_unknown_provider_errors(pool_path: Path):
    rc, _, err = _run([
        "--pool-path", str(pool_path), "models", "definitely-fake-provider",
    ])
    assert rc == 2
    assert "not registered" in err


def test_models_no_credential_for_hosted(pool_path: Path):
    """Hosted provider with no key in the pool can't build the provider."""
    rc, _, err = _run([
        "--pool-path", str(pool_path), "models", "anthropic",
    ])
    assert rc == 2
    assert "no credentials available" in err.lower() or "could not build" in err


def test_models_lists_what_provider_returns(monkeypatch, pool_path: Path):
    """When the resolver hands us a Provider with a working list_models,
    the CLI prints every id sorted, one per line."""
    captured: list[str] = []

    class _StubAnthropic:
        def __init__(self, **_):
            pass
        def list_models(self):
            return ["claude-haiku-4-5-20251001", "claude-sonnet-4-7", "claude-opus-4-7"]
        def close(self):
            pass

    # Replace the registry's anthropic entry so the resolver hands the
    # stub back, AND seed a credential so the resolver doesn't bail.
    from athena.providers import _REGISTRY
    monkeypatch.setitem(_REGISTRY, "anthropic", _StubAnthropic)
    from athena.providers.credential_pool import CredentialPool, Credential
    CredentialPool(pool_path).add_credential("anthropic", Credential(key="sk-test"))

    rc, stdout, _ = _run([
        "--pool-path", str(pool_path), "models", "anthropic",
    ])
    assert rc == 0
    # Sorted by name; sonnet < opus alphabetically — verify they show.
    assert "claude-haiku-4-5-20251001" in stdout
    assert "claude-sonnet-4-7" in stdout
    assert "claude-opus-4-7" in stdout


def test_models_limit_truncates(monkeypatch, pool_path: Path):
    class _Stub:
        def __init__(self, **_): pass
        def list_models(self):
            return [f"model-{i}" for i in range(50)]
        def close(self): pass

    from athena.providers import _REGISTRY
    monkeypatch.setitem(_REGISTRY, "anthropic", _Stub)
    from athena.providers.credential_pool import CredentialPool, Credential
    CredentialPool(pool_path).add_credential("anthropic", Credential(key="k"))

    rc, stdout, _ = _run([
        "--pool-path", str(pool_path), "models", "anthropic", "--limit", "3",
    ])
    assert rc == 0
    listed = [line.strip() for line in stdout.splitlines() if line.strip()]
    assert len(listed) == 3


def test_models_propagates_provider_error(monkeypatch, pool_path: Path):
    class _Broken:
        def __init__(self, **_): pass
        def list_models(self):
            raise RuntimeError("simulated 401")
        def close(self): pass

    from athena.providers import _REGISTRY
    monkeypatch.setitem(_REGISTRY, "anthropic", _Broken)
    from athena.providers.credential_pool import CredentialPool, Credential
    CredentialPool(pool_path).add_credential("anthropic", Credential(key="k"))

    rc, _, err = _run([
        "--pool-path", str(pool_path), "models", "anthropic",
    ])
    assert rc == 1
    assert "list_models failed" in err
