"""Rich terminal UI helpers — confirmation prompts, diff rendering, status."""

from __future__ import annotations

import difflib
import re
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

# On legacy Windows consoles (cp1252-encoded stdout), `console.print` crashes
# on common UI glyphs like ✗ / ✓ / ↳ / ▰ because they aren't representable.
# Reconfigure stdout to encode with errors="replace" so unrepresentable chars
# degrade to '?' instead of taking down the process. Python 3.7+ supports
# ``reconfigure`` on TextIOBase.
if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass

console = Console()

# Pick glyphs that survive the legacy Windows console. The replacement
# variants are plain ASCII fall-backs so a user on cmd.exe with cp1252
# still gets a readable transcript even if their terminal can't render
# the colored unicode symbols.
_X = "x" if console.legacy_windows else "✗"
_CHECK = "+" if console.legacy_windows else "✓"

# ----------------------------------------------------------------------
# Theme system. The legacy ``LIME`` / ``LIME_DIM`` / ``LIME_FAINT`` /
# ``_GRADIENT`` names stay as module-level attributes so existing
# f-string consumers keep working — but they're resolved through the
# active theme at access time via ``__getattr__`` below. Switch themes
# at runtime with ``set_theme(name)`` or via the ``/theme`` slash.
# ----------------------------------------------------------------------


from dataclasses import dataclass, field


@dataclass(frozen=True)
class Theme:
    """Color palette for the TUI.

    Field roles:
      - ``primary``     loudest interactive color (prompt, tool calls)
      - ``primary_dim`` 50% intensity for labels, dim accents
      - ``primary_faint`` 25% intensity for borders + faint hints
      - ``accent``      brand secondary (the owl, banner highlight)
      - ``accent_dim``  50% accent
      - ``gradient``    6-stop gradient walked top-to-bottom in the
                        banner wordmark — usually a vertical fade
                        through the primary hue
    """

    name: str
    description: str
    primary: str
    primary_dim: str
    primary_faint: str
    accent: str
    accent_dim: str
    gradient: tuple[str, ...] = field(default_factory=tuple)


# TUI sprint step 11: themes load from TOML files at startup, not a
# hardcoded dict. Bundled palettes live at athena/tui_gateway/themes/.
# Users can drop their own at ~/.athena/themes/<name>.toml — user
# themes override bundled ones with the same name.
def _load_themes() -> dict[str, "Theme"]:
    """Walk bundled + user theme dirs, load each .toml into a Theme."""
    import os
    try:
        import tomllib  # py311+
    except ImportError:
        import tomli as tomllib  # type: ignore

    themes: dict[str, Theme] = {}

    def _load_dir(dirpath: Path) -> None:
        if not dirpath.is_dir():
            return
        for entry in sorted(dirpath.glob("*.toml")):
            try:
                with open(entry, "rb") as f:
                    data = tomllib.load(f)
                t = Theme(
                    name=str(data["name"]),
                    description=str(data.get("description", "")),
                    primary=str(data["primary"]),
                    primary_dim=str(data["primary_dim"]),
                    primary_faint=str(data["primary_faint"]),
                    accent=str(data["accent"]),
                    accent_dim=str(data["accent_dim"]),
                    gradient=tuple(str(c) for c in data.get("gradient", [])),
                )
                themes[t.name] = t  # user-dir overrides bundled
            except Exception as e:  # noqa: BLE001
                import logging as _logging
                _logging.getLogger(__name__).warning(
                    "failed to load theme %s: %s", entry, e,
                )

    bundled_dir = Path(__file__).resolve().parent / "tui_gateway" / "themes"
    user_dir = Path(os.path.expanduser("~/.athena/themes"))
    _load_dir(bundled_dir)
    _load_dir(user_dir)

    # Fail-safe: if no themes loaded (corrupt install), synthesize a
    # minimal default so the TUI doesn't crash on missing theme.
    if not themes:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "no themes loaded from %s or %s — using built-in fallback",
            bundled_dir, user_dir,
        )
        themes["phosphor"] = Theme(
            name="phosphor",
            description="fallback (theme files not found)",
            primary="#00ff00",
            primary_dim="#008800",
            primary_faint="#004400",
            accent="#ffcc66",
            accent_dim="#aa7733",
            gradient=("#00aa00", "#22cc22", "#44ee44", "#66ff66", "#22cc22", "#008800"),
        )
    return themes


THEMES: dict[str, Theme] = _load_themes()


