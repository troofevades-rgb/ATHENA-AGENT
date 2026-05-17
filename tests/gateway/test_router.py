"""SessionRouter — sticky per-(platform, chat, user) routing."""
from __future__ import annotations

from pathlib import Path

from athena.gateway.events import MessageEvent
from athena.gateway.router import SessionRouter
from athena.sessions.store import SessionStore


def _evt(
    platform: str = "telegram",
    chat_id: str = "chat-1",
    user_id: str = "user-1",
    text: str = "hi",
) -> MessageEvent:
    return MessageEvent(
        platform=platform, chat_id=chat_id, user_id=user_id, text=text,
    )


def _router(tmp_path: Path, *, continuity: bool = False) -> SessionRouter:
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    store = SessionStore(profile_dir)
    return SessionRouter(
        profile_dir, store,
        profile="default",
        model="parent-model",
        provider="ollama",
        continuity=continuity,
    )


# ---- first-message creation -------------------------------------------


async def test_first_inbound_creates_session(tmp_path: Path) -> None:
    r = _router(tmp_path)
    sid = await r.resolve(_evt())
    assert sid
    routes = r.list_routes()
    assert len(routes) == 1
    assert routes[0].platform == "telegram"
    assert routes[0].session_id == sid


async def test_subsequent_inbound_reuses_session(tmp_path: Path) -> None:
    r = _router(tmp_path)
    sid1 = await r.resolve(_evt())
    sid2 = await r.resolve(_evt())
    assert sid1 == sid2


async def test_different_chat_creates_different_session(tmp_path: Path) -> None:
    r = _router(tmp_path)
    sid1 = await r.resolve(_evt(chat_id="chat-A"))
    sid2 = await r.resolve(_evt(chat_id="chat-B"))
    assert sid1 != sid2


async def test_different_user_creates_different_session(tmp_path: Path) -> None:
    r = _router(tmp_path)
    sid1 = await r.resolve(_evt(user_id="alice"))
    sid2 = await r.resolve(_evt(user_id="bob"))
    assert sid1 != sid2


async def test_different_platform_creates_different_session(tmp_path: Path) -> None:
    r = _router(tmp_path)
    sid1 = await r.resolve(_evt(platform="telegram"))
    sid2 = await r.resolve(_evt(platform="slack"))
    assert sid1 != sid2


# ---- persistence ------------------------------------------------------


async def test_route_persists_across_router_instances(tmp_path: Path) -> None:
    """Daemon restart simulation: a fresh SessionRouter on the same
    profile_dir must see the route. SessionStore must also see the
    minted session — both halves of persistence."""
    r1 = _router(tmp_path)
    sid = await r1.resolve(_evt(chat_id="persist-chat"))
    r1.close()

    profile_dir = tmp_path / "profile"
    store2 = SessionStore(profile_dir)
    r2 = SessionRouter(
        profile_dir, store2,
        profile="default",
        model="parent-model",
        provider="ollama",
    )
    sid2 = await r2.resolve(_evt(chat_id="persist-chat"))
    assert sid2 == sid


async def test_last_seen_at_bumps_on_reuse(tmp_path: Path) -> None:
    r = _router(tmp_path)
    await r.resolve(_evt())
    routes = r.list_routes()
    first_seen = routes[0].last_seen_at
    # Reuse the route — last_seen_at must advance.
    await r.resolve(_evt())
    routes2 = r.list_routes()
    assert routes2[0].last_seen_at >= first_seen


# ---- continuity -------------------------------------------------------


async def test_continuity_disabled_keeps_users_isolated(tmp_path: Path) -> None:
    r = _router(tmp_path, continuity=False)
    r.link_user("alice@home", "telegram", "tg-alice")
    r.link_user("alice@home", "slack", "sl-alice")
    sid_tg = await r.resolve(_evt(platform="telegram", user_id="tg-alice"))
    sid_sl = await r.resolve(_evt(platform="slack", user_id="sl-alice"))
    assert sid_tg != sid_sl


async def test_continuity_enabled_links_users_across_platforms(
    tmp_path: Path,
) -> None:
    r = _router(tmp_path, continuity=True)
    r.link_user("alice@home", "telegram", "tg-alice")
    r.link_user("alice@home", "slack", "sl-alice")

    sid_tg = await r.resolve(_evt(platform="telegram", user_id="tg-alice"))
    sid_sl = await r.resolve(_evt(platform="slack", user_id="sl-alice"))
    assert sid_tg == sid_sl


async def test_continuity_falls_back_to_new_session_when_no_link(
    tmp_path: Path,
) -> None:
    r = _router(tmp_path, continuity=True)
    sid = await r.resolve(_evt(user_id="unlinked"))
    assert sid  # mints a fresh session normally


# ---- linking management ------------------------------------------------


async def test_link_user_idempotent(tmp_path: Path) -> None:
    r = _router(tmp_path)
    r.link_user("alice", "telegram", "tg-1")
    r.link_user("alice", "telegram", "tg-1")  # second call must not raise
    assert r._canonical_user("telegram", "tg-1") == "alice"


async def test_link_user_overwrites_canonical_binding(tmp_path: Path) -> None:
    r = _router(tmp_path)
    r.link_user("alice", "telegram", "tg-1")
    r.link_user("bob", "telegram", "tg-1")
    assert r._canonical_user("telegram", "tg-1") == "bob"


async def test_unlink_user_removes_binding(tmp_path: Path) -> None:
    r = _router(tmp_path)
    r.link_user("alice", "telegram", "tg-1")
    assert r.unlink_user("telegram", "tg-1") is True
    assert r._canonical_user("telegram", "tg-1") is None


async def test_unlink_user_returns_false_when_no_row(tmp_path: Path) -> None:
    r = _router(tmp_path)
    assert r.unlink_user("telegram", "missing") is False


# ---- listing + removal ------------------------------------------------


async def test_list_routes_filters_by_platform(tmp_path: Path) -> None:
    r = _router(tmp_path)
    await r.resolve(_evt(platform="telegram", chat_id="c1"))
    await r.resolve(_evt(platform="slack", chat_id="c1"))
    await r.resolve(_evt(platform="telegram", chat_id="c2"))
    tg = r.list_routes(platform="telegram")
    sl = r.list_routes(platform="slack")
    assert len(tg) == 2
    assert len(sl) == 1


async def test_remove_route_deletes_row(tmp_path: Path) -> None:
    r = _router(tmp_path)
    await r.resolve(_evt())
    assert r.remove_route("telegram", "chat-1", "user-1") is True
    assert r.list_routes() == []


async def test_remove_route_returns_false_when_no_row(tmp_path: Path) -> None:
    r = _router(tmp_path)
    assert r.remove_route("telegram", "nope", "nope") is False


# ---- concurrency ------------------------------------------------------


async def test_concurrent_resolves_same_chat_yield_same_session(
    tmp_path: Path,
) -> None:
    """Two events arriving on the same tick must both end up bound to
    one session, not two. The router's asyncio.Lock makes this safe."""
    import asyncio

    r = _router(tmp_path)
    sids = await asyncio.gather(
        r.resolve(_evt(chat_id="race")),
        r.resolve(_evt(chat_id="race")),
        r.resolve(_evt(chat_id="race")),
    )
    assert sids[0] == sids[1] == sids[2]
    assert len(r.list_routes()) == 1
