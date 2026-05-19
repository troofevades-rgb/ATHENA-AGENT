"""Rich terminal UI helpers — confirmation prompts, diff rendering, status."""

from __future__ import annotations

import difflib
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

# Electric-lime palette. Truecolor; falls back gracefully on 256-color terms.
LIME = "#00ff00"
LIME_DIM = "#008800"
LIME_FAINT = "#004400"

# Gradient stops walked top-to-bottom across the banner. Phosphor green
# fades into a lime highlight in the middle then back down — gives the
# ASCII art a slight 3D feel without resorting to background fills.
_GRADIENT = ("#00aa00", "#22cc22", "#44ee44", "#66ff66", "#22cc22", "#008800")


# ATHENA-AGENT in pyfiglet's ``ansi_shadow`` font. 101 chars wide,
# 6 rows tall — single-line render. Modern dev terminals default
# to ≥100 cols (Windows Terminal: 120, iTerm2: 80→user-resized,
# most IDE terminals: 100+) so this fits on a single line in
# practice. Genuinely narrow terminals will wrap; that's a
# user-side problem the previous adaptive-stack code papered over
# at the cost of looking inconsistent across sessions.
_ATHENA_AGENT = (
    " █████╗ ████████╗██╗  ██╗███████╗███╗   ██╗ █████╗        █████╗  ██████╗ ███████╗███╗   ██╗████████╗\n"
    "██╔══██╗╚══██╔══╝██║  ██║██╔════╝████╗  ██║██╔══██╗      ██╔══██╗██╔════╝ ██╔════╝████╗  ██║╚══██╔══╝\n"
    "███████║   ██║   ███████║█████╗  ██╔██╗ ██║███████║█████╗███████║██║  ███╗█████╗  ██╔██╗ ██║   ██║   \n"
    "██╔══██║   ██║   ██╔══██║██╔══╝  ██║╚██╗██║██╔══██║╚════╝██╔══██║██║   ██║██╔══╝  ██║╚██╗██║   ██║   \n"
    "██║  ██║   ██║   ██║  ██║███████╗██║ ╚████║██║  ██║      ██║  ██║╚██████╔╝███████╗██║ ╚████║   ██║   \n"
    "╚═╝  ╚═╝   ╚═╝   ╚═╝  ╚═╝╚══════╝╚═╝  ╚═══╝╚═╝  ╚═╝      ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝   "
)

# Spray-line matches the banner width so it looks like a single
# nameplate. 99 cells of ▒/▓/█ with fade caps.
_SPRAY = (
    "░▒▓████████████████████████████████████████████████"
    "█████████████████████████████████████████████▓▒░"
)


def _gradient_text(art: str) -> Text:
    """Apply the vertical gradient across the ASCII-art's rows."""
    lines = art.splitlines()
    text = Text()
    n = max(len(lines) - 1, 1)
    for i, line in enumerate(lines):
        # Pick a gradient stop proportional to the row's position.
        idx = int(round(i / n * (len(_GRADIENT) - 1)))
        text.append(line + "\n", style=f"bold {_GRADIENT[idx]}")
    return text


def _model_color(model: str) -> str:
    """Map a model id to a tier-specific accent color so glancing at
    the banner tells you what's running. Hosted high-tier = magenta,
    hosted mid-tier = cyan, local = dim lime."""
    m = (model or "").lower()
    if "opus" in m or "gpt-5" in m and "mini" not in m:
        return "#ff66ff"
    if "sonnet" in m or "gpt-4" in m or "gemini-2" in m:
        return "#66e0ff"
    if "haiku" in m or "mini" in m or "flash" in m:
        return "#ffcc66"
    # Default: local / unrecognized — phosphor lime.
    return LIME


def banner(model: str, workspace: Path) -> None:
    console.print()
    console.print(_gradient_text(_ATHENA_AGENT))
    console.print(Text(_SPRAY, style=LIME_DIM))
    accent = _model_color(model)
    console.print(
        Text.from_markup(
            f"  [bold {LIME}]▰[/] [{LIME}]model[/]  [bold {accent}]{model}[/]\n"
            f"  [bold {LIME}]▰[/] [{LIME}]cwd[/]    [white]{workspace}[/]\n"
            f"  [bold {LIME}]▰[/] [{LIME_DIM}]/help · /status · /cost · /plan · /exit[/]"
        )
    )
    console.print()


def info(msg: str) -> None:
    console.print(f"[{LIME_DIM}]·[/] [dim]{msg}[/]")