_active_theme: Theme = THEMES["phosphor"]

# Module-level color names. Bound to the active theme's values; the
# bindings are REASSIGNED inside ``set_theme()`` so internal call
# sites (``f"[{LIME}]…"`` inside this same module) see the new theme
# without going through a __getattr__ dance.
LIME: str = _active_theme.primary
LIME_DIM: str = _active_theme.primary_dim
LIME_FAINT: str = _active_theme.primary_faint
_OWL_AMBER: str = _active_theme.accent
_OWL_AMBER_DIM: str = _active_theme.accent_dim
_GRADIENT: tuple[str, ...] = _active_theme.gradient


def theme() -> Theme:
    """Return the currently active theme."""
    return _active_theme


def set_theme(name: str) -> Theme:
    """Switch the active theme. Raises KeyError on unknown name.
    Returns the newly active theme so callers can echo back.

    Rebinds the module-level ``LIME`` / ``LIME_DIM`` / ``LIME_FAINT``
    / ``_GRADIENT`` / ``_OWL_AMBER`` aliases so every subsequent
    ``ui.*`` call (banner, tool_call, info, panels) renders in the
    new palette without restarting athena.
    """
    global _active_theme, LIME, LIME_DIM, LIME_FAINT
    global _GRADIENT, _OWL_AMBER, _OWL_AMBER_DIM
    if name not in THEMES:
        avail = ", ".join(sorted(THEMES))
        raise KeyError(f"unknown theme {name!r}. Available: {avail}")
    _active_theme = THEMES[name]
    LIME = _active_theme.primary
    LIME_DIM = _active_theme.primary_dim
    LIME_FAINT = _active_theme.primary_faint
    _OWL_AMBER = _active_theme.accent
    _OWL_AMBER_DIM = _active_theme.accent_dim
    _GRADIENT = _active_theme.gradient
    return _active_theme


def list_themes() -> list[Theme]:
    """All registered themes, sorted by name."""
    return [THEMES[name] for name in sorted(THEMES)]


# ----------------------------------------------------------------------
# Gateway bridge. When ``set_gateway()`` has been called, ``info`` /
# ``warn`` / ``error`` / ``tool_call_summary`` / ``tool_result`` emit
# typed events on the JSON-RPC channel instead of rendering Rich
# directly. The Ink TUI consumes them. Without a gateway set, the
# legacy Rich path runs unchanged — that's what keeps the ``athena``
# CLI's existing modes (headless, gateway daemon, train, etc.) working
# while the migration is in flight.
# ----------------------------------------------------------------------

_active_gateway: Any | None = None

# Context flag that gates the ``console.print`` bridge. The bridge
# only emits MessageAppendEvent when this is True — slash command
# dispatch wraps its handler in ``user_facing_render()`` to opt
# in. Agent-internal code runs without the flag, so its noisy
# turn-time ``console.print`` calls go straight to devnull
# instead of polluting the transcript.
import contextvars as _ctxvars

_bridge_context: _ctxvars.ContextVar[bool] = _ctxvars.ContextVar(
    "athena_ui_bridge_console_print",
    default=False,
)


from contextlib import contextmanager as _contextmanager


@_contextmanager
def user_facing_render():
    """While this context is active, any ``console.print`` call
    is captured and shipped as MessageAppendEvent — so slash
    command output (``/help``, ``/board``, etc) shows up in the
    Ink transcript.

    Outside the context, ``console.print`` is silent in TUI
    mode. Use this to wrap user-initiated output regions; do
    NOT wrap ``agent.run_turn()`` or the model will spew
    internal logging into the transcript.
    """
    token = _bridge_context.set(True)
    try:
        yield
    finally:
        _bridge_context.reset(token)


