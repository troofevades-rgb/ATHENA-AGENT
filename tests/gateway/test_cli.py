"""``athena gateway`` CLI subcommands.

Run, link, unlink, routes, canonical-users. The ``run`` command's
deeper end-to-end behavior is exercised by tests/gateway/test_daemon
— here we verify the CLI dispatch and the no-platforms early-exit.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from athena.cli import gateway as cli
from athena.config import Config, GatewayConfig


@pytest.fixture
def isolated_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Redirect profile_dir() to land under tmp_path."""
    from athena import config as cfg_mod

    def fake_profile_dir(name: str = "default", home: Path | None = None) -> Path:
        return tmp_path / "athena_home" / name

    monkeypatch.setattr(cfg_mod, "profile_dir", fake_profile_dir)
    monkeypatch.setattr(cli, "profile_dir", fake_profile_dir)
    return tmp_path / "athena_home"


@pytest.fixture
def cfg_for_cli(monkeypatch: pytest.MonkeyPatch) -> Config:
    cfg = Config(profile="testprofile")
    cfg.gateway = GatewayConfig()
    monkeypatch.setattr(cli, "load_config", lambda: cfg)
    return cfg


# ---- run: no platforms configured ------------------------------------


def test_run_no_platforms_configured_exits_2(
    isolated_profile: Path,
    cfg_for_cli: Config,
    capsys: pytest.CaptureFixture,
) -> None:
    rc = cli.main(["run"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "no gateway platforms" in err


# ---- routes ----------------------------------------------------------


def test_routes_empty_lists_none(
    isolated_profile: Path,
    cfg_for_cli: Config,
    capsys: pytest.CaptureFixture,
) -> None:
    rc = cli.main(["routes"])
    assert rc == 0
    assert "(no routes)" in capsys.readouterr().out


def test_routes_after_link_and_resolve(
    isolated_profile: Path,
    cfg_for_cli: Config,
    capsys: pytest.CaptureFixture,
) -> None:
    """Link a canonical user, then verify list_routes returns rows
    after a resolve. We synthesize the resolve via the router
    directly to avoid spinning the daemon."""
    import asyncio

    from athena.gateway.events import MessageEvent
    from athena.gateway.router import SessionRouter
    from athena.sessions.store import SessionStore

    profile_dir = isolated_profile / cfg_for_cli.profile
    profile_dir.mkdir(parents=True, exist_ok=True)
    store = SessionStore(profile_dir)
    router = SessionRouter(
        profile_dir,
        store,
        profile=cfg_for_cli.profile,
        model="m",
        provider="ollama",
    )
    asyncio.run(
        router.resolve(
            MessageEvent(
                platform="telegram",
                chat_id="C1",
                user_id="U1",
                text="hi",
            )
        )
    )
    router.close()

    rc = cli.main(["routes"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "telegram" in out
    assert "C1" in out
    assert "U1" in out


def test_routes_json_output(
    isolated_profile: Path,
    cfg_for_cli: Config,
    capsys: pytest.CaptureFixture,
) -> None:
    import asyncio
    import json

    from athena.gateway.events import MessageEvent
    from athena.gateway.router import SessionRouter
    from athena.sessions.store import SessionStore

    profile_dir = isolated_profile / cfg_for_cli.profile
    profile_dir.mkdir(parents=True, exist_ok=True)
    store = SessionStore(profile_dir)
    router = SessionRouter(
        profile_dir,
        store,
        profile=cfg_for_cli.profile,
        model="m",
        provider="ollama",
    )
    asyncio.run(
        router.resolve(
            MessageEvent(
                platform="slack",
                chat_id="C-sl",
                user_id="U-sl",
                text="hi",
            )
        )
    )
    router.close()

    rc = cli.main(["routes", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload) == 1
    assert payload[0]["platform"] == "slack"


def test_routes_filter_by_platform(
    isolated_profile: Path,
    cfg_for_cli: Config,
    capsys: pytest.CaptureFixture,
) -> None:
    import asyncio

    from athena.gateway.events import MessageEvent
    from athena.gateway.router import SessionRouter
    from athena.sessions.store import SessionStore

    profile_dir = isolated_profile / cfg_for_cli.profile
    profile_dir.mkdir(parents=True, exist_ok=True)
    store = SessionStore(profile_dir)
    router = SessionRouter(
        profile_dir,
        store,
        profile=cfg_for_cli.profile,
        model="m",
        provider="ollama",
    )
    asyncio.run(
        router.resolve(
            MessageEvent(
                platform="telegram",
                chat_id="C-t",
                user_id="U-t",
                text="hi",
            )
        )
    )
    asyncio.run(
        router.resolve(
            MessageEvent(
                platform="slack",
                chat_id="C-s",
                user_id="U-s",
                text="hi",
            )
        )
    )
    router.close()

    rc = cli.main(["routes", "--platform", "telegram"])
    out = capsys.readouterr().out
    assert "C-t" in out
    assert "C-s" not in out


# ---- link / unlink ----------------------------------------------------


def test_link_requires_at_least_one_platform(
    isolated_profile: Path,
    cfg_for_cli: Config,
    capsys: pytest.CaptureFixture,
) -> None:
    rc = cli.main(["link", "--canonical", "alice"])
    assert rc == 2
    assert "at least one of" in capsys.readouterr().err


def test_link_persists_bindings(
    isolated_profile: Path,
    cfg_for_cli: Config,
    capsys: pytest.CaptureFixture,
) -> None:
    rc = cli.main(
        [
            "link",
            "--canonical",
            "alice",
            "--telegram",
            "tg-1",
            "--slack",
            "U-x",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "telegram: tg-1" in out
    assert "slack: U-x" in out

    # canonical-users round-trip
    rc = cli.main(["canonical-users"])
    out = capsys.readouterr().out
    assert "alice" in out
    assert "telegram=tg-1" in out
    assert "slack=U-x" in out


def test_unlink_removes_bindings(
    isolated_profile: Path,
    cfg_for_cli: Config,
    capsys: pytest.CaptureFixture,
) -> None:
    cli.main(
        [
            "link",
            "--canonical",
            "bob",
            "--discord",
            "D-1",
        ]
    )
    capsys.readouterr()  # drain
    rc = cli.main(["unlink", "--canonical", "bob"])
    assert rc == 0
    assert "1 bindings" in capsys.readouterr().out


def test_unlink_missing_user_returns_zero(
    isolated_profile: Path,
    cfg_for_cli: Config,
    capsys: pytest.CaptureFixture,
) -> None:
    rc = cli.main(["unlink", "--canonical", "ghost"])
    assert rc == 0
    assert "no bindings" in capsys.readouterr().out


def test_canonical_users_empty(
    isolated_profile: Path,
    cfg_for_cli: Config,
    capsys: pytest.CaptureFixture,
) -> None:
    rc = cli.main(["canonical-users"])
    assert rc == 0
    assert "(no canonical users)" in capsys.readouterr().out


# ---- _build_adapters: platform config validation ---------------------


def test_build_adapters_no_platforms(
    isolated_profile: Path,
) -> None:
    """Empty config → empty list, no exceptions."""
    from athena.gateway.daemon import GatewayDaemon

    cfg = Config(profile="t")
    cfg.gateway = GatewayConfig(platforms={})
    daemon = GatewayDaemon(cfg)
    assert cli._build_adapters(daemon, cfg) == []


def test_build_adapters_skips_disabled(
    isolated_profile: Path,
) -> None:
    from athena.gateway.daemon import GatewayDaemon

    cfg = Config(profile="t")
    cfg.gateway = GatewayConfig(
        platforms={
            "telegram": {"bot_token": "t", "enabled": False},
        }
    )
    daemon = GatewayDaemon(cfg)
    assert cli._build_adapters(daemon, cfg) == []


def test_build_adapters_telegram_requires_token(
    isolated_profile: Path,
) -> None:
    from athena.gateway.daemon import GatewayDaemon

    cfg = Config(profile="t")
    cfg.gateway = GatewayConfig(
        platforms={
            "telegram": {"bot_token": ""},
        }
    )
    daemon = GatewayDaemon(cfg)
    assert cli._build_adapters(daemon, cfg) == []


def test_build_adapters_telegram_registers(
    isolated_profile: Path,
) -> None:
    from athena.gateway.daemon import GatewayDaemon

    cfg = Config(profile="t")
    cfg.gateway = GatewayConfig(
        platforms={
            "telegram": {"bot_token": "real-token"},
        }
    )
    daemon = GatewayDaemon(cfg)
    registered = cli._build_adapters(daemon, cfg)
    assert registered == ["telegram"]
    assert daemon.adapters[0].name == "telegram"


def test_build_adapters_slack_requires_both_tokens(
    isolated_profile: Path,
) -> None:
    from athena.gateway.daemon import GatewayDaemon

    cfg = Config(profile="t")
    cfg.gateway = GatewayConfig(
        platforms={
            "slack": {"bot_token": "xoxb-t"},  # missing app_token
        }
    )
    daemon = GatewayDaemon(cfg)
    assert cli._build_adapters(daemon, cfg) == []


def test_build_adapters_slack_registers(
    isolated_profile: Path,
) -> None:
    from athena.gateway.daemon import GatewayDaemon

    cfg = Config(profile="t")
    cfg.gateway = GatewayConfig(
        platforms={
            "slack": {"bot_token": "xoxb-t", "app_token": "xapp-t"},
        }
    )
    daemon = GatewayDaemon(cfg)
    assert cli._build_adapters(daemon, cfg) == ["slack"]


def test_build_adapters_unknown_platform_skipped(
    isolated_profile: Path,
) -> None:
    from athena.gateway.daemon import GatewayDaemon

    cfg = Config(profile="t")
    cfg.gateway = GatewayConfig(
        platforms={
            "irc": {"bot_token": "x"},
        }
    )
    daemon = GatewayDaemon(cfg)
    assert cli._build_adapters(daemon, cfg) == []


# ---- Phase 11 platform wiring ----------------------------------------


def test_build_adapters_signal_requires_both_keys(
    isolated_profile: Path,
) -> None:
    from athena.gateway.daemon import GatewayDaemon

    cfg = Config(profile="t")
    cfg.gateway = GatewayConfig(
        platforms={
            "signal": {"rest_url": "http://x"},  # missing account_number
        }
    )
    daemon = GatewayDaemon(cfg)
    assert cli._build_adapters(daemon, cfg) == []


def test_build_adapters_signal_registers(isolated_profile: Path) -> None:
    from athena.gateway.daemon import GatewayDaemon

    cfg = Config(profile="t")
    cfg.gateway = GatewayConfig(
        platforms={
            "signal": {
                "rest_url": "http://localhost:8080",
                "account_number": "+15555550100",
            },
        }
    )
    daemon = GatewayDaemon(cfg)
    assert cli._build_adapters(daemon, cfg) == ["signal"]
    assert daemon.adapters[0].name == "signal"


def test_build_adapters_imessage_registers(isolated_profile: Path) -> None:
    from athena.gateway.daemon import GatewayDaemon

    cfg = Config(profile="t")
    cfg.gateway = GatewayConfig(
        platforms={
            "imessage": {
                "server_url": "https://bb.example.com",
                "password": "secret",
            },
        }
    )
    daemon = GatewayDaemon(cfg)
    assert cli._build_adapters(daemon, cfg) == ["imessage"]


def test_build_adapters_imessage_missing_password(
    isolated_profile: Path,
) -> None:
    from athena.gateway.daemon import GatewayDaemon

    cfg = Config(profile="t")
    cfg.gateway = GatewayConfig(
        platforms={
            "imessage": {"server_url": "https://x"},
        }
    )
    daemon = GatewayDaemon(cfg)
    assert cli._build_adapters(daemon, cfg) == []


def test_build_adapters_matrix_registers(isolated_profile: Path) -> None:
    from athena.gateway.daemon import GatewayDaemon

    cfg = Config(profile="t")
    cfg.gateway = GatewayConfig(
        platforms={
            "matrix": {
                "homeserver": "https://matrix.example.org",
                "user_id": "@bot:example.org",
                "access_token": "syt_TOKEN",
                "device_id": "DEV1",
            },
        }
    )
    daemon = GatewayDaemon(cfg)
    assert cli._build_adapters(daemon, cfg) == ["matrix"]


def test_build_adapters_matrix_missing_user_id(
    isolated_profile: Path,
) -> None:
    from athena.gateway.daemon import GatewayDaemon

    cfg = Config(profile="t")
    cfg.gateway = GatewayConfig(
        platforms={
            "matrix": {
                "homeserver": "https://matrix.example.org",
                "access_token": "t",
                "device_id": "D",
                # missing user_id
            },
        }
    )
    daemon = GatewayDaemon(cfg)
    assert cli._build_adapters(daemon, cfg) == []


def test_build_adapters_email_registers(isolated_profile: Path) -> None:
    from athena.gateway.daemon import GatewayDaemon

    cfg = Config(profile="t")
    cfg.gateway = GatewayConfig(
        platforms={
            "email": {
                "imap_host": "imap.example.com",
                "imap_user": "bot@example.com",
                "imap_password": "pw",
                "smtp_host": "smtp.example.com",
                "smtp_user": "bot@example.com",
                "smtp_password": "pw",
                "from_address": "bot@example.com",
            },
        }
    )
    daemon = GatewayDaemon(cfg)
    assert cli._build_adapters(daemon, cfg) == ["email"]


def test_build_adapters_email_missing_smtp_password(
    isolated_profile: Path,
) -> None:
    from athena.gateway.daemon import GatewayDaemon

    cfg = Config(profile="t")
    cfg.gateway = GatewayConfig(
        platforms={
            "email": {
                "imap_host": "i",
                "imap_user": "u",
                "imap_password": "p",
                "smtp_host": "s",
                "smtp_user": "u",
                # missing smtp_password
                "from_address": "f@x",
            },
        }
    )
    daemon = GatewayDaemon(cfg)
    assert cli._build_adapters(daemon, cfg) == []


def test_build_adapters_email_accepts_allowed_senders(
    isolated_profile: Path,
) -> None:
    from athena.gateway.daemon import GatewayDaemon

    cfg = Config(profile="t")
    cfg.gateway = GatewayConfig(
        platforms={
            "email": {
                "imap_host": "i",
                "imap_user": "u",
                "imap_password": "p",
                "smtp_host": "s",
                "smtp_user": "u",
                "smtp_password": "p",
                "from_address": "f@x",
                "allowed_senders": ["alice@x", "bob@x"],
            },
        }
    )
    daemon = GatewayDaemon(cfg)
    assert cli._build_adapters(daemon, cfg) == ["email"]
    adapter = daemon.adapters[0]
    assert adapter.allowed_senders == {"alice@x", "bob@x"}


def test_build_adapters_seven_platforms_together(
    isolated_profile: Path,
) -> None:
    """Smoke test the full menu wires up in one daemon."""
    from athena.gateway.daemon import GatewayDaemon

    cfg = Config(profile="t")
    cfg.gateway = GatewayConfig(
        platforms={
            "telegram": {"bot_token": "t1"},
            "slack": {"bot_token": "xoxb-x", "app_token": "xapp-x"},
            "discord": {"bot_token": "d"},
            "signal": {"rest_url": "http://x", "account_number": "+1"},
            "imessage": {"server_url": "http://x", "password": "p"},
            "matrix": {
                "homeserver": "https://x",
                "user_id": "@b:x",
                "access_token": "t",
                "device_id": "D",
            },
            "email": {
                "imap_host": "i",
                "imap_user": "u",
                "imap_password": "p",
                "smtp_host": "s",
                "smtp_user": "u",
                "smtp_password": "p",
                "from_address": "f@x",
            },
        }
    )
    daemon = GatewayDaemon(cfg)
    registered = cli._build_adapters(daemon, cfg)
    assert set(registered) == {
        "telegram",
        "slack",
        "discord",
        "signal",
        "imessage",
        "matrix",
        "email",
    }
