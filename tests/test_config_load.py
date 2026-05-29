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
# Phase 18.1 R4 stage 2 -- SafetyConfig promotion
# ---------------------------------------------------------------------------


def test_safety_defaults_match_legacy_dict(isolated: Path) -> None:
    """No [safety] table -> dataclass defaults match the dict the
    promotion replaced. Users on factory settings see no behaviour
    change."""
    cfg = cfg_mod.load_config()
    assert cfg.safety.snapshot_foreground is False
    assert cfg.safety.retention_days == 90
    assert cfg.safety.retention_count == 5_000
    assert cfg.safety.retention_bytes == 5 * 1024**3


def test_safety_table_overrides_defaults(isolated: Path) -> None:
    """The [safety] TOML table maps onto SafetyConfig field-by-field
    through the existing _assign_field dataclass-merge logic."""
    _write_toml(isolated, """
        [safety]
        snapshot_foreground = true
        retention_days = 30
        retention_count = 100
        retention_bytes = 1073741824
    """)
    cfg = cfg_mod.load_config()
    assert cfg.safety.snapshot_foreground is True
    assert cfg.safety.retention_days == 30
    assert cfg.safety.retention_count == 100
    assert cfg.safety.retention_bytes == 1024**3


def test_safety_partial_override_keeps_other_defaults(isolated: Path) -> None:
    """Setting only retention_days must leave the other fields at their
    defaults (the merge logic at _assign_field doesn't overwrite the
    whole dataclass with a sparse TOML table)."""
    _write_toml(isolated, """
        [safety]
        retention_days = 7
    """)
    cfg = cfg_mod.load_config()
    assert cfg.safety.retention_days == 7
    assert cfg.safety.retention_count == 5_000  # default preserved
    assert cfg.safety.snapshot_foreground is False  # default preserved


# ---------------------------------------------------------------------------
# Phase 18.1 R4 stage 3 -- ComputerConfig promotion
# ---------------------------------------------------------------------------


def test_computer_defaults_match_legacy_flat(isolated: Path) -> None:
    """No [computer] table -> nested dataclass defaults match the
    legacy flat-field defaults exactly."""
    cfg = cfg_mod.load_config()
    assert cfg.computer.use_enabled is False
    assert cfg.computer.permission_mode == "observe_only"
    assert cfg.computer.app_allowlist == []
    assert cfg.computer.kill_hotkey == "ctrl+alt+k"
    assert cfg.computer.max_actions_per_task == 40
    assert cfg.computer.deny_during_goal_loop is True
    # Default denylist still contains the password / finance apps.
    deny = cfg.computer.app_denylist
    assert any("password" in d.lower() for d in deny)


def test_computer_table_loads_into_nested(isolated: Path) -> None:
    _write_toml(isolated, """
        [computer]
        use_enabled = true
        permission_mode = "per_action"
        max_actions_per_task = 5
        kill_hotkey = "ctrl+alt+q"
    """)
    cfg = cfg_mod.load_config()
    assert cfg.computer.use_enabled is True
    assert cfg.computer.permission_mode == "per_action"
    assert cfg.computer.max_actions_per_task == 5
    assert cfg.computer.kill_hotkey == "ctrl+alt+q"


def test_legacy_flat_computer_read_emits_warning(
    isolated: Path,
) -> None:
    """Reading cfg.computer_use_enabled still works for one release
    but emits a DeprecationWarning routing the caller to the new path."""
    import warnings

    cfg = cfg_mod.Config()
    cfg.computer.use_enabled = True
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert cfg.computer_use_enabled is True
    assert any(
        issubclass(w.category, DeprecationWarning)
        and "computer_use_enabled" in str(w.message)
        for w in caught
    )


def test_legacy_flat_computer_write_routes_to_nested(
    isolated: Path,
) -> None:
    """Test fixtures and operator scripts commonly write
    cfg.computer_X = Y. Config.__setattr__ routes those through to
    the nested instance so canonical readers (cfg.computer.X) and
    legacy reads (cfg.computer_X) see the same value."""
    cfg = cfg_mod.Config()
    cfg.computer_use_enabled = True
    assert cfg.computer.use_enabled is True
    cfg.computer_permission_mode = "per_action"
    assert cfg.computer.permission_mode == "per_action"


# ---------------------------------------------------------------------------
# Phase 18.1 R4 stage 4 -- ParseltongueConfig promotion
# ---------------------------------------------------------------------------