def set_gateway(gateway: Any | None) -> None:
    """Activate (or clear) the Ink TUI gateway. Pass ``None`` to
    revert to direct Rich rendering. Idempotent.

    Post TUI sprint steps 6 + 7: silencing is **semantic only**.
    Two layers protect Ink's render from rich.print output that
    would otherwise corrupt it, but ``sys.stdout`` / ``sys.stderr``
    are NOT manipulated and file descriptors are NOT dup'd:

      0. ``console.print`` is replaced with a bridge that captures
         user-facing slash-command output (those that wrap their
         render in :func:`user_facing_render`) and ships it as
         ``MessageAppendEvent``. Outside that context, prints
         silently no-op so agent-internal turn-time chatter
         doesn't flood the transcript.
      1. ``console.file`` is redirected to ``os.devnull`` as a
         backstop for any Rich machinery (e.g. Rich.Live regions)
         that bypasses ``console.print``.

    What we deliberately do NOT do anymore:
      - Swap ``sys.stdout`` / ``sys.stderr`` to a null sink. Any
        raw ``print()`` call in the agent loop while Ink is
        active is now a bug to surface, not paper over.
      - dup2 fds 1+2 to /dev/null. Native libraries writing via
        raw file descriptors will visibly corrupt the Ink render
        — also a bug to surface.

    Why we kept layers 0 + 1: ~254 legacy ``console.print`` call
    sites haven't been migrated to typed gateway events; without
    this bridge they'd all break in TUI mode. Layers 2 + 3 (the
    FD-level silencing) were sledgehammer protection that hid
    bugs and complicated subprocess-fd inheritance reasoning.
    """
    import os as _os

    global _active_gateway, _saved_console_file, _saved_console_print
    _active_gateway = gateway
    if gateway is not None:
        # Layer 0: replace console.print with a bridge that
        # captures Rich's rendered text and ships it as a
        # MessageAppendEvent(role="system") inside
        # ``user_facing_render()`` blocks; silent no-op otherwise.
        if _saved_console_print is None:
            _saved_console_print = console.print
        console.print = _bridged_print  # type: ignore[assignment]
        # Layer 1: console.file → devnull so any Rich machinery
        # that bypasses .print() (Live regions, status spinners)
        # writes to the void instead of the terminal.
        if _saved_console_file is None:
            _saved_console_file = "saved"  # truthy sentinel
        try:
            console.file = open(_os.devnull, "w", encoding="utf-8")
        except OSError:
            pass
    else:
        # Restore in reverse order.
        if _saved_console_file is not None:
            try:
                console.file.close()
            except Exception:  # noqa: BLE001
                pass
            # Clearing ``_file`` makes Rich's Console.file
            # property resolve ``sys.stdout`` dynamically on
            # every access (via ``_get_default_file``). That's
            # the right behavior under pytest — capsys installs
            # a fresh sys.stdout per test, and a cached
            # console.file reference would point at the
            # previous test's (closed) capture buffer.
            console._file = None  # type: ignore[attr-defined]
            _saved_console_file = None
        if _saved_console_print is not None:
            # Remove the instance attribute we set so the
            # original class-level print method is used again.
            console.__dict__.pop("print", None)
            _saved_console_print = None


def _bridged_print(*args: Any, **kwargs: Any) -> None:
    """Replacement for ``console.print`` while the gateway is
    active.

    Only emits MessageAppendEvent when ``user_facing_render()``
    is in effect on the calling stack — that's how slash command
    output reaches the transcript without flooding it with the
    agent's internal turn-time logging (``[yellow]command:[/]``
    previews, "recovered N tool calls", etc).

    Outside the user-facing context: defers to the original
    Console.print, which writes to ``console.file = devnull``
    — i.e. silent, which is what we want for internal noise.
    """
    if not _bridge_context.get():
        # Internal logging or stray prints — keep them out of
        # the transcript. The console.file devnull redirect
        # silences the actual Rich render.
        if _saved_console_print is not None:
            return _saved_console_print(*args, **kwargs)
        return None
    gw = _active_gateway
    if gw is None or _saved_console_print is None:
        if _saved_console_print is not None:
            return _saved_console_print(*args, **kwargs)
        return None
    try:
        import io as _io

        from rich.console import Console as _RichConsole

        capture = _io.StringIO()
        capture_console = _RichConsole(
            file=capture,
            force_terminal=False,
            no_color=True,
            color_system=None,
            width=100,
            highlight=False,
            soft_wrap=True,
        )
        capture_console.print(*args, **kwargs)
        text = capture.getvalue().rstrip("\n")
        if not text:
            return None
        from .tui_gateway.events import MessageAppendEvent

        gw.send_event(MessageAppendEvent(role="system", content=text))
    except Exception:  # noqa: BLE001 — never break a print()
        return None


# Saved across set_gateway calls so we can restore the original
# console state when the TUI exits. Only console-level state is
# saved here; we no longer touch sys.stdout/sys.stderr or fds
# (see set_gateway docstring for the post-step-6+7 design).
_saved_console_file: Any = None
_saved_console_print: Any = None


