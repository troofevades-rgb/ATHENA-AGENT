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
    from ..providers import _REGISTRY

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


def _credential_env_candidates(name: str) -> list[str]:
    """The env-var names a backend's credential could live under.

    Resolution order:
      1. Backend's ``credential_env_vars`` class attribute (declared
         explicitly so the auth-status display matches what the
         backend's own resolver actually checks).
      2. Heuristic fallback: ``ATHENA_<NAME>_API_KEY``,
         ``ATHENA_<NAME>_TOKEN``, ``<NAME>_API_KEY``.
    """
    from ..providers import _REGISTRY

    cls = _REGISTRY.get(name)
    declared = getattr(cls, "credential_env_vars", None) if cls else None
    if declared:
        return [str(k) for k in declared]
    canonical = name.upper().replace("-", "_")
    return [
        f"ATHENA_{canonical}_API_KEY",
        f"ATHENA_{canonical}_TOKEN",
        f"{canonical}_API_KEY",
    ]


def _find_credential(name: str) -> str | None:
    """Return a short label for where ``name``'s credential lives, or
    None if none is set.

    Checks the env-var candidates first, then the secure credential
    pool (``~/.athena/credentials.json``) under the backend's declared
    ``credential_pool_names`` — falling back to the backend name. This
    matches what the backend's own resolver checks, so status doesn't
    report "no credential" for a key that's actually in the pool.
    """
    from ..env import get_credential
    from ..providers import _REGISTRY

    for key in _credential_env_candidates(name):
        if get_credential(key):
            return key

    cls = _REGISTRY.get(name)
    pool_names = getattr(cls, "credential_pool_names", None) or (name,)
    try:
        from ..providers.credential_pool import global_pool

        pool = global_pool()
        for pool_name in pool_names:
            if pool.get(pool_name) is not None:
                return f"credential pool ({pool_name})"
    except Exception:  # noqa: BLE001 — pool lookup is best-effort
        pass
    return None


def _auth_status(name: str) -> str:
    """Rich-markup credential-status string for a backend."""
    found = _find_credential(name)
    if found:
        return f"[green]auth ok[/] (via {found})"
    return "[yellow]no credential found[/]"


def _resolved_backend_name(cfg) -> str | None:
    """What a ``video_generate`` call will ACTUALLY use right now —
    the result of the same resolver the tools call. Returns the backend
    name, or None if nothing resolves. Never raises."""
    try:
        from ..videogen.job import resolve_backend

        backend = resolve_backend(cfg)
        return getattr(backend, "name", None)
    except Exception:  # noqa: BLE001 — status display must not crash
        return None


def _show(agent) -> None:
    cfg = getattr(agent, "cfg", None)
    vg = getattr(cfg, "video_generation", None) if cfg else None
    selector = vg.backend if vg is not None else None
    enabled = bool(getattr(vg, "enabled", False)) if vg is not None else False

    ui.console.print(
        f"[bold]video generation:[/] {'[green]enabled[/]' if enabled else '[yellow]disabled[/]'}"
    )
    ui.console.print(f"[bold]video selector:[/] {selector or '[dim](auto — broker picks)[/]'}")

    # Effective backend — the real "what will run" answer. A None
    # selector silently resolving to the local stub is exactly the
    # confusion this line exists to clear up.
    resolved = _resolved_backend_name(cfg) if cfg is not None else None
    backends = _video_backends()
    requires_key = {n: rk for n, rk in backends}
    if resolved is None:
        ui.console.print(
            "[bold]effective backend:[/] [yellow](none — calls return not_configured)[/]"
        )
    else:
        cred = _find_credential(resolved) if requires_key.get(resolved) else None
        if not requires_key.get(resolved):
            note = "[dim]local (no key)[/]"
        elif cred:
            note = f"[green]auth ok[/] (via {cred})"
        else:
            note = "[red]NO CREDENTIAL — calls will fail until a key is set[/]"
        ui.console.print(f"[bold]effective backend:[/] {resolved}  —  {note}")
        # Loud, actionable hint when the resolved backend can't run.
        if requires_key.get(resolved) and not cred:
            keys = " or ".join(_credential_env_candidates(resolved))
            ui.warn(f"set {keys} in ~/.athena/.env to use {resolved}")

    if not backends:
        ui.warn("no providers declare video_generation capability")
        return

    ui.console.print("[bold]available backends:[/]")
    for name, rk in backends:
        marker = " *" if name == selector else "  "
        auth = _auth_status(name) if rk else "[dim]local (no key)[/]"
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
    cfg.video_generation.backend = name
    ui.info(f"video backend → {name} (session-scoped; edit ~/.athena/config.toml to persist)")


def _clear(agent) -> None:
    cfg = getattr(agent, "cfg", None)
    if cfg is None:
        ui.error("agent has no cfg attribute")
        return
    cfg.video_generation.backend = None
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