def test_parseltongue_defaults_to_heuristic_policy(isolated: Path) -> None:
    """No [parseltongue] table -> dataclass defaults match the dict
    behaviour: heuristic policy with empty defaults / user_rules."""
    cfg = cfg_mod.load_config()
    assert cfg.parseltongue.policy == "heuristic"
    assert cfg.parseltongue.defaults == {}
    assert cfg.parseltongue.user_rules == []
    assert cfg.parseltongue.classifier_model == "qwen2.5:1.5b"


def test_parseltongue_table_loads_into_dataclass(isolated: Path) -> None:
    _write_toml(isolated, """
        [parseltongue]
        policy = "static"

        [parseltongue.defaults]
        temperature = 0.2
        top_p = 0.9
    """)
    cfg = cfg_mod.load_config()
    assert cfg.parseltongue.policy == "static"
    assert cfg.parseltongue.defaults == {"temperature": 0.2, "top_p": 0.9}


def test_policy_from_config_accepts_dataclass(isolated: Path) -> None:
    """The promoted ParseltongueConfig instance is accepted by
    policy_from_config directly -- canonical readers don't need to
    convert to a dict first."""
    from athena.agent.param_policy import policy_from_config, StaticPolicy

    cfg = cfg_mod.Config()
    cfg.parseltongue.policy = "static"
    cfg.parseltongue.defaults = {"temperature": 0.1}
    policy = policy_from_config(cfg.parseltongue)
    assert isinstance(policy, StaticPolicy)
    assert policy.defaults == {"temperature": 0.1}


def test_policy_from_config_still_accepts_dict_for_back_compat() -> None:
    """One-release back-compat: the eval runner + external scripts
    can still pass a plain dict to policy_from_config so the migration
    can happen at the caller's pace."""
    from athena.agent.param_policy import policy_from_config, StaticPolicy

    policy = policy_from_config({"policy": "static", "defaults": {"temperature": 0.3}})
    assert isinstance(policy, StaticPolicy)
    assert policy.defaults == {"temperature": 0.3}


# ---------------------------------------------------------------------------
# Phase 18.1 R4 stage 4b -- PluginsConfig promotion
# ---------------------------------------------------------------------------


def test_plugins_defaults_match_legacy_dict(isolated: Path) -> None:
    """No [plugins] table -> PluginsConfig has empty enabled +
    empty per_plugin. Matches the legacy ``dict[str, Any] = {}``
    behaviour."""
    cfg = cfg_mod.load_config()
    assert isinstance(cfg.plugins, cfg_mod.PluginsConfig)
    assert cfg.plugins.enabled == {}
    assert cfg.plugins.per_plugin == {}


def test_plugins_table_loads_enabled_and_per_plugin(isolated: Path) -> None:
    """The [plugins] block splits into ``enabled`` and per-plugin
    sub-tables. Each ``[plugins.<name>]`` (not "enabled") goes into
    PluginsConfig.per_plugin[<name>]."""
    _write_toml(isolated, """
        [plugins.enabled]
        observability = true
        shell_audit = false

        [plugins.observability]
        metrics_console = true
        export_interval_s = 30
    """)
    cfg = cfg_mod.load_config()
    assert cfg.plugins.enabled == {"observability": True, "shell_audit": False}
    assert cfg.plugins.per_plugin["observability"] == {
        "metrics_console": True,
        "export_interval_s": 30,
    }


def test_plugins_dict_style_readers_still_work(isolated: Path) -> None:
    """Existing readers do ``cfg.plugins.get("enabled")`` and
    ``cfg.plugins["plugin_name"]``. The dataclass implements
    __getitem__ / get / __contains__ so they keep working."""
    cfg = cfg_mod.Config()
    cfg.plugins.enabled["observability"] = True
    cfg.plugins.per_plugin["shell_audit"] = {"log_root": "/tmp/x"}

    # ``cfg.plugins.get("enabled")`` returns the enable map.
    assert cfg.plugins.get("enabled") == {"observability": True}
    # ``cfg.plugins.get("<plugin_name>")`` returns the per-plugin slice.
    assert cfg.plugins.get("shell_audit") == {"log_root": "/tmp/x"}
    assert cfg.plugins.get("missing") is None
    assert cfg.plugins.get("missing", {"default": True}) == {"default": True}
    # ``"enabled" in cfg.plugins`` is always True; arbitrary plugin
    # names test against per_plugin.
    assert "enabled" in cfg.plugins
    assert "shell_audit" in cfg.plugins
    assert "missing" not in cfg.plugins
    # __getitem__ honours the same routing.
    assert cfg.plugins["enabled"] == {"observability": True}
    assert cfg.plugins["shell_audit"] == {"log_root": "/tmp/x"}