def gateway() -> Any | None:
    """Inspector — returns the currently-active gateway or None."""
    return _active_gateway


def _emit_message(role: str, content: str) -> bool:
    """If a gateway is set, send a MessageAppendEvent and return
    True. Caller falls back to Rich on False."""
    gw = _active_gateway
    if gw is None:
        return False
    try:
        from .tui_gateway.events import MessageAppendEvent

        gw.send_event(MessageAppendEvent(role=role, content=content))
        return True
    except RuntimeError:
        # Gateway socket dead. Step 6 design: no mid-session
        # swap back to Rich. The recv_command loop will see EOF
        # shortly and __main__:_run_interactive_repl exits.
        # Drop this single event silently; subsequent calls will
        # take the same path until the loop notices the EOF.
        return False
    except Exception:  # noqa: BLE001 — gateway failures must not crash the agent
        return False


def _emit_flash(level: str, text: str) -> bool:
    """Ephemeral status — appears briefly above the prompt,
    decays without polluting the transcript. Used for ``info``
    and ``warn`` so internal agent logging doesn't interleave
    with the streaming assistant text."""
    gw = _active_gateway
    if gw is None:
        return False
    try:
        from .tui_gateway.events import StatusFlashEvent

        gw.send_event(StatusFlashEvent(text=text, level=level))  # type: ignore[arg-type]
        return True
    except RuntimeError:
        # See _emit_message — no mid-session swap.
        return False
    except Exception:  # noqa: BLE001
        return False


def info(msg: str) -> None:
    # In TUI mode: ephemeral toast above the prompt. In Rich
    # mode: console line as before.
    if _emit_flash("info", msg):
        return
    console.print(f"[{LIME_DIM}]·[/] [dim]{msg}[/]")


def warn(msg: str) -> None:
    # In TUI mode: ephemeral toast (level=warn). Persistent
    # failures should use ``ui.error`` instead.
    if _emit_flash("warn", msg):
        return
    console.print(f"[yellow]![/] [yellow]{msg}[/]")


def error(msg: str) -> None:
    # Errors stay in the transcript — they matter.
    if _emit_message("system", f"✗ {msg}"):
        return
    console.print(f"[red]{_X}[/] [red]{msg}[/]")


def tool_round_header() -> None:
    """Emit a visual separator between model reasoning rounds.

    Quieter than the prior ``── round 7 · 1 tool call ──`` form —
    the round number is technical noise and the tool count rarely
    tells the user anything they can't see from the tool lines
    that follow. A thin rule with the wall-clock time is enough to
    visually section the transcript without competing with content.
    """
    from datetime import datetime
    ts = datetime.now().strftime("%H:%M:%S")
    content = f"─── {ts} ───"
    if _emit_message("separator", content):
        return
    console.print(f"[{LIME_FAINT}]{content}[/]")


def tool_call_summary(name: str, args: dict) -> None:
    # Compact one-liner so the user sees what the model is doing
    args_str = ", ".join(f"{k}={_short(v)}" for k, v in args.items())
    gw = _active_gateway
    if gw is not None:
        try:
            from .tui_gateway.events import ToolStartEvent

            # Bug fix (post-sprint): use tool name as call_id so the
            # matching ToolCompleteEvent (also keyed by name) can be
            # paired by the TUI's reducer. Previously we used
            # f"{name}-{id(args)}" here and f"{name}-result" there,
            # which never matched — the spinner stayed on screen
            # forever. Trade-off: same-tool concurrent calls will
            # share a lane row. athena's agent loop runs tools
            # sequentially, so this is fine in practice.
            gw.send_event(
                ToolStartEvent(
                    call_id=name,
                    tool=name,
                    args_preview=args_str,
                )
            )
            return
        except Exception:  # noqa: BLE001
            pass
    console.print(
        f"[bold {LIME}]▰▰[/] [bold {LIME}]{name}[/][{LIME_DIM}]([/][dim]{args_str}[/][{LIME_DIM}])[/]"
    )


def _short(v, n: int = 60) -> str:
    s = repr(v)
    return s if len(s) <= n else s[: n - 1] + "…"


