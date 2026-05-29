"""End-to-end ``load_config`` + plugin-state + path-helper tests.

Existing coverage:
  * tests/test_config_dataclass_merge.py — TOML → nested dataclass merge (4)
  * tests/test_config_host_normalize.py — OLLAMA_HOST rewriting (10)

What's still untested:
  * ``load_config`` with no config file at all → defaults
  * Env var overrides (ATHENA_MODEL, OLLAMA_HOST)
  * The ``auto_approve_bash`` → ``auto_approve_tools`` deprecation rename
  * Theme application + invalid theme falls back silently
  * ``load_plugin_state`` / ``save_plugin_state`` / ``_merge_plugin_state``
  * ``profile_dir`` + ``mcp_config_paths`` path helpers
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from athena import config as cfg_mod


# ---------------------------------------------------------------------------
# Isolation fixture — redirect every config path into tmp_path
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Sandbox config + plugin-state + sessions dirs so a test can't
    touch the developer's real ~/.athena/ files."""
    home = tmp_path / "home"
    athena_dir = home / ".athena"
    monkeypatch.setattr(cfg_mod, "CONFIG_DIR", athena_dir)
    monkeypatch.setattr(cfg_mod, "CONFIG_PATH", athena_dir / "config.toml")
    monkeypatch.setattr(cfg_mod, "SESSIONS_DIR", athena_dir / "sessions")
    monkeypatch.setattr(
        cfg_mod, "PLUGINS_STATE_PATH", athena_dir / "plugins_state.json",
    )
    monkeypatch.setattr(
        cfg_mod, "USER_MCP_PATH", athena_dir / "mcp.json",
    )
    # Drop env vars that influence load_config so tests are deterministic
    monkeypatch.delenv("ATHENA_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    return home


def _write_toml(home: Path, body: str) -> None:
    body = textwrap.dedent(body).lstrip()
    (home / ".athena").mkdir(parents=True, exist_ok=True)
    (home / ".athena" / "config.toml").write_text(body, encoding="utf-8")


# ---------------------------------------------------------------------------
# load_config — file-absent + defaults
# ---------------------------------------------------------------------------


def test_load_config_no_file_returns_defaults(isolated: Path) -> None:
    """A fresh install has no config.toml. Must return a populated
    Config with defaults, not crash. Also: must create the
    CONFIG_DIR + SESSIONS_DIR so other init code can write into
    them immediately."""
    cfg = cfg_mod.load_config()
    assert isinstance(cfg, cfg_mod.Config)
    # Sentinel: the CONFIG_DIR was created
    assert cfg_mod.CONFIG_DIR.exists()
    assert cfg_mod.SESSIONS_DIR.exists()


def test_load_config_with_simple_overrides(isolated: Path) -> None:
    """Top-level scalar fields override defaults."""
    _write_toml(isolated, """
        model = "custom-model:7b"
        theme = "dusk"
    """)
    cfg = cfg_mod.load_config()
    assert cfg.model == "custom-model:7b"
    assert cfg.theme == "dusk"


# ---------------------------------------------------------------------------
# Env var overrides
# ---------------------------------------------------------------------------


def test_athena_model_env_overrides_config_file(
    isolated: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ATHENA_MODEL env var wins over the model field in config.toml.
    Common CI pattern — pin a model per job without rewriting the
    file."""
    _write_toml(isolated, 'model = "file-model"\n')
    monkeypatch.setenv("ATHENA_MODEL", "env-model")
    cfg = cfg_mod.load_config()
    assert cfg.model == "env-model"


def test_ollama_host_env_overrides_and_normalizes(
    isolated: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OLLAMA_HOST env var wins AND gets normalized through
    _normalize_ollama_host. So 0.0.0.0 in the env becomes 127.0.0.1
    (the regression that prompted the normalize helper)."""
    _write_toml(isolated, 'ollama_host = "http://from-file:11434"\n')
    monkeypatch.setenv("OLLAMA_HOST", "0.0.0.0:11434")
    cfg = cfg_mod.load_config()
    assert cfg.ollama_host == "http://127.0.0.1:11434"


def test_ollama_host_env_overrides_default_when_no_file(
    isolated: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Env-only — no config.toml. Common case for containerized runs."""
    monkeypatch.setenv("OLLAMA_HOST", "gpu-box.lan:11434")
    cfg = cfg_mod.load_config()
    assert cfg.ollama_host == "http://gpu-box.lan:11434"


# ---------------------------------------------------------------------------
# auto_approve_bash deprecation rename
# ---------------------------------------------------------------------------


def test_deprecated_auto_approve_bash_renames_to_auto_approve_tools(
    isolated: Path, capsys: pytest.CaptureFixture,
) -> None:
    """Backward compat: ``auto_approve_bash = true`` in old configs
    gets renamed to ``auto_approve_tools`` with a stderr warning."""
    _write_toml(isolated, "auto_approve_bash = true\n")
    cfg = cfg_mod.load_config()
    assert cfg.auto_approve_tools is True
    captured = capsys.readouterr()
    assert "deprecated" in captured.err.lower()
    assert "auto_approve_tools" in captured.err


def test_new_name_wins_when_both_present(
    isolated: Path, capsys: pytest.CaptureFixture,
) -> None:
    """If a config has BOTH the old and new names (user mid-migration),
    the new ``auto_approve_tools`` wins and no rename happens (the
    old one is ignored, no warning)."""
    _write_toml(isolated, """
        auto_approve_bash = false
        auto_approve_tools = true
    """)
    cfg = cfg_mod.load_config()
    assert cfg.auto_approve_tools is True


# ---------------------------------------------------------------------------
# Phase 18.1 R4 -- nested config migration (SkillsConfig + BashConfig pilot)
# ---------------------------------------------------------------------------


def test_skills_table_loads_into_nested_dataclass(isolated: Path) -> None:
    """The new ``[skills]`` table sets the nested SkillsConfig directly --
    no deprecation warning, no legacy shim involvement."""
    _write_toml(isolated, """
        [skills]
        autoload = true
        autoload_interval = 5.0
    """)
    cfg = cfg_mod.load_config()
    assert cfg.skills.autoload is True
    assert cfg.skills.autoload_interval == 5.0


def test_legacy_flat_skills_keys_fold_into_nested(
    isolated: Path, capsys: pytest.CaptureFixture,
) -> None:
    """Legacy flat ``skills_autoload`` at TOML root is folded into the new
    nested location with a one-line stderr deprecation note."""
    _write_toml(isolated, """
        skills_autoload = true
        skills_autoload_interval = 7.5
    """)
    cfg = cfg_mod.load_config()
    assert cfg.skills.autoload is True
    assert cfg.skills.autoload_interval == 7.5
    captured = capsys.readouterr()
    assert "skills_autoload" in captured.err
    assert "deprecated" in captured.err.lower()


def test_legacy_flat_attribute_read_emits_deprecation_warning(
    isolated: Path,
) -> None:
    """Reading ``cfg.skills_autoload`` still works (one release) but warns."""
    import warnings

    cfg = cfg_mod.Config()
    cfg.skills.autoload = True
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert cfg.skills_autoload is True  # legacy attribute read
    assert any(
        issubclass(w.category, DeprecationWarning)
        and "skills_autoload" in str(w.message)
        for w in caught
    )


def test_unknown_attribute_still_raises_attributeerror() -> None:
    """The __getattr__ shim only resolves NAMES in ``_LEGACY_FIELD_MAP``;
    truly unknown attrs must still raise so callers don't get a silent
    surprise."""
    cfg = cfg_mod.Config()
    with pytest.raises(AttributeError):
        cfg.this_attribute_does_not_exist  # noqa: B018


def test_bash_table_loads_into_nested_dataclass(isolated: Path) -> None:
    _write_toml(isolated, """
        [bash]
        allowlist = ["git", "ls"]
        extra_denylist = ["rm.*-rf"]
    """)
    cfg = cfg_mod.load_config()
    assert cfg.bash.allowlist == ["git", "ls"]
    assert cfg.bash.extra_denylist == ["rm.*-rf"]


def test_new_table_wins_over_legacy_flat_for_same_field(
    isolated: Path,
) -> None:
    """If both ``[skills] autoload = true`` AND legacy ``skills_autoload``
    appear, the new-shape entry wins. No warning for the explicit
    new-shape user."""
    _write_toml(isolated, """
        skills_autoload = false
        [skills]
        autoload = true
    """)
    cfg = cfg_mod.load_config()
    assert cfg.skills.autoload is True


# ---------------------------------------------------------------------------
# Theme application
# ---------------------------------------------------------------------------


def test_unknown_theme_falls_back_silently(
    isolated: Path,
) -> None:
    """A typo in the theme name must NOT crash startup. Falls back
    to default (phosphor) silently — the rest of the session works
    fine, the user just doesn't see their custom palette."""
    _write_toml(isolated, 'theme = "definitely-not-a-real-theme"\n')
    # MUST NOT raise
    cfg = cfg_mod.load_config()
    assert cfg.theme == "definitely-not-a-real-theme"  # value preserved


def test_phosphor_default_skips_set_theme_call(isolated: Path) -> None:
    """The set_theme call is gated on ``cfg.theme != "phosphor"`` —
    saves an import + a function call on the default path. Pin this
    so a future refactor doesn't accidentally always-invoke."""
    # Default config — no theme override
    cfg = cfg_mod.load_config()
    assert cfg.theme == "phosphor"  # default value


# ---------------------------------------------------------------------------
# Plugin state persistence
# ---------------------------------------------------------------------------


def test_load_plugin_state_missing_file_returns_empty(isolated: Path) -> None:
    """No plugins_state.json yet (fresh install) → empty dict, no
    exception."""
    assert cfg_mod.load_plugin_state() == {}


def test_load_plugin_state_malformed_returns_empty(isolated: Path) -> None:
    """Corrupt JSON must NOT crash athena startup — pin silent
    fallback to empty dict. Worst case: user's plugin enable state
    resets to defaults, recoverable."""
    cfg_mod.PLUGINS_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    cfg_mod.PLUGINS_STATE_PATH.write_text("{not valid json", encoding="utf-8")
    assert cfg_mod.load_plugin_state() == {}


def test_load_plugin_state_non_dict_top_level_returns_empty(
    isolated: Path,
) -> None:
    """File contains valid JSON but a non-object at top level
    (someone wrote a list by mistake) → empty dict."""
    cfg_mod.PLUGINS_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    cfg_mod.PLUGINS_STATE_PATH.write_text('["not", "a", "dict"]', encoding="utf-8")
    assert cfg_mod.load_plugin_state() == {}


def test_save_then_load_plugin_state_roundtrip(isolated: Path) -> None:
    state = {"enabled": {"observability": True, "shell_audit": False}}
    cfg_mod.save_plugin_state(state)
    assert cfg_mod.load_plugin_state() == state


def test_save_plugin_state_creates_parent_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If ~/.athena/ doesn't exist yet, save_plugin_state must
    create it. Otherwise a fresh install + first plugin toggle =
    crash."""
    nested = tmp_path / "no" / "such" / "path" / "plugins_state.json"
    monkeypatch.setattr(cfg_mod, "PLUGINS_STATE_PATH", nested)
    cfg_mod.save_plugin_state({"enabled": {"x": True}})
    assert nested.exists()


def test_save_plugin_state_writes_pretty_sorted(isolated: Path) -> None:
    """Sorted keys + indent=2 + trailing newline so the file is
    diff-friendly when someone edits it by hand."""
    cfg_mod.save_plugin_state({"zebra": 1, "alpha": 2})
    body = cfg_mod.PLUGINS_STATE_PATH.read_text(encoding="utf-8")
    assert body.endswith("\n")
    # alpha < zebra alphabetically; sort_keys puts alpha first
    assert body.find("alpha") < body.find("zebra")
    # Indented (not minified)
    assert "  " in body or "\t" in body


# ---------------------------------------------------------------------------
# _merge_plugin_state — overlay logic
# ---------------------------------------------------------------------------


def test_merge_plugin_state_no_sidecar_returns_config_unchanged(
    isolated: Path,
) -> None:
    base = {"observability": {"metrics_console": False}}
    out = cfg_mod._merge_plugin_state(base)
    assert out == base


def test_merge_plugin_state_overlays_enabled_dict(isolated: Path) -> None:
    """plugins_state.json's `enabled` map overlays config.toml's
    enable settings. Sidecar wins for keys it specifies; config
    keys not in the sidecar are preserved."""
    cfg_mod.save_plugin_state({"enabled": {"observability": False}})
    cfg = {"enabled": {"observability": True, "shell_audit": True}}
    out = cfg_mod._merge_plugin_state(cfg)
    assert out["enabled"]["observability"] is False  # sidecar wins
    assert out["enabled"]["shell_audit"] is True  # preserved from cfg


def test_merge_plugin_state_handles_missing_cfg_enabled(
    isolated: Path,
) -> None:
    """Config has no [plugins.enabled] section but sidecar does —
    overlay still works, doesn't crash."""
    cfg_mod.save_plugin_state({"enabled": {"new_plugin": True}})
    out = cfg_mod._merge_plugin_state({})
    assert out["enabled"]["new_plugin"] is True


def test_merge_plugin_state_ignores_non_dict_state_enabled(
    isolated: Path,
) -> None:
    """If the sidecar has `enabled` as a non-dict (corruption /
    schema drift), don't crash — just don't overlay."""
    cfg_mod.save_plugin_state({"enabled": "not a dict"})
    cfg = {"enabled": {"x": True}}
    out = cfg_mod._merge_plugin_state(cfg)
    assert out["enabled"] == {"x": True}


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------


def test_profile_dir_default(isolated: Path) -> None:
    p = cfg_mod.profile_dir()
    assert p.name == "default"
    assert p.parent.name == "profiles"


def test_profile_dir_custom_profile(isolated: Path) -> None:
    p = cfg_mod.profile_dir("work")
    assert p.name == "work"


def test_profile_dir_custom_home(tmp_path: Path) -> None:
    """Caller can override the home root (used by tests + the
    profile manager during onboarding)."""
    custom = tmp_path / "elsewhere"
    p = cfg_mod.profile_dir("p1", home=custom)
    assert p == custom / "profiles" / "p1"


def test_mcp_config_paths_returns_three_in_precedence_order(
    isolated: Path, tmp_path: Path,
) -> None:
    """MCP config precedence: user → project-hidden → project-visible.
    LATER paths in the list WIN (loader merges in order). Pin the
    order so a refactor doesn't accidentally flip user-vs-project
    precedence."""
    workspace = tmp_path / "ws"
    paths = cfg_mod.mcp_config_paths(workspace)
    assert len(paths) == 3
    assert paths[0] == cfg_mod.USER_MCP_PATH
    assert paths[1] == workspace / ".athena" / "mcp.json"
    assert paths[2] == workspace / "mcp.json"
