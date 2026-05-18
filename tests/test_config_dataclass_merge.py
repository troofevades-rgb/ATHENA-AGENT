"""TOML → Config field merging.

A nested TOML table like ``[gateway.platforms.telegram]`` arrives as a
plain dict; without ``_assign_field`` it would silently overwrite the
``Config.gateway`` dataclass and downstream code that expects
``cfg.gateway.continuity`` blows up with AttributeError. Verify
nested merge keeps the dataclass intact.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from athena import config as cfg_mod


def _write_config(home: Path, body: str) -> None:
    body = textwrap.dedent(body).lstrip()
    (home / ".athena").mkdir(parents=True, exist_ok=True)
    (home / ".athena" / "config.toml").write_text(body, encoding="utf-8")


@pytest.fixture
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect CONFIG_DIR to a tmp_path so load_config reads our test
    file, not the developer's real ~/.athena/config.toml."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", home / ".athena")
    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", home / ".athena" / "config.toml")
    monkeypatch.setattr(cfg_mod, "SESSIONS_DIR", home / ".athena" / "sessions")
    return home


def test_gateway_table_merges_into_dataclass(isolated_config: Path) -> None:
    _write_config(isolated_config, """
        [gateway.platforms.telegram]
        enabled = true
        bot_token = "redacted-test-token"
    """)
    cfg = cfg_mod.load_config()
    # gateway remains a GatewayConfig — not overwritten with a raw dict.
    assert isinstance(cfg.gateway, cfg_mod.GatewayConfig)
    # Default fields preserved.
    assert cfg.gateway.continuity is False
    assert cfg.gateway.max_warm_agents == 50
    # Nested platform table parsed into the platforms dict.
    assert "telegram" in cfg.gateway.platforms
    assert cfg.gateway.platforms["telegram"]["enabled"] is True


def test_gateway_partial_override_keeps_defaults(isolated_config: Path) -> None:
    _write_config(isolated_config, """
        [gateway]
        continuity = true
    """)
    cfg = cfg_mod.load_config()
    assert cfg.gateway.continuity is True
    # max_warm_agents was not specified — must still be the default.
    assert cfg.gateway.max_warm_agents == 50


def test_review_table_also_merges_into_dataclass(isolated_config: Path) -> None:
    """ReviewConfig follows the same pattern as GatewayConfig."""
    _write_config(isolated_config, """
        [review]
        disabled = true
        nudge_interval = 25
    """)
    cfg = cfg_mod.load_config()
    assert isinstance(cfg.review, cfg_mod.ReviewConfig)
    assert cfg.review.disabled is True
    assert cfg.review.nudge_interval == 25
    # Field not specified retains default.
    assert cfg.review.max_iterations == 8


def test_unknown_keys_are_ignored(isolated_config: Path) -> None:
    """Stray entries don't blow up."""
    _write_config(isolated_config, """
        unknown_top_level = "yo"
        [gateway]
        continuity = true
    """)
    cfg = cfg_mod.load_config()
    assert cfg.gateway.continuity is True