def warn(msg: str) -> None:
    console.print(f"[yellow]![/] [yellow]{msg}[/]")


def error(msg: str) -> None:
    console.print(f"[red]{_X}[/] [red]{msg}[/]")


def tool_call_summary(name: str, args: dict) -> None:
    # Compact one-liner so the user sees what the model is doing
    args_str = ", ".join(f"{k}={_short(v)}" for k, v in args.items())
    console.print(
        f"[bold {LIME}]▰▰[/] [bold {LIME}]{name}[/][{LIME_DIM}]([/][dim]{args_str}[/][{LIME_DIM}])[/]"
    )


def _short(v, n: int = 60) -> str:
    s = repr(v)
    return s if len(s) <= n else s[: n - 1] + "…"


def tool_result(name: str, output: str, max_lines: int = 12) -> None:
    lines = output.splitlines()
    shown = lines[:max_lines]
    body = "\n".join(shown)
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
        console.print(f"[dim](no changes to {path})[/]")
        return
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

    def _renderable(self, body: str):
        text = Text()
        if self._prefix:
            text.append(self._prefix, style=self._prefix_style or "")
        text.append(body)
        return text

    def start(self) -> None:
        if self._live is not None or self._closed:
            return
        self._live = Live(
            self._renderable(""),
            console=console,
            refresh_per_second=self._refresh,
            transient=False,
            auto_refresh=True,
        )
        self._live.__enter__()

    def feed(self, chunk: str) -> None:
        if self._live is None and not self._closed:
            self.start()
        self._buf += chunk
        if self._live is not None:
            self._live.update(self._renderable(self._buf))

    def finalize(self, *, markdown: bool) -> str:
        """Stop the Live region. If ``markdown`` and the buffered text
        contains markdown features, re-render as Rich.Markdown so the
        final view in the terminal is the polished one. Returns the
        full streamed text."""
        if self._closed:
            return self._buf
        text = self._buf
        if self._live is not None:
            if markdown and _text_has_markdown(text):
                # Swap to Markdown before closing so the in-place
                # Live region rewrites with the rendered view (rather
                # than printing twice).
                self._live.update(Markdown(text))
            self._live.__exit__(None, None, None)
            self._live = None
            # Live writes the final frame on exit; add the trailing
            # newline by hand for spacing parity with the prior
            # console.print-based path.
            if text and not text.endswith("\n"):
                console.print()
        self._closed = True
        return text


_SPARK_BARS = "▁▂▃▄▅▆▇█"
_tps_history: list[float] = []
_TPS_HISTORY_MAX = 30


def _sparkline(values: list[float], *, width: int = 12) -> str:
    """Render a unicode sparkline. Empty / single-value sequences
    return a centered dot so the footer doesn't visibly resize."""
    if not values:
        return "·" * width
    sample = values[-width:]
    mn, mx = min(sample), max(sample)
    span = mx - mn
    out: list[str] = []
    for v in sample:
        if span <= 0:
            idx = len(_SPARK_BARS) // 2
        else:
            idx = int(round((v - mn) / span * (len(_SPARK_BARS) - 1)))
        out.append(_SPARK_BARS[max(0, min(len(_SPARK_BARS) - 1, idx))])
    # Left-pad with the lowest bar so a young session shows a growing
    # sparkline instead of a left-justified one that looks unfinished.
    if len(out) < width:
        out = [_SPARK_BARS[0]] * (width - len(out)) + out
    return "".join(out)


def stream_stats(raw: dict) -> None:
    """One-line tokens/sec footer with a session-wide sparkline of
    throughput. Reads Ollama's ``eval_count`` / ``eval_duration``
    when present; falls back to the OpenAI-style usage chunk's
    ``completion_tokens`` (no per-call duration means tps is omitted)."""
    eval_count = raw.get("eval_count") or raw.get("completion_tokens") or 0
    eval_duration = raw.get("eval_duration") or 0  # nanoseconds
    prompt_count = raw.get("prompt_eval_count") or raw.get("prompt_tokens") or 0
    if eval_count and eval_duration:
        secs = eval_duration / 1e9
        tps = eval_count / secs if secs > 0 else 0
        _tps_history.append(tps)
        del _tps_history[: max(0, len(_tps_history) - _TPS_HISTORY_MAX)]
        spark = _sparkline(_tps_history)
        console.print(
            f"[{LIME_DIM}]→ {eval_count} tok · {secs:.1f}s · "
            f"{tps:.1f} tok/s [{LIME}]{spark}[/{LIME}][{LIME_DIM}] · "
            f"prompt {prompt_count} tok[/]"
        )
    elif eval_count or prompt_count:
        # Hosted providers usually don't report per-call duration; show
        # the counts without the tps/sparkline so the footer doesn't
        # mislead.
        console.print(f"[{LIME_DIM}]→ {eval_count} tok · prompt {prompt_count} tok[/]")