def _maybe_pretty_json(output: str) -> str:
    """Pretty-print ``output`` if it parses as a non-trivial JSON
    object or array. Pass through unchanged otherwise.

    Single-line JSON dumps from tools like ``search_x`` /
    ``browser_extract_text`` / status tools land in the transcript as
    a wall of escaped braces; pretty-printing makes them readable AND
    lets the line-based truncation in :func:`tool_result` do its job
    (without pretty-printing, the whole result is one giant "line"
    that can't be line-truncated).

    Heuristic — fast: only attempt parse if the trimmed text starts
    with ``{`` or ``[`` and ends with the matching closer. Avoids
    parsing arbitrary text just to find out it's not JSON.
    """
    s = output.strip()
    if not s or len(s) < 8:
        return output
    first, last = s[0], s[-1]
    if not ((first == "{" and last == "}") or (first == "[" and last == "]")):
        return output
    try:
        import json
        parsed = json.loads(s)
    except (ValueError, RecursionError):
        return output
    # Only re-render if it's a structure (object/array). Primitives
    # come back unchanged — no value in pretty-printing those.
    if not isinstance(parsed, (dict, list)):
        return output
    try:
        return json.dumps(parsed, indent=2, ensure_ascii=False)
    except (TypeError, ValueError):
        return output


def _summarize_tool_result(name: str, output: str) -> str:
    """Per-tool intelligent compression. Returns a shorter, more
    scannable version of ``output`` for high-frequency tools whose
    raw output is verbose. Falls back to the unchanged output for
    tools we don't recognize.

    The goal is the user shouldn't have to read a 12-line YAML dump
    to remember "I just viewed the python-typing-style skill" —
    one line stating that fact + the first few content lines is
    enough.
    """
    if not output:
        return output

    # skill_view / skill_manage(action=view) — frontmatter is 4-7
    # lines of YAML that the user rarely needs to re-read; collapse
    # to a one-liner with the skill name + description, then show
    # the first ~5 body lines.
    if name in ("skill_view", "skill_manage") and output.lstrip().startswith("---"):
        return _summarize_skill_md(output)

    # TaskCreate emits "(thought)-<uuid> created: <subject>". The
    # UUID prefix is internal bookkeeping and noise to the user.
    if name == "TaskCreate":
        m = re.match(r"^\([^)]+\)-[a-f0-9-]+\s+created:\s+(.*)$", output.strip())
        if m:
            return f"created: {m.group(1)}"

    # TaskUpdate emits "(thought)-<uuid> updated: <fields>" — same.
    if name == "TaskUpdate":
        m = re.match(r"^\([^)]+\)-[a-f0-9-]+\s+(updated|completed):\s+(.*)$", output.strip())
        if m:
            return f"{m.group(1)}: {m.group(2)}"

    return output


def _summarize_skill_md(output: str) -> str:
    """Collapse a SKILL.md dump (YAML frontmatter + body) into a
    one-line header + the first few body lines."""
    lines = output.splitlines()
    fm_close = -1
    if lines and lines[0].strip() == "---":
        for i, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                fm_close = i
                break
    if fm_close < 0:
        # Malformed — just return as-is, line truncation handles it
        return output
    # Parse frontmatter for name + description
    fm: dict[str, str] = {}
    for line in lines[1:fm_close]:
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip().strip("'\"")
    header_bits: list[str] = []
    if fm.get("name"):
        header_bits.append(fm["name"])
    if fm.get("description"):
        desc = fm["description"]
        if len(desc) > 120:
            desc = desc[:117] + "…"
        header_bits.append(desc)
    header = " · ".join(header_bits) if header_bits else "(skill)"
    # Body: skip the close-marker, drop leading blank lines
    body = lines[fm_close + 1:]
    while body and not body[0].strip():
        body.pop(0)
    body_shown = body[:5]
    body_more = len(body) - len(body_shown)
    out_lines = [header]
    out_lines.extend(body_shown)
    if body_more > 0:
        out_lines.append(f"… ({body_more} more body lines)")
    return "\n".join(out_lines)


