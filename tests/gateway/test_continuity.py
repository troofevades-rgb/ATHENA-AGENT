"""ContinuityManager — bulk cross-platform user linking.

The per-row primitives (link_user, _canonical_user) live on
SessionRouter; ContinuityManager adds bulk-operation helpers used by
the CLI. These tests cover the bulk paths and the route-resolution
interaction.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from athena.gateway.continuity import ContinuityManager
from athena.gateway.events import MessageEvent
from athena.gateway.router import SessionRouter
from athena.sessions.store import SessionStore


def _router(tmp_path: Path, *, continuity: bool = False) -> SessionRouter:
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    store = SessionStore(profile_dir)
    return SessionRouter(
        profile_dir,
        store,
        profile="default",
        model="parent-model",
        provider="ollama",
        continuity=continuity,
    )


def _evt(platform: str, user_id: str, chat_id: str = "c-1") -> MessageEvent:
    return MessageEvent(
        platform=platform,
        chat_id=chat_id,
        user_id=user_id,
        text="hi",
    )


# ---- link_canonical ---------------------------------------------------


def test_link_canonical_binds_multiple_platforms_at_once(tmp_path: Path) -> None:
    router = _router(tmp_path)
    cm = ContinuityManager(router)
    cm.link_canonical(
        "alice@home",
        {
            "telegram": "tg-alice",
            "slack": "sl-alice",
            "discord": "dc-alice",
        },
    )
    assert cm.canonical_for("telegram", "tg-alice") == "alice@home"
    assert cm.canonical_for("slack", "sl-alice") == "alice@home"
    assert cm.canonical_for("discord", "dc-alice") == "alice@home"


def test_link_canonical_empty_platform_dict_is_noop(tmp_path: Path) -> None:
    cm = ContinuityManager(_router(tmp_path))
    cm.link_canonical("alice", {})
    assert cm.list_canonical_users() == []


def test_link_canonical_rejects_empty_canonical_id(tmp_path: Path) -> None:
    cm = ContinuityManager(_router(tmp_path))
    with pytest.raises(ValueError):
        cm.link_canonical("", {"telegram": "tg-x"})


def test_link_canonical_idempotent_on_repeat(tmp_path: Path) -> None:
    cm = ContinuityManager(_router(tmp_path))
    cm.link_canonical("alice", {"telegram": "tg-1"})
    cm.link_canonical("alice", {"telegram": "tg-1"})  # same bindings again
    assert cm.platforms_for("alice") == [("telegram", "tg-1")]


def test_link_canonical_overwrites_prior_canonical_binding(tmp_path: Path) -> None:
    cm = ContinuityManager(_router(tmp_path))
    cm.link_canonical("alice", {"telegram": "tg-1"})
    # Bob takes over tg-1.
    cm.link_canonical("bob", {"telegram": "tg-1"})
    assert cm.canonical_for("telegram", "tg-1") == "bob"
    # alice no longer has any bindings.
    assert cm.platforms_for("alice") == []


# ---- unlink_canonical -----------------------------------------------


def test_unlink_canonical_drops_all_bindings(tmp_path: Path) -> None:
    cm = ContinuityManager(_router(tmp_path))
    cm.link_canonical("alice", {"telegram": "t", "slack": "s"})
    assert cm.unlink_canonical("alice") == 2
    assert cm.platforms_for("alice") == []


def test_unlink_canonical_returns_zero_when_no_bindings(tmp_path: Path) -> None:
    cm = ContinuityManager(_router(tmp_path))
    assert cm.unlink_canonical("never-existed") == 0


def test_unlink_canonical_ignores_empty_id(tmp_path: Path) -> None:
    cm = ContinuityManager(_router(tmp_path))
    cm.link_canonical("alice", {"telegram": "t"})
    assert cm.unlink_canonical("") == 0
    assert cm.platforms_for("alice") == [("telegram", "t")]


# ---- inspection -----------------------------------------------------


def test_platforms_for_returns_sorted_pairs(tmp_path: Path) -> None:
    cm = ContinuityManager(_router(tmp_path))
    cm.link_canonical(
        "alice",
        {
            "telegram": "tg-2",
            "slack": "sl-1",
            "discord": "dc-1",
        },
    )
    cm.link_canonical("alice", {"telegram": "tg-1"})  # add another telegram id
    pairs = cm.platforms_for("alice")
    # Sorted by platform asc, then platform_user_id asc.
    assert pairs == [
        ("discord", "dc-1"),
        ("slack", "sl-1"),
        ("telegram", "tg-1"),
        ("telegram", "tg-2"),
    ]


def test_list_canonical_users_returns_distinct_sorted(tmp_path: Path) -> None:
    cm = ContinuityManager(_router(tmp_path))
    cm.link_canonical("zara", {"slack": "z1"})
    cm.link_canonical("alice", {"telegram": "a1"})
    cm.link_canonical("alice", {"slack": "a2"})
    assert cm.list_canonical_users() == ["alice", "zara"]


# ---- end-to-end interaction with routing ----------------------------


async def test_linking_via_continuity_makes_router_share_session(
    tmp_path: Path,
) -> None:
    router = _router(tmp_path, continuity=True)
    cm = ContinuityManager(router)
    cm.link_canonical("alice", {"telegram": "tg-a", "slack": "sl-a"})

    sid_tg = await router.resolve(_evt("telegram", "tg-a"))
    sid_sl = await router.resolve(_evt("slack", "sl-a"))
    assert sid_tg == sid_sl


async def test_unlinking_breaks_shared_session_for_future_routes(
    tmp_path: Path,
) -> None:
    router = _router(tmp_path, continuity=True)
    cm = ContinuityManager(router)
    cm.link_canonical("alice", {"telegram": "tg-a", "slack": "sl-a"})

    sid_tg = await router.resolve(_evt("telegram", "tg-a"))
    cm.unlink_canonical("alice")
    # New slack route, no link, gets a fresh session.
    sid_sl = await router.resolve(_evt("slack", "sl-a"))
    assert sid_sl != sid_tg
