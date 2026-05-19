"""``athena model {list,switch,info}``.

``list`` shows every Ollama model on the local box. ``switch`` updates
the user-level ``config.toml`` so subsequent athena sessions use the new
default model. ``info`` is a thin wrapper around ``ollama show`` for
when the user wants Modelfile metadata.

Sessions already in flight aren't affected by ``switch`` — they bind to
whichever model they started with. This is on purpose: an in-flight
training run that completed mid-session shouldn't suddenly speak with a
different voice.
"""

from __future__ import annotations

import argparse
import sys

from ..config import CONFIG_PATH
from ..transform.deploy import (
    ensure_ollama,
    list_local_models,
    show_model,
    switch_model,
)


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="athena model")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="List local Ollama models.")
    p_switch = sub.add_parser(
        "switch",
        help="Set the default model for new sessions (writes ~/.athena/config.toml).",
    )
    p_switch.add_argument("name")
    p_info = sub.add_parser("info", help="Show a model's Modelfile metadata.")
    p_info.add_argument("name")
    return ap


def _cmd_list() -> int:
    if not ensure_ollama():
        print("error: 'ollama' not found on PATH", file=sys.stderr)
        return 2
    models = list_local_models()
    if not models:
        print("(no local Ollama models)")
        return 0
    widths = [
        max(len(m["name"]) for m in models),
        max(len(m["id"]) for m in models),
        max(len(m["size"]) for m in models),
    ]
    for m in models:
        print(
            f"  {m['name'].ljust(widths[0])}  {m['id'].ljust(widths[1])}  "
            f"{m['size'].ljust(widths[2])}  {m['modified_at']}"
        )
    return 0


def _cmd_switch(name: str) -> int:
    if not ensure_ollama():
        print(
            "warning: 'ollama' not found on PATH — config will still be "
            "updated but the new model may not exist locally",
            file=sys.stderr,
        )
    switch_model(CONFIG_PATH, name)
    print(f"default model set to {name!r} in {CONFIG_PATH}")
    return 0


def _cmd_info(name: str) -> int:
    if not ensure_ollama():
        print("error: 'ollama' not found on PATH", file=sys.stderr)
        return 2
    out = show_model(name)
    if not out:
        print(f"error: 'ollama show {name}' returned no output", file=sys.stderr)
        return 1
    print(out)
    return 0


def main(argv: list[str]) -> int:
    args = _build_parser().parse_args(argv)
    if args.cmd == "list":
        return _cmd_list()
    if args.cmd == "switch":
        return _cmd_switch(args.name)
    if args.cmd == "info":
        return _cmd_info(args.name)
    return 2
