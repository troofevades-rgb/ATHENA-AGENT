"""CredentialPool: get/round-robin/cooldown/persist/redact."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest

from athena.providers.credential_pool import (
    Credential,
    CredentialPool,
    global_pool,
    reset_global_pool,
)


@pytest.fixture
def pool(tmp_path: Path) -> CredentialPool:
    return CredentialPool(tmp_path / "credentials.json", cooldown_seconds=60)


# ---- Credential dataclass -----------------------------------------------


def test_credential_redacted_strips_to_last_4():
    c = Credential(key="sk-ant-abcdefghijklmnop", label="primary")
    out = c.redacted()
    assert out["key_suffix"] == "...mnop"
    assert out["label"] == "primary"
    assert out["in_cooldown"] is False


def test_credential_round_trips_via_dict():
    when = datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc)
    c = Credential(
        key="k",
        label="l",
        fail_count=3,
        last_429_at=when,
        last_used_at=when,
    )
    d = c.to_dict()
    c2 = Credential.from_dict(d)
    assert c2.key == "k"
    assert c2.fail_count == 3
    assert c2.last_429_at == when
    assert c2.last_used_at == when


# ---- Basic get ----------------------------------------------------------


def test_get_returns_none_for_unknown_provider(pool: CredentialPool):
    assert pool.get("nope") is None


def test_get_returns_credential_after_add(pool: CredentialPool):
    pool.add_credential("anthropic", Credential(key="sk-1"))
    c = pool.get("anthropic")
    assert c is not None
    assert c.key == "sk-1"


def test_get_stamps_last_used_at(pool: CredentialPool):
    pool.add_credential("anthropic", Credential(key="sk-1"))
    c = pool.get("anthropic")
    assert c.last_used_at is not None
    assert c.last_used_at.tzinfo is not None


def test_add_credential_is_idempotent(pool: CredentialPool):
    """Adding the same key twice should not duplicate."""
    pool.add_credential("anthropic", Credential(key="sk-1"))
    pool.add_credential("anthropic", Credential(key="sk-1", label="ignored-dup"))
    listed = pool.list_credentials("anthropic")["anthropic"]
    assert len(listed) == 1


# ---- Round-robin --------------------------------------------------------


def test_round_robin_selection(pool: CredentialPool):
    """Sequential gets rotate through the bucket in order."""
    pool.add_credential("anthropic", Credential(key="sk-1"))
    pool.add_credential("anthropic", Credential(key="sk-2"))
    pool.add_credential("anthropic", Credential(key="sk-3"))
    seen = [pool.get("anthropic").key for _ in range(6)]
    assert seen == ["sk-1", "sk-2", "sk-3", "sk-1", "sk-2", "sk-3"]


# ---- 429 cooldown -------------------------------------------------------


def test_429_skips_credential_in_cooldown(pool: CredentialPool):
    pool.add_credential("openai", Credential(key="k1"))
    pool.add_credential("openai", Credential(key="k2"))
    # k1 hits 429, next get should skip it.
    pool.get("openai")  # advances to k2-start
    pool.mark_429("openai", "k1")
    next1 = pool.get("openai")
    next2 = pool.get("openai")
    assert next1.key == "k2"
    assert next2.key == "k2"  # k1 still in cooldown; only k2 available


def test_cooldown_expires(tmp_path: Path):
    """A 0-second cooldown means the 429 stamp is immediately ignored."""
    p = CredentialPool(tmp_path / "c.json", cooldown_seconds=0)
    p.add_credential("openai", Credential(key="k1"))
    p.add_credential("openai", Credential(key="k2"))
    p.mark_429("openai", "k1")
    # k1 should be eligible again because cooldown=0.
    seen = {p.get("openai").key for _ in range(4)}
    assert seen == {"k1", "k2"}


def test_all_in_cooldown_returns_none(pool: CredentialPool):
    pool.add_credential("openai", Credential(key="k1"))
    pool.add_credential("openai", Credential(key="k2"))
    pool.mark_429("openai", "k1")
    pool.mark_429("openai", "k2")
    assert pool.get("openai") is None


def test_clear_cooldown_makes_credential_eligible_again(pool: CredentialPool):
    pool.add_credential("openai", Credential(key="k1"))
    pool.mark_429("openai", "k1")
    assert pool.get("openai") is None
    pool.clear_cooldown("openai", "k1")
    assert pool.get("openai").key == "k1"


def test_mark_429_unknown_returns_false(pool: CredentialPool):
    assert pool.mark_429("nope", "k") is False
    pool.add_credential("openai", Credential(key="k1"))
    assert pool.mark_429("openai", "nope-key") is False


# ---- Failure counting ---------------------------------------------------


def test_mark_failure_bumps_count(pool: CredentialPool):
    pool.add_credential("openai", Credential(key="k1"))
    pool.mark_failure("openai", "k1")
    pool.mark_failure("openai", "k1")
    cred = pool.get("openai")
    assert cred.fail_count == 2


def test_mark_failure_unknown_returns_false(pool: CredentialPool):
    assert pool.mark_failure("openai", "k") is False


# ---- Removal ------------------------------------------------------------


def test_remove_by_exact_key(pool: CredentialPool):
    pool.add_credential("openai", Credential(key="k1"))
    pool.add_credential("openai", Credential(key="k2"))
    assert pool.remove_credential("openai", "k1") == 1
    listed = [c["key_suffix"] for c in pool.list_credentials("openai")["openai"]]
    assert all("k1" not in s for s in listed)


def test_remove_by_unambiguous_prefix(pool: CredentialPool):
    pool.add_credential("openai", Credential(key="sk-abc-123"))
    pool.add_credential("openai", Credential(key="sk-xyz-789"))
    assert pool.remove_credential("openai", "sk-abc") == 1


def test_remove_ambiguous_prefix_is_noop(pool: CredentialPool):
    pool.add_credential("openai", Credential(key="sk-abc-123"))
    pool.add_credential("openai", Credential(key="sk-abc-456"))
    # Two credentials match the prefix; refuse to guess.
    assert pool.remove_credential("openai", "sk-abc") == 0
    assert len(pool.list_credentials("openai")["openai"]) == 2


def test_remove_unknown_returns_zero(pool: CredentialPool):
    assert pool.remove_credential("openai", "nope") == 0


def test_remove_by_suffix(pool: CredentialPool):
    """The listing shows '...XXXX' suffixes — remove must accept that
    form so the user can act on what they see."""
    pool.add_credential("openai", Credential(key="sk-abc-123-WXYZ"))
    pool.add_credential("openai", Credential(key="sk-def-456-MNOP"))
    assert pool.remove_credential("openai", "WXYZ") == 1
    listed = pool.list_credentials("openai")["openai"]
    assert len(listed) == 1
    assert listed[0]["key_suffix"] == "...MNOP"


def test_remove_by_suffix_with_listing_dots(pool: CredentialPool):
    """The literal display form '...WXYZ' should work too."""
    pool.add_credential("openai", Credential(key="sk-abc-WXYZ"))
    assert pool.remove_credential("openai", "...WXYZ") == 1


def test_remove_ambiguous_suffix_is_noop(pool: CredentialPool):
    pool.add_credential("openai", Credential(key="aaa-WXYZ"))
    pool.add_credential("openai", Credential(key="bbb-WXYZ"))
    assert pool.remove_credential("openai", "WXYZ") == 0


def test_prefix_match_preferred_over_suffix(pool: CredentialPool):
    """When the needle matches both a prefix and a suffix on different
    credentials, prefix wins. (Real keys are usually disambiguated by
    suffix only — the listing prefix is '...' — but the priority order
    must be deterministic regardless.)"""
    pool.add_credential("openai", Credential(key="abc-thing"))
    pool.add_credential("openai", Credential(key="other-abc"))
    # "abc" prefix-matches "abc-thing" exactly once.
    assert pool.remove_credential("openai", "abc") == 1
    listed = pool.list_credentials("openai")["openai"]
    assert len(listed) == 1
    assert listed[0]["key_suffix"][-3:] == "abc"


# ---- Persistence --------------------------------------------------------


def test_credentials_persist_to_disk(tmp_path: Path):
    path = tmp_path / "credentials.json"
    p1 = CredentialPool(path)
    p1.add_credential("anthropic", Credential(key="sk-1", label="primary"))
    p1.add_credential("anthropic", Credential(key="sk-2"))
    p1.mark_429("anthropic", "sk-1")

    # New pool reading the same file picks up the data.
    p2 = CredentialPool(path)
    listed = p2.list_credentials("anthropic")["anthropic"]
    assert len(listed) == 2
    assert any(c["label"] == "primary" for c in listed)
    # The 429 stamp survived the round-trip.
    assert any(c["in_cooldown"] for c in listed)


def test_load_tolerates_missing_file(tmp_path: Path):
    """No file → empty pool, no exception."""
    p = CredentialPool(tmp_path / "nope" / "credentials.json")
    assert p.providers() == []


def test_load_tolerates_malformed_json(tmp_path: Path):
    path = tmp_path / "c.json"
    path.write_text("{ not json", encoding="utf-8")
    p = CredentialPool(path)
    assert p.providers() == []


def test_save_is_atomic(tmp_path: Path):
    """The intermediate tempfile shouldn't linger after a successful save."""
    p = CredentialPool(tmp_path / "credentials.json")
    p.add_credential("openai", Credential(key="k1"))
    leftover = list(tmp_path.glob(".credentials-*"))
    assert leftover == []


