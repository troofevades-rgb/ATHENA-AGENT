"""``/theme`` — inspect or switch the TUI color palette.

Subcommands::

    /theme              show the active theme + every registered one
    /theme list         name-only listing (scriptable)
    /theme set <name>   switch the active theme for this session
    /theme save         persist the current theme to config.toml

Theming applies immediately to every subsequent ``ui.*`` call —
banner, status bar, tool-call panels, info/warn/error lines, the
typewriter prefix bar — they all read from the active theme on
each access. The next ``/dump`` or model turn will render in the
new palette without restarting athena.
"""

from __future__ import annotations

from .. import ui
from . import command


def _swatch(color: str) -> str:
    """A short colored block for visual previews in the listing."""
    return f"[on {color}]    [/]"


def _show(agent) -> None:
    active = ui.theme()
    ui.console.print(
        f"[bold]active theme:[/] {active.name} — [dim]{active.description}[/]"
    )
    ui.console.print("[bold]available themes:[/]")
    for t in ui.list_themes():
        marker = " *" if t.name == active.name else "  "
        # Inline preview: primary / accent / dim swatches.
        swatches = (
            _swatch(t.primary)
            + _swatch(t.accent)
            + _swatch(t.primary_dim)
        )
        ui.console.print(
            f"{marker} [bold]{t.name:10}[/] {swatches}  [dim]{t.description}[/]"
        )


def _list(agent) -> None:
    for t in ui.list_themes():
        ui.console.print(t.name)


def _set(agent, name: str) -> None:
    name = name.strip()
    if not name:
        ui.error("usage: /theme set <name>")
        return
    try:
        new = ui.set_theme(name)
    except KeyError as e:
        ui.error(str(e))
        return
    # Mirror onto the live cfg so a follow-up build_banner()
    # resolves the same theme. Tests sometimes pass an agent
    # stub without ``cfg`` — guard so the slash never crashes
    # on a thin test double.
    cfg = getattr(agent, "cfg", None)
    if cfg is not None:
        cfg.theme = new.name
    # When running under the Ink TUI, push a fresh BannerEvent
    # so the Nameplate / status bar palette repaints immediately
    # instead of waiting for the next session. Headless / Rich
    # mode has no gateway; the call is a no-op there.
    _refresh_tui_banner(agent)
    ui.info(
        f"theme → {new.name} ({new.description}). "
        "session-scoped; use /theme save to persist."
    )


def _refresh_tui_banner(agent) -> None:
    """If a TUI gateway is active, re-emit ``BannerEvent`` so
    the Ink-side palette updates live. Silent no-op when the
    legacy Rich UI path is in use or the banner build fails for
    any reason — the slash command itself must never crash on a
    rendering follow-up."""
    gw = ui.gateway()
    if gw is None:
        return
    try:
        from pathlib import Path

        from ..tui_gateway.banner_data import build_banner

        gw.send_event(
            build_banner(
                model=agent.model,
                cwd=Path(agent.workspace),
                cfg=agent.cfg,
            )
        )
    except Exception:  # noqa: BLE001 — UX follow-up, not load-bearing
        return


def _save(agent) -> None:
    """Persist the active theme name to ``~/.athena/config.toml``.

    Atomic write: parse the existing file, set or insert ``theme =
    "<name>"`` ABOVE the first ``[section]`` header (top-level keys
    must precede sections in TOML — same gotcha we've hit twice in
    this project), then rewrite.
    """
    from pathlib import Path

    cfg_path = Path.home() / ".athena" / "config.toml"
    active = ui.theme()
    if not cfg_path.exists():
        # Create with a minimal header line.
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(
            f'theme = "{active.name}"\n', encoding="utf-8",
        )
        ui.info(f"wrote new config at {cfg_path} with theme = {active.name!r}")
        return

    lines = cfg_path.read_text(encoding="utf-8").splitlines()
    # Find existing theme line.
    found = False
    out: list[str] = []
    first_section = None
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("theme = ") or stripped.startswith("theme="):
            out.append(f'theme = "{active.name}"')
            found = True
            continue
        if first_section is None and stripped.startswith("[") and stripped.endswith("]"):
            first_section = i
        out.append(line)

    if not found:
        # Insert theme line above the first [section], else append.
        insert_at = first_section if first_section is not None else len(out)
        out.insert(insert_at, f'theme = "{active.name}"')

    cfg_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    ui.info(f"saved theme = {active.name!r} to {cfg_path}")


@command("theme")
def cmd_theme(agent, arg: str = "") -> str:
    """``/theme`` — inspect or switch the TUI color palette."""
    arg = (arg or "").strip()
    if not arg or arg in ("status", "show"):
        _show(agent)
        return ""
    if arg == "list":
        _list(agent)
        return ""
    if arg == "save":
        _save(agent)
        return ""
    if arg.startswith("set "):
        _set(agent, arg[4:])
        return ""
    if arg == "set":
        ui.error("usage: /theme set <name>")
        return ""
    ui.error(
        f"unknown /theme subcommand: {arg!r}. "
        "Try: /theme, /theme list, /theme set <name>, /theme save"
    )
    return ""
