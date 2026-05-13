"""Configuration loading. Reads ~/.ocode/config.toml; falls back to defaults."""
from __future__ import annotations
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore


CONFIG_DIR = Path.home() / ".ocode"
CONFIG_PATH = CONFIG_DIR / "config.toml"
SESSIONS_DIR = CONFIG_DIR / "sessions"  # legacy flat dir; new code uses profile_dir
USER_MCP_PATH = CONFIG_DIR / "mcp.json"


def profile_dir(profile: str = "default", home: Path | None = None) -> Path:
    """Return the on-disk root for ``profile`` (``~/.ocode/profiles/<profile>``)."""
    return (home or CONFIG_DIR) / "profiles" / profile


def mcp_config_paths(workspace: Path) -> list[Path]:
    """Files to read for MCP server config, in precedence order (later wins).

    Order:
      1. ~/.ocode/mcp.json           (user-level defaults)
      2. <workspace>/.ocode/mcp.json (project-level, hidden)
      3. <workspace>/mcp.json        (project-level, visible — overrides above)
    """
    return [
        USER_MCP_PATH,
        workspace / ".ocode" / "mcp.json",
        workspace / "mcp.json",
    ]


@dataclass
class Config:
    model: str = "qwen2.5-coder:14b"
    ollama_host: str = "http://127.0.0.1:11434"
    # Profile name under ~/.ocode/profiles/<profile>/. Sessions, memory, and
    # per-profile config live here. Multiple profiles let a user keep work
    # contexts (default / personal / client-foo) separated without juggling
    # OCODE_HOME values.
    profile: str = "default"
    # Skip the per-tool confirmation prompt for tools that opt into it
    # (Bash, Write to existing files, etc.). Replaces the old auto_approve_bash.
    auto_approve_tools: bool = False
    context_window: int = 32768
    # Toolsets advertised to the model. None means "all registered toolsets"
    # (legacy behavior). An explicit list scopes the registry — used by forks
    # to give sub-agents a narrow capability surface.
    enabled_toolsets: list[str] | None = None
    # Tools the user has globally disabled (by name). Deprecated in favor of
    # enabled_toolsets but kept for one transitional release; intersects with
    # enabled_toolsets when both are set.
    disabled_tools: list[str] = field(default_factory=list)
    # Max bytes to include from a single file read
    max_file_read: int = 256_000
    # Max stdout bytes captured per bash run
    max_bash_output: int = 64_000
    # Use a trimmed system prompt (helpful for small or low-context models)
    lean_prompt: bool = False
    # Section names to omit from the system prompt. Names match keys in
    # ocode/prompts/system.py SECTIONS (e.g. "executing_with_care",
    # "session_guidance", "memory_header"). Combines with lean_prompt.
    disabled_prompt_sections: list[str] = field(default_factory=list)
    # Per-Bash command allowlist; entries are simple prefix matches.
    # E.g. ["git status", "git diff", "ls", "cat"]. Allowlisted commands
    # skip the confirmation prompt even when auto_approve_tools is False.
    bash_allowlist: list[str] = field(default_factory=list)
    # Hard cap on tool-call rounds per user turn. Stops runaway loops.
    max_turn_steps: int = 25


def load_config() -> Config:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    cfg = Config()
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "rb") as f:
            data = tomllib.load(f)
        # Back-compat: accept old key name and map it forward
        if "auto_approve_bash" in data and "auto_approve_tools" not in data:
            data["auto_approve_tools"] = data.pop("auto_approve_bash")
            print(
                f"warning: {CONFIG_PATH}: 'auto_approve_bash' is deprecated; "
                "rename to 'auto_approve_tools'.",
                file=sys.stderr,
            )
        for k, v in data.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)
    # Env overrides
    if env := os.environ.get("OCODE_MODEL"):
        cfg.model = env
    if env := os.environ.get("OLLAMA_HOST"):
        cfg.ollama_host = env if env.startswith("http") else f"http://{env}"
    return cfg
