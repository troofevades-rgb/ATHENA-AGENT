"""GatewayDaemon — wires router, pool, adapters, command dispatch."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from athena.config import Config, GatewayConfig
from athena.gateway.base import GatewayAdapter
from athena.gateway.daemon import GatewayDaemon
from athena.gateway.events import MessageEvent


class _NoopAdapter(GatewayAdapter):
    """Records start/stop calls; trivially satisfies the ABC."""

    def __init__(self, daemon: GatewayDaemon, *, name: str = "noop") -> None:
        self.name = name
        super().__init__(daemon)
        self.started = False
        self.stopped = False
        self.stop_delay = 0.0

    async def start(self) -> None:
        self.started = True
        # Mimic a polling loop: park until cancelled or stop() runs.
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            raise

    async def stop(self) -> None:
        if self.stop_delay:
            await asyncio.sleep(self.stop_delay)
        self.stopped = True

    async def send_text(self, chat_id: str, text: str) -> str:
        return "msg-1"

    async def send_file(
        self, chat_id: str, file_path: Path, caption: str | None = None
    ) -> str:
        return "msg-1"


def _cfg(tmp_path: Path, *, max_warm: int = 50) -> Config:
    profile = "tdaemon"
    cfg = Config(profile=profile)
    cfg.gateway = GatewayConfig(max_warm_agents=max_warm)
    return cfg


@pytest.fixture
def isolated_cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    """Point ATHENA home at tmp so SessionStore writes don't escape."""
    monkeypatch.setenv("ATHENA_HOME", str(tmp_path / "athena_home"))
    # Force config module to re-resolve home — it caches via module-level
    # CONFIG_DIR. The simplest path: monkeypatch profile_dir resolution
    # to land in tmp_path regardless.
    from athena import config as cfg_mod

    def fake_profile_dir(name: str = "default", home: Path | None = None) -> Path:
        return tmp_path / "athena_home" / "profiles" / name

    monkeypatch.setattr(cfg_mod, "profile_dir", fake_profile_dir)
    from athena.gateway import daemon as daemon_mod
    monkeypatch.setattr(daemon_mod, "profile_dir", fake_profile_dir)
    return _cfg(tmp_path)


# ---- construction -----------------------------------------------------


def test_daemon_constructs_router_pool_store(isolated_cfg: Config) -> None:
    daemon = GatewayDaemon(isolated_cfg)
    assert daemon.router is not None
    assert daemon.pool is not None
    assert daemon.session_store is not None
    assert daemon.adapters == []


def test_daemon_pool_respects_max_warm_agents_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATHENA_HOME", str(tmp_path))
    from athena import config as cfg_mod
    from athena.gateway import daemon as daemon_mod

    def fake_profile_dir(name: str = "default", home: Path | None = None) -> Path:
        return tmp_path / "p" / name

    monkeypatch.setattr(cfg_mod, "profile_dir", fake_profile_dir)
    monkeypatch.setattr(daemon_mod, "profile_dir", fake_profile_dir)
    cfg = _cfg(tmp_path, max_warm=7)
    daemon = GatewayDaemon(cfg)
    assert daemon.pool.max_size == 7


# ---- adapter registration --------------------------------------------


async def test_register_adds_adapter(isolated_cfg: Config) -> None:
    daemon = GatewayDaemon(isolated_cfg)
    adapter = _NoopAdapter(daemon)
    daemon.register(adapter)
    assert daemon.adapters == [adapter]


async def test_register_after_start_raises(isolated_cfg: Config) -> None:
    daemon = GatewayDaemon(isolated_cfg)
    adapter = _NoopAdapter(daemon)
    daemon.register(adapter)
    await daemon.start()
    try:
        with pytest.raises(RuntimeError):
            daemon.register(_NoopAdapter(daemon, name="late"))
    finally:
        await daemon.stop()


# ---- start / stop -----------------------------------------------------


async def test_start_kicks_adapter_start_as_task(isolated_cfg: Config) -> None:
    daemon = GatewayDaemon(isolated_cfg)
    a = _NoopAdapter(daemon)
    daemon.register(a)
    await daemon.start()
    # Give the event loop a tick to run the task.
    await asyncio.sleep(0)
    assert a.started is True
    await daemon.stop()


async def test_stop_calls_each_adapter_stop(isolated_cfg: Config) -> None:
    daemon = GatewayDaemon(isolated_cfg)
    a1 = _NoopAdapter(daemon, name="a1")
    a2 = _NoopAdapter(daemon, name="a2")
    daemon.register(a1)
    daemon.register(a2)
    await daemon.start()
    await daemon.stop()
    assert a1.stopped and a2.stopped