def tool_result(name: str, output: str, max_lines: int = 12) -> None:
    # Escape rich markup in the tool output — arbitrary tool text may
    # contain characters like ``[/]``, ``[bold]``, or ``[red]`` that
    # rich's parser would otherwise interpret as markup tags and
    # crash on (MarkupError on unbalanced tags). Our own trailing
    # ``[dim]... (N more lines)[/]`` is concatenated AFTER the escape
    # so the suffix renders as styled text and the body renders as
    # literal characters. Without this, a tool that emits text like
    # ``str | None`` triggers MarkupError and kills the session.
    from rich.markup import escape as _markup_escape

    # Per-tool intelligent compression first (collapses YAML
    # frontmatter, strips UUID bookkeeping prefixes, etc).
    output = _summarize_tool_result(name, output)

    # Pretty-print JSON outputs (search_x, browser_*, status tools all
    # return one-line JSON dumps). Without this, line-based truncation
    # has nothing to truncate (one long line) and the user sees an
    # unreadable wall of escaped braces in the transcript.
    output = _maybe_pretty_json(output)

    lines = output.splitlines()
    shown = lines[:max_lines]
    body_truncated = "\n".join(shown)
    if len(lines) > max_lines:
        body_truncated += f"\n… ({len(lines) - max_lines} more lines)"

    gw = _active_gateway
    if gw is not None:
        try:
            from .tui_gateway.events import ToolCompleteEvent

            gw.send_event(
                ToolCompleteEvent(
                    # Matches the call_id ToolStartEvent used — see
                    # comment in tool_call_summary above.
                    call_id=name,
                    tool=name,
                    ok=True,
                    result_preview=body_truncated,
                )
            )
            return
        except Exception:  # noqa: BLE001
            pass

    body = _markup_escape("\n".join(shown))
    if len(lines) > max_lines:
        body += f"\n[dim]... ({len(lines) - max_lines} more lines)[/]"
    console.print(
        Panel(body, title=f"↳ {name}", border_style=LIME_FAINT, title_align="left", padding=(0, 1))
    )


def show_diff(path: str, old: str, new: str) -> None:
    diff = difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        n=2,
    )
    text = "".join(diff)
    if not text:
        # Surface "no changes" as a user-visible message —
        # this is tool feedback the user wants, regardless of
        # whether the bridge context is active.
        gw = _active_gateway
        if gw is not None:
            try:
                from .tui_gateway.events import MessageAppendEvent

                gw.send_event(
                    MessageAppendEvent(
                        role="system", content=f"(no changes to {path})"
                    )
                )
                return
            except Exception:  # noqa: BLE001
                pass
        console.print(f"[dim](no changes to {path})[/]")
        return
    gw = _active_gateway
    if gw is not None:
        # Ship the diff as a tool-style transcript entry so the
        # user sees what changed when an Edit/Write tool runs.
        # Plain text — Ink renders without Rich's Syntax styling
        # but the +/- markers are clear enough.
        try:
            from .tui_gateway.events import ToolCompleteEvent

            gw.send_event(
                ToolCompleteEvent(
                    call_id=f"diff-{path}",
                    tool=f"diff {path}",
                    ok=True,
                    result_preview=text,
                )
            )
            return
        except Exception:  # noqa: BLE001 — fall through to Rich
            pass
    console.print(Syntax(text, "diff", theme="ansi_dark", word_wrap=True))


_MARKDOWN_SIGNALS = ("```", "\n#", "\n- ", "\n* ", "\n1. ", "\n> ", "**", "`")


def _text_has_markdown(text: str) -> bool:
    """Heuristic: should we re-render the assembled reply as Markdown?

    Yes when the text has any of the obvious-payoff markers — fenced
    code blocks (which get syntax-highlighted), headings, lists,
    blockquotes, or inline emphasis. Pure prose stays as plain text
    because re-rendering would only churn the terminal.
    """
    if not text or len(text) < 8:
        return False
    return any(marker in text for marker in _MARKDOWN_SIGNALS)


def _strip_think_blocks(text: str) -> str:
    """Return ``text`` with ``<think>...</think>`` blocks replaced by a
    short marker. Used for the final markdown render so chain-of-
    thought doesn't appear in the polished view. Open / unclosed think
    blocks (rare on a clean finalize but possible on interrupt) get
    truncated at the opener.
    """
    import re as _re

    out = _re.sub(
        r"<think>.*?</think>\s*", "_(thought collapsed)_\n\n", text, flags=_re.DOTALL,
    )
    # Drop any trailing unclosed <think> block.
    idx = out.find("<think>")
    if idx != -1:
        out = out[:idx] + "_(thinking…)_"
    return out