def test_plugins_as_dict_for_loader_reconstitutes_envelope(
    isolated: Path,
) -> None:
    """The plugin loader takes a dict-shaped config. PluginsConfig
    exposes ``as_dict_for_loader`` so the agent's _build_plugin_hooks
    can hand the loader the legacy envelope without leaking the
    dataclass through the loader's interface."""
    cfg = cfg_mod.Config()
    cfg.plugins.enabled = {"observability": True}
    cfg.plugins.per_plugin = {"shell_audit": {"log_root": "/tmp/x"}}
    out = cfg.plugins.as_dict_for_loader()
    assert out == {
        "enabled": {"observability": True},
        "shell_audit": {"log_root": "/tmp/x"},
    }
    # ``as_dict_for_loader`` returns COPIES so the loader can't mutate
    # the live PluginsConfig.
    out["enabled"]["observability"] = False
    out["shell_audit"]["log_root"] = "/somewhere/else"
    assert cfg.plugins.enabled == {"observability": True}
    assert cfg.plugins.per_plugin["shell_audit"] == {"log_root": "/tmp/x"}


def test_snapshot_store_singleton_picks_up_safety_retention(
    isolated: Path, tmp_path: Path,
) -> None:
    """The Phase 18.1 R4 stage 2 wiring change: get_snapshot_store()
    now reads cfg.safety so the user's [safety] table actually takes
    effect on retention. Before this commit the singleton ignored cfg
    entirely and used SnapshotStore's hardcoded defaults -- the
    [safety] dict was advertised but dead."""
    from athena.safety import context as ctx_mod

    _write_toml(isolated, """
        [safety]
        retention_days = 14
        retention_count = 50
    """)
    ctx_mod.reset_for_tests()
    try:
        store = ctx_mod.get_snapshot_store(profile_dir=tmp_path)
        assert store.retention_days == 14
        assert store.retention_count == 50
    finally:
        ctx_mod.reset_for_tests()


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


def test_merge_plugin_state_no_sidecar_leaves_config_unchanged(
    isolated: Path,
) -> None:
    """R4 stage 4b changed _merge_plugin_state's signature from
    ``dict -> dict`` to ``PluginsConfig -> None`` (in-place mutation)."""
    plugins = cfg_mod.PluginsConfig()
    plugins.per_plugin["observability"] = {"metrics_console": False}
    cfg_mod._merge_plugin_state(plugins)
    # No sidecar file present in isolated -> nothing to overlay.
    assert plugins.enabled == {}
    assert plugins.per_plugin["observability"] == {"metrics_console": False}


def test_merge_plugin_state_overlays_enabled_dict(isolated: Path) -> None:
    """plugins_state.json's ``enabled`` map overlays the PluginsConfig's
    enable settings. Sidecar wins for keys it specifies; config keys
    not in the sidecar are preserved."""
    cfg_mod.save_plugin_state({"enabled": {"observability": False}})
    plugins = cfg_mod.PluginsConfig(
        enabled={"observability": True, "shell_audit": True},
    )
    cfg_mod._merge_plugin_state(plugins)
    assert plugins.enabled["observability"] is False  # sidecar wins
    assert plugins.enabled["shell_audit"] is True  # preserved


def test_merge_plugin_state_handles_empty_initial_enabled(
    isolated: Path,
) -> None:
    """Config has no [plugins.enabled] section but sidecar does --
    overlay still works, doesn't crash."""
    cfg_mod.save_plugin_state({"enabled": {"new_plugin": True}})
    plugins = cfg_mod.PluginsConfig()
    cfg_mod._merge_plugin_state(plugins)
    assert plugins.enabled["new_plugin"] is True


def test_merge_plugin_state_ignores_non_dict_state_enabled(
    isolated: Path,
) -> None:
    """If the sidecar has ``enabled`` as a non-dict (corruption /
    schema drift), don't crash -- just don't overlay."""
    cfg_mod.save_plugin_state({"enabled": "not a dict"})
    plugins = cfg_mod.PluginsConfig(enabled={"x": True})
    cfg_mod._merge_plugin_state(plugins)
    assert plugins.enabled == {"x": True}


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