async def test_stop_is_idempotent(isolated_cfg: Config) -> None:
    daemon = GatewayDaemon(isolated_cfg)
    daemon.register(_NoopAdapter(daemon))
    await daemon.start()
    await daemon.stop()
    await daemon.stop()  # second call must not raise


async def test_stop_drains_agent_pool(isolated_cfg: Config) -> None:
    """Stopping the daemon must evict every cached agent so anything
    holding a provider client lets go cleanly."""
    daemon = GatewayDaemon(isolated_cfg)
    daemon.register(_NoopAdapter(daemon))

    # Plug in a factory and pre-warm two sessions.
    closed: list[str] = []

    class _Fake:
        def __init__(self, sid: str) -> None:
            self.session_id = sid

        async def close(self) -> None:
            closed.append(self.session_id)

    async def factory(sid: str):
        return _Fake(sid)

    daemon.pool._factory = factory  # type: ignore[assignment]
    await daemon.pool.get("s1")
    await daemon.pool.get("s2")

    await daemon.start()
    await daemon.stop()
    assert sorted(closed) == ["s1", "s2"]


async def test_stop_bounded_by_timeout_on_wedged_adapter(
    isolated_cfg: Config,
) -> None:
    """If an adapter.stop() never returns, daemon.stop() must still
    complete within ~10s."""
    daemon = GatewayDaemon(isolated_cfg)
    slow = _NoopAdapter(daemon)
    slow.stop_delay = 30.0  # would block much longer than the 10s bound
    daemon.register(slow)
    await daemon.start()

    import time
    start = time.monotonic()
    # The wait_for inside _bounded_stop caps at 10s; for the test we
    # want to confirm the bound exists, not actually wait 10s. We pass
    # an asyncio.wait_for around the whole call so the test caps itself
    # if the bound is missing.
    try:
        await asyncio.wait_for(daemon.stop(), timeout=12.0)
    except asyncio.TimeoutError:  # pragma: no cover
        pytest.fail("daemon.stop() did not honor adapter-stop timeout bound")
    elapsed = time.monotonic() - start
    assert elapsed < 11.5, f"stop() exceeded its bound (elapsed={elapsed:.2f}s)"


# ---- command dispatch ------------------------------------------------


async def test_dispatch_command_default_returns_placeholder(
    isolated_cfg: Config,
) -> None:
    daemon = GatewayDaemon(isolated_cfg)
    event = MessageEvent(
        platform="t", chat_id="c", user_id="u", text="/stop",
    )
    out = await daemon.dispatch_command(event, "sess-1", "stop")
    assert "/stop" in out
    assert "not yet implemented" in out


async def test_dispatch_command_uses_injected_dispatcher(
    isolated_cfg: Config,
) -> None:
    async def fake_dispatch(event, session_id, cmd):
        return f"dispatched:{cmd}:{session_id}"

    daemon = GatewayDaemon(
        isolated_cfg,
        command_dispatcher=fake_dispatch,
    )
    event = MessageEvent(platform="t", chat_id="c", user_id="u", text="/x")
    out = await daemon.dispatch_command(event, "sess-9", "x")
    assert out == "dispatched:x:sess-9"


async def test_dispatch_command_traps_dispatcher_exceptions(
    isolated_cfg: Config,
) -> None:
    async def bad_dispatch(*_a, **_kw):
        raise RuntimeError("boom")

    daemon = GatewayDaemon(isolated_cfg, command_dispatcher=bad_dispatch)
    event = MessageEvent(platform="t", chat_id="c", user_id="u", text="/x")
    out = await daemon.dispatch_command(event, "s", "x")
    assert "failed" in out


# ---- router wiring ---------------------------------------------------


async def test_router_creates_session_for_first_inbound(
    isolated_cfg: Config,
) -> None:
    """End-to-end smoke: an inbound event hitting the daemon's router
    mints a route and a session via the shared SessionStore."""
    daemon = GatewayDaemon(isolated_cfg)
    event = MessageEvent(
        platform="telegram", chat_id="chat-1", user_id="user-1", text="hi",
    )
    session_id = await daemon.router.resolve(event)
    assert session_id
    routes = daemon.router.list_routes()
    assert len(routes) == 1
    assert routes[0].session_id == session_id


# ---- stub factory -----------------------------------------------------


async def test_default_pool_factory_raises_not_implemented(
    isolated_cfg: Config,
) -> None:
    """Phase 10.2's daemon ships a stub factory — touching it before
    Phase 10.8 wires the real one must be loud, not silent."""
    daemon = GatewayDaemon(isolated_cfg)
    with pytest.raises(NotImplementedError):
        await daemon.pool.get("some-session")