class TypewriterStream:
    """Stream assistant text live via Rich.Live, swap to Markdown on
    finalize().

    Usage::

        tw = TypewriterStream(prefix="▌ ", prefix_style="bold #00ff00")
        tw.start()
        for chunk in stream:
            tw.feed(chunk)
        tw.finalize(markdown=True)

    The Live region renders growing plain Text while chunks arrive
    (so the user sees the model "type" in real time), then on
    ``finalize`` swaps the rendered content to a syntax-highlighted
    :class:`rich.markdown.Markdown` view when ``_text_has_markdown``
    detects code blocks / headings / lists. Plain-prose responses
    pass through with the same final newline they always had — no
    churn.
    """

    def __init__(
        self,
        *,
        prefix: str = "",
        prefix_style: str = "",
        refresh_per_second: int = 24,
    ) -> None:
        self._prefix = prefix
        self._prefix_style = prefix_style
        self._refresh = refresh_per_second
        self._buf = ""
        self._live: Live | None = None
        self._closed = False
        # Gateway-bridge state. When ``set_gateway()`` is active, the
        # stream events ride the JSON-RPC channel instead of rendering
        # Rich.Live. Recorded at start() so a mid-stream gateway swap
        # doesn't desync the stream_id.
        self._gateway: Any | None = None
        self._stream_id: str | None = None

    def _renderable(self, body: str):
        text = Text()
        if self._prefix:
            text.append(self._prefix, style=self._prefix_style or "")
        self._append_with_think_collapse(text, body)
        return text

    def _append_with_think_collapse(self, text: "Text", body: str) -> None:
        """Append ``body`` to ``text``, collapsing ``<think>...</think>``
        blocks (qwen / reasoning-model CoT) into a dim marker.

        Why: showing raw thought tags pollutes the visible output with
        the model's chain-of-thought, which the user usually doesn't
        want to read. Collapsing keeps the streaming UI alive (so the
        user knows the model is doing something) without leaking the
        full reasoning trace.

        Behavior:
          - Closed ``<think>...</think>`` block → ``· (thought)`` dim italic
          - Open ``<think>`` (mid-stream, not closed yet) → ``· thinking…``
            dim italic, and everything after the open tag is suppressed
            until the close tag arrives.
          - No think tags → original text appended verbatim.
        """
        pos = 0
        while True:
            open_idx = body.find("<think>", pos)
            if open_idx == -1:
                text.append(body[pos:])
                return
            # Text before the open tag passes through verbatim.
            text.append(body[pos:open_idx])
            close_idx = body.find("</think>", open_idx)
            if close_idx == -1:
                # Open block not yet closed — model is mid-thinking.
                text.append("· thinking…", style="dim italic")
                return
            # Closed block — past-tense marker.
            text.append("· (thought)", style="dim italic")
            pos = close_idx + len("</think>")

    def start(self) -> None:
        if self._live is not None or self._stream_id is not None or self._closed:
            return
        # Gateway path: emit a StreamStartEvent. Rich.Live stays off.
        gw = _active_gateway
        if gw is not None:
            self._gateway = gw
            import uuid as _uuid

            self._stream_id = _uuid.uuid4().hex
            try:
                from .tui_gateway.events import StreamStartEvent

                gw.send_event(
                    StreamStartEvent(stream_id=self._stream_id)
                )
                return
            except Exception:  # noqa: BLE001 — fall back to Rich
                self._gateway = None
                self._stream_id = None
        # Fallback Rich.Live path (no gateway active).
        self._live = Live(
            self._renderable(""),
            console=console,
            refresh_per_second=self._refresh,
            transient=False,
            auto_refresh=True,
        )
        self._live.__enter__()

    def feed(self, chunk: str) -> None:
        if (
            self._live is None
            and self._stream_id is None
            and not self._closed
        ):
            self.start()
        self._buf += chunk
        if self._stream_id is not None and self._gateway is not None:
            try:
                from .tui_gateway.events import StreamDeltaEvent

                self._gateway.send_event(
                    StreamDeltaEvent(stream_id=self._stream_id, text=chunk)
                )
                return
            except Exception:  # noqa: BLE001 — let next feed retry or finalize close
                pass
        if self._live is not None:
            self._live.update(self._renderable(self._buf))

    def finalize(self, *, markdown: bool) -> str:
        """Stop the Live region. If ``markdown`` and the buffered text
        contains markdown features, re-render as Rich.Markdown so the
        final view in the terminal is the polished one. Returns the
        full streamed text — INCLUDING the original ``<think>`` content
        (callers like history persistence get the raw model output;
        only the on-screen render strips the thoughts)."""
        if self._closed:
            return self._buf
        text = self._buf
        # Gateway path: emit StreamEnd, nothing else to clean up.
        if self._stream_id is not None and self._gateway is not None:
            try:
                from .tui_gateway.events import StreamEndEvent

                self._gateway.send_event(
                    StreamEndEvent(stream_id=self._stream_id)
                )
            except Exception:  # noqa: BLE001
                pass
            self._stream_id = None
            self._gateway = None
            self._closed = True
            return text
        if self._live is not None:
            # Visible-only copy with think blocks stripped — used for
            # the final Live frame so the polished view isn't polluted.
            visible = _strip_think_blocks(text)
            if markdown and _text_has_markdown(visible):
                self._live.update(Markdown(visible))
            else:
                # Re-render the plain typewriter view one last time so
                # the final frame shows the collapsed think markers
                # consistently with what the streaming pass displayed.
                self._live.update(self._renderable(text))
            self._live.__exit__(None, None, None)
            self._live = None
            if text and not text.endswith("\n"):
                console.print()
        self._closed = True
        return text


