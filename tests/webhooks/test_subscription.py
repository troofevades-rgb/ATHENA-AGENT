"""WebhookSubscription dataclass + SQLite WebhookStore."""

from __future__ import annotations

from pathlib import Path

import pytest

from athena.webhooks.subscription import WebhookStore, WebhookSubscription

# ---- dataclass validation -------------------------------------------


def test_construct_minimal_skill_binding() -> None:
    sub = WebhookSubscription(
        skill_name="summarize",
        auth_secret="s3cret",
    )
    assert sub.binding_type == "skill"
    assert sub.skill_name == "summarize"
    assert sub.auth_type == "hmac_sha256"
    assert sub.enabled is True
    assert sub.fire_count == 0
    assert sub.id  # auto-generated UUID4


def test_prompt_binding_requires_template() -> None:
    with pytest.raises(ValueError, match="prompt_template"):
        WebhookSubscription(
            binding_type="prompt",
            prompt_template=None,
            auth_secret="x",
        )


def test_skill_binding_requires_skill_name() -> None:
    with pytest.raises(ValueError, match="skill_name"):
        WebhookSubscription(skill_name=None, auth_secret="x")


def test_auth_hmac_requires_secret() -> None:
    with pytest.raises(ValueError, match="auth_secret"):
        WebhookSubscription(
            skill_name="x",
            auth_type="hmac_sha256",
            auth_secret="",
        )


def test_auth_bearer_requires_secret() -> None:
    with pytest.raises(ValueError, match="auth_secret"):
        WebhookSubscription(
            skill_name="x",
            auth_type="bearer",
            auth_secret="",
        )


def test_auth_none_doesnt_require_secret() -> None:
    sub = WebhookSubscription(
        skill_name="x",
        auth_type="none",
        auth_secret="",
    )
    assert sub.auth_type == "none"


def test_invalid_auth_type_rejected() -> None:
    with pytest.raises(ValueError, match="auth_type"):
        WebhookSubscription(
            skill_name="x",
            auth_type="basic_auth",  # type: ignore[arg-type]
        )


def test_invalid_binding_type_rejected() -> None:
    with pytest.raises(ValueError, match="binding_type"):
        WebhookSubscription(
            skill_name="x",
            binding_type="magic",  # type: ignore[arg-type]
        )


def test_rate_limit_must_be_positive() -> None:
    with pytest.raises(ValueError, match="rate_limit"):
        WebhookSubscription(
            skill_name="x",
            auth_secret="s",
            rate_limit_per_minute=0,
        )


# ---- store CRUD ----------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> WebhookStore:
    return WebhookStore(tmp_path / "webhooks.db")


def _make_sub(**overrides) -> WebhookSubscription:
    base = dict(skill_name="echo", auth_secret="s3cret")
    base.update(overrides)
    return WebhookSubscription(**base)


def test_add_and_get(store: WebhookStore) -> None:
    sub = _make_sub(description="echoes payload")
    store.add(sub)
    loaded = store.get(sub.id)
    assert loaded is not None
    assert loaded.id == sub.id
    assert loaded.description == "echoes payload"
    assert loaded.skill_name == "echo"
    assert loaded.auth_secret == "s3cret"


def test_get_unknown_returns_none(store: WebhookStore) -> None:
    assert store.get("never-existed") is None


def test_list_sorted_by_created_at(store: WebhookStore) -> None:
    """Successive adds should land in chronological order."""
    a = _make_sub(description="first")
    store.add(a)
    b = _make_sub(description="second")
    store.add(b)
    rows = store.list()
    assert len(rows) == 2
    assert rows[0].description == "first"
    assert rows[1].description == "second"


def test_list_empty(store: WebhookStore) -> None:
    assert store.list() == []


def test_update_persists_changes(store: WebhookStore) -> None:
    sub = _make_sub()
    store.add(sub)
    sub.description = "renamed"
    sub.rate_limit_per_minute = 30
    sub.enabled = False
    assert store.update(sub) is True
    loaded = store.get(sub.id)
    assert loaded.description == "renamed"
    assert loaded.rate_limit_per_minute == 30
    assert loaded.enabled is False


def test_update_missing_returns_false(store: WebhookStore) -> None:
    sub = _make_sub()
    # Not added to the store.
    assert store.update(sub) is False


def test_delete_removes_row(store: WebhookStore) -> None:
    sub = _make_sub()
    store.add(sub)
    assert store.delete(sub.id) is True
    assert store.get(sub.id) is None


def test_delete_missing_returns_false(store: WebhookStore) -> None:
    assert store.delete("ghost") is False


def test_set_enabled_toggles(store: WebhookStore) -> None:
    sub = _make_sub()
    store.add(sub)
    assert store.set_enabled(sub.id, False) is True
    assert store.get(sub.id).enabled is False
    assert store.set_enabled(sub.id, True) is True
    assert store.get(sub.id).enabled is True


def test_set_enabled_missing_returns_false(store: WebhookStore) -> None:
    assert store.set_enabled("ghost", False) is False


# ---- record_fire -------------------------------------------------


def test_record_fire_increments_count_and_timestamp(
    store: WebhookStore,
) -> None:
    sub = _make_sub()
    store.add(sub)
    assert store.get(sub.id).fire_count == 0
    assert store.get(sub.id).last_fired_at is None

    store.record_fire(sub.id)
    loaded = store.get(sub.id)
    assert loaded.fire_count == 1
    assert loaded.last_fired_at is not None

    store.record_fire(sub.id)
    assert store.get(sub.id).fire_count == 2


def test_record_fire_missing_id_is_silent(store: WebhookStore) -> None:
    """Recording a fire for an unknown id mustn't crash — webhooks
    are async; a delete between auth-check and dispatch could leave
    record_fire pointing at a stale id."""
    store.record_fire("ghost")  # no exception


# ---- persistence across instances -------------------------------


def test_store_persists_across_instances(tmp_path: Path) -> None:
    """A reopened store sees previously-added rows. Important for
    daemon restarts not losing webhook config."""
    db = tmp_path / "webhooks.db"
    s1 = WebhookStore(db)
    sub = _make_sub(description="persistent")
    s1.add(sub)
    s1.close()

    s2 = WebhookStore(db)
    assert s2.get(sub.id) is not None
    assert s2.get(sub.id).description == "persistent"


# ---- bookkeeping fields round-trip ---------------------------------


def test_fire_count_persists(tmp_path: Path) -> None:
    db = tmp_path / "webhooks.db"
    s1 = WebhookStore(db)
    sub = _make_sub()
    s1.add(sub)
    for _ in range(3):
        s1.record_fire(sub.id)
    s1.close()
    s2 = WebhookStore(db)
    assert s2.get(sub.id).fire_count == 3
