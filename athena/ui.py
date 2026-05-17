"""Rich terminal UI helpers — confirmation prompts, diff rendering, status."""
from __future__ import annotations
import difflib
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text


console = Console()

# Electric-lime palette. Truecolor; falls back gracefully on 256-color terms.
LIME = "#00ff00"
LIME_DIM = "#008800"
LIME_FAINT = "#004400"


_ATHENA_ART = (
    " █████╗ ████████╗██╗  ██╗███████╗███╗   ██╗ █████╗ \n"
    "██╔══██╗╚══██╔══╝██║  ██║██╔════╝████╗  ██║██╔══██╗\n"
    "███████║   ██║   ███████║█████╗  ██╔██╗ ██║███████║\n"
    "██╔══██║   ██║   ██╔══██║██╔══╝  ██║╚██╗██║██╔══██║\n"
    "██║  ██║   ██║   ██║  ██║███████╗██║ ╚████║██║  ██║\n"
    "╚═╝  ╚═╝   ╚═╝   ╚═╝  ╚═╝╚══════╝╚═╝  ╚═══╝╚═╝  ╚═╝"
)
_SPRAY = "░▒▓██████████████████████████████████████████████▓▒░"


def banner(model: str, workspace: Path) -> None:
    console.print()
    console.print(Text(_ATHENA_ART, style=f"bold {LIME}"))
    console.print(Text(_SPRAY, style=LIME_DIM))
    console.print(Text.from_markup(
        f"  [bold {LIME}]▰[/] [{LIME}]model[/]  [white]{model}[/]\n"
        f"  [bold {LIME}]▰[/] [{LIME}]cwd[/]    [white]{workspace}[/]\n"
        f"  [bold {LIME}]▰[/] [{LIME_DIM}]/help · /exit · /clear · /plan[/]"
    ))
    console.print()


def info(msg: str) -> None:
    console.print(f"[{LIME_DIM}]·[/] [dim]{msg}[/]")


def warn(msg: str) -> None:
    console.print(f"[yellow]![/] [yellow]{msg}[/]")


def error(msg: str) -> None:
    console.print(f"[red]✗[/] [red]{msg}[/]")


def tool_call_summary(name: str, args: dict) -> None:
    # Compact one-liner so the user sees what the model is doing
    args_str = ", ".join(f"{k}={_short(v)}" for k, v in args.items())
    console.print(f"[bold {LIME}]▰▰[/] [bold {LIME}]{name}[/][{LIME_DIM}]([/][dim]{args_str}[/][{LIME_DIM}])[/]")


def _short(v, n: int = 60) -> str:
    s = repr(v)
    return s if len(s) <= n else s[: n - 1] + "…"


def tool_result(name: str, output: str, max_lines: int = 12) -> None:
    lines = output.splitlines()
    shown = lines[:max_lines]
    body = "\n".join(shown)
    if len(lines) > max_lines:
        body += f"\n[dim]... ({len(lines) - max_lines} more lines)[/]"
    console.print(Panel(body, title=f"↳ {name}", border_style=LIME_FAINT, title_align="left", padding=(0, 1)))


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


def stream_stats(raw: dict) -> None:
    """One-line tokens/sec footer from an Ollama /api/chat done chunk."""
    eval_count = raw.get("eval_count") or 0
    eval_duration = raw.get("eval_duration") or 0  # nanoseconds
    prompt_count = raw.get("prompt_eval_count") or 0
    if eval_count and eval_duration:
        secs = eval_duration / 1e9
        tps = eval_count / secs if secs > 0 else 0
        console.print(
            f"[{LIME_DIM}]→ {eval_count} tok · {secs:.1f}s · {tps:.1f} tok/s · "
            f"prompt {prompt_count} tok[/]"
        )


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