_SPARK_BARS = "▁▂▃▄▅▆▇█"
_tps_history: list[float] = []
_TPS_HISTORY_MAX = 30


def confirm(
    prompt: str, default: bool = False,
    *,
    tool_name: str | None = None,
    preview: str | None = None,
    preview_kind: str | None = None,
) -> bool:
    """Yes/no prompt. In TUI mode, ships ``ConfirmRequestEvent``
    to Ink and blocks on a queue waiting for the user's reply —
    NEVER calls ``input()`` directly because Ink owns stdin and
    that would deadlock both processes.

    Optional rich-preview fields let safety-tier callers (Bash, Edit,
    Write approvals) show the user WHAT is about to happen, not
    just "Run X?". ``preview_kind`` selects rendering style on the
    TUI side: ``"command"`` / ``"diff"`` / ``"file"`` / ``"text"``.
    """
    gw = _active_gateway
    if gw is not None:
        return _confirm_via_gateway(
            gw, prompt, default,
            tool_name=tool_name, preview=preview, preview_kind=preview_kind,
        )
    # Legacy Rich path — direct stdin read. Print the preview here
    # too so non-TUI users still see what they're approving.
    if preview:
        console.print()
        if tool_name:
            console.print(f"[bold cyan]── {tool_name} ──[/]")
        console.print(preview)
        console.print(f"[bold cyan]{'─' * 4}[/]")
    suffix = "[Y/n]" if default else "[y/N]"
    try:
        ans = input(f"{prompt} {suffix} ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        console.print()
        return False
    if not ans:
        return default
    return ans in ("y", "yes")


def _confirm_via_gateway(
    gw: Any, prompt: str, default: bool,
    *,
    tool_name: str | None = None,
    preview: str | None = None,
    preview_kind: str | None = None,
) -> bool:
    """Ship a ConfirmRequestEvent and wait up to 5 minutes for a
    matching ConfirmReplyCommand. On timeout / error / interrupt,
    fall back to ``default`` so a misbehaving TUI can't hang the
    agent indefinitely."""
    import queue as _queue
    import uuid as _uuid

    request_id = _uuid.uuid4().hex
    reply_q: _queue.Queue[bool] = _queue.Queue(maxsize=1)
    _pending_confirms[request_id] = reply_q
    try:
        from .tui_gateway.events import ConfirmRequestEvent

        gw.send_event(
            ConfirmRequestEvent(
                request_id=request_id, prompt=prompt, default=default,
                tool_name=tool_name, preview=preview, preview_kind=preview_kind,
            )
        )
    except Exception:  # noqa: BLE001
        _pending_confirms.pop(request_id, None)
        return default
    try:
        return reply_q.get(timeout=300.0)
    except _queue.Empty:
        return default
    except (KeyboardInterrupt, SystemExit):
        return False
    finally:
        _pending_confirms.pop(request_id, None)


def _deliver_confirm_reply(request_id: str, accepted: bool) -> None:
    """Hand a reply back to the waiting ``_confirm_via_gateway``
    call. Called by the REPL loop in ``__main__.py`` when it sees
    a ``ConfirmReplyCommand`` come through the gateway."""
    import queue as _queue

    q = _pending_confirms.get(request_id)
    if q is None:
        return  # request already timed out or was cancelled
    try:
        q.put_nowait(accepted)
    except _queue.Full:
        pass


# Pending confirm requests keyed by request_id. Each waits on a
# 1-slot Queue; the reply command pushes into it and the
# ``confirm()`` call unblocks.
_pending_confirms: dict[str, Any] = {}