_MODEL_PRICING_PER_MILLION: dict[str, tuple[float, float]] = {
    # (input USD per 1M tokens, output USD per 1M tokens). Conservative
    # values from the providers' published rate cards; absent models
    # render the price column as "—" without breaking the toolbar.
    "claude-opus-4-7": (15.0, 75.0),
    "claude-opus-4": (15.0, 75.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-sonnet-4": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "gpt-5": (5.0, 20.0),
    "gpt-5-mini": (0.5, 2.0),
    "gpt-4o": (2.5, 10.0),
    "gemini-2.5-pro": (1.25, 5.0),
    "gemini-2.5-flash": (0.075, 0.30),
}


def _price_for(model: str) -> tuple[float, float] | None:
    if not model:
        return None
    m = model.lower()
    # Strip any routing prefix (anthropic/, openai/, etc.)
    if "/" in m:
        m = m.split("/", 1)[1]
    # Exact match first, then prefix match for tagged variants like
    # ``claude-sonnet-4-6@20260101``.
    if m in _MODEL_PRICING_PER_MILLION:
        return _MODEL_PRICING_PER_MILLION[m]
    for key, price in _MODEL_PRICING_PER_MILLION.items():
        if m.startswith(key):
            return price
    return None


def estimated_cost_usd(model: str, prompt_tokens: int, eval_tokens: int) -> float:
    """Best-effort cost estimate; returns 0.0 for unknown / local models."""
    price = _price_for(model)
    if price is None:
        return 0.0
    in_per_m, out_per_m = price
    return (prompt_tokens * in_per_m + eval_tokens * out_per_m) / 1_000_000.0


def _format_duration(seconds: float) -> str:
    seconds = max(0.0, seconds)
    if seconds < 60:
        return f"{int(seconds)}s"
    m, s = divmod(int(seconds), 60)
    if m < 60:
        return f"{m}m{s:02d}s"
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m"


def _format_tool_histogram(counts: dict[str, int], *, limit: int = 3) -> str:
    """Compact ``Read 2 / Edit 1 / Write 1`` style summary."""
    if not counts:
        return "no tools yet"
    items = sorted(counts.items(), key=lambda kv: -kv[1])[:limit]
    return " / ".join(f"{name} {count}" for name, count in items)


def build_bottom_toolbar(agent: Any) -> Callable[[], str]:
    """Return a ``prompt_toolkit`` bottom_toolbar callable that
    renders a live status line: model · profile · elapsed · tokens
    · cost · tool histogram. The closure reads from the live
    ``agent`` and ``agent.stats`` so each redraw shows current
    numbers without polling."""
    from prompt_toolkit.formatted_text import HTML

    def _render() -> HTML:
        stats = agent.stats
        elapsed = _format_duration(time.time() - stats.started)
        model = agent.model
        profile = agent.cfg.profile or "default"
        prompt_tokens = stats.prompt_tokens
        eval_tokens = stats.eval_tokens
        cost = estimated_cost_usd(model, prompt_tokens, eval_tokens)
        cost_str = f"${cost:.4f}" if cost > 0 else "—"
        tool_hist = _format_tool_histogram(stats.tool_call_counts)
        # prompt_toolkit's HTML supports a limited tag set; use named
        # colors that map across the ansi-16 palette. Lime is bg=ansigreen.
        return HTML(
            f" <ansigreen><b>▰▰</b></ansigreen>"
            f" <b>{model}</b>"
            f" · <ansigreen>{profile}</ansigreen>"
            f" · {elapsed}"
            f" · <ansiblue>↑</ansiblue>{prompt_tokens:,}"
            f" <ansicyan>↓</ansicyan>{eval_tokens:,}"
            f" · <ansiyellow>{cost_str}</ansiyellow>"
            f" · <ansibrightblack>{tool_hist}</ansibrightblack>"
        )

    return _render


def live_status(agent: Any) -> None:
    """Real-time TUI dashboard for the active agent.

    Four panels in a 2×2 layout: counters, tool histogram, last-reply
    preview, recent snapshots from the Phase 17 store. Refreshes
    twice per second until the user presses ``q`` or ``Ctrl+C``.
    Falls back to the static :func:`render_status` text when run on
    a non-TTY terminal (CI capture, pipe, etc.).
    """
    from rich.layout import Layout
    from rich.table import Table

    # Non-TTY: just dump the static snapshot once and return so log
    # captures don't fill with refresh frames.
    if not console.is_terminal:
        from .cli.status import render_status

        snapshot = agent.stats.to_snapshot(
            session_id=agent.session_id,
            model=agent.model,
            provider=getattr(agent.provider, "name", "?"),
            profile=(agent.cfg.profile or "default"),
        )
        console.print(render_status(snapshot))
        return

    def _counters_panel() -> Panel:
        stats = agent.stats
        cost = estimated_cost_usd(
            agent.model,
            stats.prompt_tokens,
            stats.eval_tokens,
        )
        cost_str = f"${cost:.4f}" if cost > 0 else "—"
        t = Table.grid(padding=(0, 1))
        t.add_column(style=LIME_DIM, justify="right")
        t.add_column()
        t.add_row("model", f"[bold {_model_color(agent.model)}]{agent.model}[/]")
        t.add_row("profile", agent.cfg.profile or "default")
        t.add_row("session", (agent.session_id or "n/a")[:8])
        t.add_row("elapsed", _format_duration(time.time() - stats.started))
        t.add_row("turns", str(stats.turns))
        t.add_row(
            "tokens",
            f"[ansiblue]↑[/]{stats.prompt_tokens:,} [ansicyan]↓[/]{stats.eval_tokens:,}",
        )
        t.add_row("cost", f"[yellow]{cost_str}[/]")
        return Panel(t, title="counters", border_style=LIME_FAINT, padding=(1, 1))

    def _tools_panel() -> Panel:
        counts = agent.stats.tool_call_counts
        if not counts:
            body = "[dim](no tool calls yet)[/]"
            return Panel(body, title="tools", border_style=LIME_FAINT, padding=(1, 1))
        t = Table.grid(padding=(0, 1))
        t.add_column()
        t.add_column(justify="right")
        # Sorted by count desc, with a tiny lime bar showing relative weight.
        max_count = max(counts.values())
        for name, count in sorted(counts.items(), key=lambda kv: -kv[1]):
            bar_len = max(1, int(round(count / max_count * 18)))
            bar = "█" * bar_len
            t.add_row(name, f"[{LIME}]{bar}[/] [bold]{count}[/]")
        return Panel(t, title="tools", border_style=LIME_FAINT, padding=(1, 1))

    def _reply_panel() -> Panel:
        try:
            text = agent.last_assistant_message() or "[dim](no replies yet)[/]"
        except Exception:
            text = "[dim](unavailable)[/]"
        if len(text) > 400:
            text = text[:397] + "…"
        return Panel(
            text,
            title="last assistant message",
            border_style=LIME_FAINT,
            padding=(1, 1),
        )

    def _snapshots_panel() -> Panel:
        try:
            from .safety.context import get_snapshot_store

            store = get_snapshot_store()
            snaps = store.list_snapshots(limit=6)
        except Exception:
            snaps = []
        if not snaps:
            body = "[dim](no snapshots yet)[/]"
            return Panel(
                body,
                title="recent snapshots",
                border_style=LIME_FAINT,
                padding=(1, 1),
            )
        t = Table.grid(padding=(0, 1))
        t.add_column(style=LIME_DIM)
        t.add_column()
        t.add_column()
        for s in snaps:
            t.add_row(
                s.created_at.strftime("%H:%M:%S"),
                s.write_origin,
                (s.tool_name or "-")[:14],
            )
        return Panel(
            t,
            title="recent snapshots",
            border_style=LIME_FAINT,
            padding=(1, 1),
        )

    def _render() -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="top", ratio=1),
            Layout(name="bot", ratio=1),
        )
        layout["top"].split_row(
            Layout(_counters_panel(), name="counters"),
            Layout(_tools_panel(), name="tools"),
        )
        layout["bot"].split_row(
            Layout(_reply_panel(), name="reply"),
            Layout(_snapshots_panel(), name="snapshots"),
        )
        return layout

    console.print("[dim](press Ctrl+C to exit live status)[/]")
    try:
        with Live(_render(), console=console, refresh_per_second=2, screen=False) as live:
            while True:
                time.sleep(0.5)
                live.update(_render())
    except KeyboardInterrupt:
        console.print()


def confirm(prompt: str, default: bool = False) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    try:
        ans = input(f"{prompt} {suffix} ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        console.print()
        return False
    if not ans:
        return default
    return ans in ("y", "yes")