def test_disk_file_format_keeps_keys_as_is(tmp_path: Path):
    """Stored on disk un-redacted (the file is user-only). Redaction
    happens only in list_credentials()."""
    path = tmp_path / "c.json"
    p = CredentialPool(path)
    p.add_credential("openai", Credential(key="sk-secret-12345"))
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["openai"][0]["key"] == "sk-secret-12345"


# ---- Listing / providers ------------------------------------------------


def test_list_all_providers(pool: CredentialPool):
    pool.add_credential("anthropic", Credential(key="a1"))
    pool.add_credential("openai", Credential(key="o1"))
    pool.add_credential("openai", Credential(key="o2"))
    all_creds = pool.list_credentials()
    assert set(all_creds.keys()) == {"anthropic", "openai"}
    assert len(all_creds["openai"]) == 2


def test_providers_returns_only_those_with_credentials(pool: CredentialPool):
    pool.add_credential("openai", Credential(key="k1"))
    pool.remove_credential("openai", "k1")
    assert "openai" not in pool.providers()


# ---- Thread safety ------------------------------------------------------


def test_concurrent_get_no_double_pick(pool: CredentialPool):
    """20 threads, 50 gets each. Every result must be a valid Credential
    (no crashes, no None when credentials exist)."""
    for i in range(5):
        pool.add_credential("openai", Credential(key=f"k{i}"))

    results: list = []
    lock = threading.Lock()

    def worker():
        for _ in range(50):
            c = pool.get("openai")
            with lock:
                results.append(c)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert all(c is not None for c in results)
    assert len(results) == 20 * 50
    keys = {c.key for c in results}
    assert keys == {"k0", "k1", "k2", "k3", "k4"}


