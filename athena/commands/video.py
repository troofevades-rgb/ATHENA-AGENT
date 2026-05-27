"""``/video`` — inspect + switch video-generation backends from the TUI.

Subcommands::

    /video               show current backend, available backends,
                         auth status, and the configured selector
    /video status        alias for bare /video
    /video list          list registered video_generation providers
    /video set <name>    switch to a named backend for this session
                         (mutates cfg.video_backend in memory)
    /video clear         unset the selector — let the broker pick

The selector lives on ``agent.cfg.video_backend`` and takes effect on
the next ``video_generate`` / ``animate_image`` call. /video persist
support (write to TOML) is deferred — for now ``/video set`` is
session-scoped; add the line to ``~/.athena/config.toml`` directly to
make it permanent.
"""

from __future__ import annotations

from .. import ui
from . import command


def _video_backends() -> list[tuple[str, bool]]:
    """Return ``[(name, requires_api_key), ...]`` for every registered
    provider whose static capabilities declare ``video_generation``.
    Sorted alphabetically for stable display.
    """
    from ..providers import _REGISTRY  # type: ignore[attr-defined]

    out: list[tuple[str, bool]] = []
    for name, cls in _REGISTRY.items():
        try:
            caps = cls.static_capabilities()
        except Exception:  # noqa: BLE001
            continue
        if not caps.supports("video_generation"):
            continue
        requires_key = bool(getattr(cls, "requires_api_key", False))
        out.append((name, requires_key))
    out.sort(key=lambda t: t[0])
    return out


def _auth_status(name: str) -> str:
    """Best-effort credential-status string for a backend.

    Resolution order:
      1. Backend's ``credential_env_vars`` class attribute (declared
         explicitly so the auth-status display matches what the
         backend's own resolver actually checks).
      2. Heuristic fallback: ``ATHENA_<NAME>_API_KEY``,
         ``ATHENA_<NAME>_TOKEN``, ``<NAME>_API_KEY``.

    Returns a rich-markup string for display.
    """
    from ..env import get_credential
    from ..providers import _REGISTRY  # type: ignore[attr-defined]

    candidates: list[str] = []
    cls = _REGISTRY.get(name)
    declared = getattr(cls, "credential_env_vars", None) if cls else None
    if declared:
        candidates.extend(str(k) for k in declared)
    else:
        canonical = name.upper().replace("-", "_")
        candidates.extend([
            f"ATHENA_{canonical}_API_KEY",
            f"ATHENA_{canonical}_TOKEN",
            f"{canonical}_API_KEY",
        ])

    for key in candidates:
        if get_credential(key):
            return f"[green]auth ok[/] (via {key})"
    return "[yellow]no credential found[/]"


def _show(agent) -> None:
    cfg = getattr(agent, "cfg", None)
    selector = getattr(cfg, "video_backend", None) if cfg else None

    ui.console.print(
        f"[bold]video selector:[/] {selector or '[dim](auto — broker picks)[/]'}"
    )

    backends = _video_backends()
    if not backends:
        ui.warn("no providers declare video_generation capability")
        return

    ui.console.print("[bold]available backends:[/]")
    for name, requires_key in backends:
        marker = " *" if name == selector else "  "
        auth = _auth_status(name) if requires_key else "[dim]local (no key)[/]"
        ui.console.print(f"{marker} {name}  —  {auth}")


def _list(agent) -> None:
    """Compact name-only listing for scripts."""
    for name, _ in _video_backends():
        ui.console.print(name)


def _set(agent, name: str) -> None:
    name = name.strip()
    if not name:
        ui.error("usage: /video set <backend_name>")
        return
    backends = {n for n, _ in _video_backends()}
    if name not in backends:
        avail = ", ".join(sorted(backends)) or "(none)"
        ui.error(f"unknown video backend: {name!r}. Available: {avail}")
        return
    cfg = getattr(agent, "cfg", None)
    if cfg is None:
        ui.error("agent has no cfg attribute — cannot set selector")
        return
    cfg.video_backend = name
    ui.info(
        f"video backend → {name} (session-scoped; edit "
        "~/.athena/config.toml to persist)"
    )


def _clear(agent) -> None:
    cfg = getattr(agent, "cfg", None)
    if cfg is None:
        ui.error("agent has no cfg attribute")
        return
    cfg.video_backend = None
    ui.info("video selector cleared — broker will choose")


@command("video")
def cmd_video(agent, arg: str = "") -> str:
    """``/video`` — inspect or switch the video-generation backend."""
    arg = (arg or "").strip()
    if not arg or arg in ("status", "show"):
        _show(agent)
        return ""
    if arg == "list":
        _list(agent)
        return ""
    if arg == "clear":
        _clear(agent)
        return ""
    if arg.startswith("set "):
        _set(agent, arg[4:])
        return ""
    if arg == "set":
        ui.error("usage: /video set <backend_name>")
        return ""
    ui.error(
        f"unknown /video subcommand: {arg!r}. "
        "Try: /video, /video list, /video set <name>, /video clear"
    )
    return ""