# ---- Global pool -------------------------------------------------------


def test_global_pool_singleton(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("athena.config.CONFIG_DIR", tmp_path)
    reset_global_pool()
    try:
        p1 = global_pool()
        p2 = global_pool()
        assert p1 is p2
    finally:
        reset_global_pool()


def test_global_pool_uses_config_dir(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("athena.config.CONFIG_DIR", tmp_path)
    reset_global_pool()
    try:
        p = global_pool()
        p.add_credential("anthropic", Credential(key="sk-x"))
        assert (tmp_path / "credentials.json").exists()
    finally:
        reset_global_pool()


# ---------------------------------------------------------------------------
# T2-02.7: get_credential_rate_state surface
# ---------------------------------------------------------------------------


def test_credential_pool_exposes_rate_state(tmp_path):
    """get_credential_rate_state() returns per-(provider, credential)
    cooldown + 429 view, keyed by redacted ...<last-4> suffix."""
    from athena.providers.credential_pool import Credential, CredentialPool

    pool = CredentialPool(tmp_path / "credentials.json")
    pool.add_credential("anthropic", Credential(key="sk-ant-aaaa1111abcd"))
    pool.add_credential("anthropic", Credential(key="sk-ant-bbbb2222wxyz"))

    state = pool.get_credential_rate_state()
    assert "anthropic" in state
    assert "...abcd" in state["anthropic"]
    assert "...wxyz" in state["anthropic"]
    assert state["anthropic"]["...abcd"]["in_cooldown"] is False
    assert state["anthropic"]["...abcd"]["fail_count"] == 0


def test_credential_pool_rate_state_reflects_429(tmp_path):
    """mark_429 stamps last_429_at; get_credential_rate_state surfaces
    in_cooldown=True until clear_cooldown."""
    from athena.providers.credential_pool import Credential, CredentialPool

    pool = CredentialPool(tmp_path / "credentials.json")
    key = "sk-ant-zzzz9999cdef"
    pool.add_credential("anthropic", Credential(key=key))

    assert pool.get_credential_rate_state()["anthropic"]["...cdef"]["in_cooldown"] is False

    pool.mark_429("anthropic", key)
    after = pool.get_credential_rate_state()
    assert after["anthropic"]["...cdef"]["in_cooldown"] is True
    assert after["anthropic"]["...cdef"]["last_429_at"] is not None

    pool.clear_cooldown("anthropic", key)
    cleared = pool.get_credential_rate_state()
    assert cleared["anthropic"]["...cdef"]["in_cooldown"] is False


def test_credential_pool_rate_state_includes_fail_count(tmp_path):
    from athena.providers.credential_pool import Credential, CredentialPool

    pool = CredentialPool(tmp_path / "credentials.json")
    key = "sk-test-failfail9876"
    pool.add_credential("openai", Credential(key=key))

    pool.mark_failure("openai", key)
    pool.mark_failure("openai", key)
    state = pool.get_credential_rate_state()
    assert state["openai"]["...9876"]["fail_count"] == 2


def test_credential_pool_rate_state_empty_when_no_creds(tmp_path):
    from athena.providers.credential_pool import CredentialPool

    pool = CredentialPool(tmp_path / "credentials.json")
    assert pool.get_credential_rate_state() == {}
