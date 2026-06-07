"""``athena recall {backfill,status,clear}`` — vector index admin (T6-01.3).

T6-01 added incremental embedding of new turns + memory entries
on write. For existing history written before semantic recall was
enabled (or after a model swap), this CLI does the one-time
bulk embed.

Subcommands:

  athena recall backfill [--profile NAME]
        Walk every session in the profile's SessionStore + embed
        each turn that isn't already in the index. Memory entries
        for the active profile are embedded too. Idempotent —
        re-runs only embed new docs.

  athena recall status [--json]
        List counts: total vectors, by model, by workspace.

  athena recall clear
        Wipe the vector index (the embeddings cost a fresh
        backfill to restore; useful when switching embedding
        models without keeping legacy vectors around).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import cast

from ..config import load_config, profile_dir
from ..recall import VectorStore, build_vector_store


def _store(args: argparse.Namespace) -> tuple[VectorStore | None, Path]:
    cfg = load_config()
    profile = getattr(args, "profile", None) or cfg.profile or "default"
    pdir = profile_dir(profile)
    store = build_vector_store(cfg=cfg, profile_dir=pdir)
    return store, pdir


def cmd_backfill(args: argparse.Namespace) -> int:
    store, pdir = _store(args)
    if store is None:
        sys.stderr.write(
            "no embeddings backend configured (semantic recall disabled "
            "or no provider declares the embeddings capability). "
            "Install a local embedding model (e.g. via Ollama) and retry.\n"
        )
        return 1

    n_turns = _backfill_sessions(store, pdir)
    n_mem = _backfill_memory(store, pdir, args)
    sys.stdout.write(f"backfilled {n_turns} session turn(s) + {n_mem} memory entry(ies)\n")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    store, _ = _store(args)
    if store is None:
        sys.stdout.write("(no embeddings backend; semantic recall disabled)\n")
        return 0
    entries = store.all()
    if args.json:
        by_model: dict[str, int] = {}
        by_workspace: dict[str, int] = {}
        for e in entries:
            by_model[e.model_id] = by_model.get(e.model_id, 0) + 1
            by_workspace[e.workspace] = by_workspace.get(e.workspace, 0) + 1
        sys.stdout.write(
            json.dumps(
                {
                    "total": len(entries),
                    "by_model": by_model,
                    "by_workspace": by_workspace,
                    "path": str(store.path),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        return 0
    sys.stdout.write(f"{len(entries)} vector(s) at {store.path}\n")
    by_model = {}
    by_workspace = {}
    for e in entries:
        by_model[e.model_id] = by_model.get(e.model_id, 0) + 1
        by_workspace[e.workspace] = by_workspace.get(e.workspace, 0) + 1
    if by_model:
        sys.stdout.write("by model:\n")
        for k, v in sorted(by_model.items()):
            sys.stdout.write(f"  {v:>6}  {k}\n")
    if by_workspace:
        sys.stdout.write("by workspace:\n")
        for k, v in sorted(by_workspace.items()):
            sys.stdout.write(f"  {v:>6}  {k or '(global)'}\n")
    return 0


def cmd_clear(args: argparse.Namespace) -> int:
    store, _ = _store(args)
    if store is None:
        sys.stdout.write("(no embeddings backend; nothing to clear)\n")
        return 0
    n = len(store.all())
    store.path.unlink(missing_ok=True)
    sys.stdout.write(f"cleared {n} vector(s) from {store.path}\n")
    return 0


# ---------------------------------------------------------------------------
# Bulk helpers
# ---------------------------------------------------------------------------


def _backfill_sessions(store: VectorStore, pdir: Path) -> int:
    """Walk every session JSONL under <pdir>/sessions/ and embed
    user + assistant turns that aren't already in the index.
    Returns the count of new vectors written."""
    sessions_dir = pdir / "sessions"
    if not sessions_dir.exists():
        return 0
    existing_ids = {e.doc_id for e in store.all()}
    items: list[tuple[str, str, str]] = []
    for path in sorted(sessions_dir.glob("*.jsonl")):
        session_id = path.stem
        workspace = ""
        meta_path = sessions_dir / f"{session_id}.meta.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                workspace = str(meta.get("workspace", "")) or ""
            except (OSError, json.JSONDecodeError):
                pass
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            role = msg.get("role", "")
            if role not in ("user", "assistant"):
                continue
            content = msg.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    c.get("text", "")
                    for c in content
                    if isinstance(c, dict) and c.get("type") == "text"
                )
            if not isinstance(content, str) or not content.strip():
                continue
            doc_id = f"{session_id}#{i}"
            if doc_id in existing_ids:
                continue
            items.append((doc_id, content.strip(), workspace))
    return store.backfill(items)


def _backfill_memory(store: VectorStore, pdir: Path, args: argparse.Namespace) -> int:
    """Embed every memory entry under <pdir>/memory/*.md."""
    memory_dir = pdir / "memory"
    if not memory_dir.exists():
        return 0
    existing_ids = {e.doc_id for e in store.all()}
    items: list[tuple[str, str, str]] = []
    profile = getattr(args, "profile", None) or load_config().profile or "default"
    for md in sorted(memory_dir.rglob("*.md")):
        name = md.relative_to(memory_dir).as_posix()
        doc_id = f"memory:{profile}:{name}"
        if doc_id in existing_ids:
            continue
        try:
            text = md.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if not text:
            continue
        items.append((doc_id, text, ""))
    return store.backfill(items)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="athena recall",
        description="Semantic recall admin: backfill / status / clear.",
    )
    sub = ap.add_subparsers(dest="action", required=True)

    p_back = sub.add_parser("backfill", help="One-time embed of existing history.")
    p_back.add_argument("--profile")
    p_back.set_defaults(func=cmd_backfill)

    p_status = sub.add_parser("status", help="Show vector counts.")
    p_status.add_argument("--profile")
    p_status.add_argument("--json", action="store_true")
    p_status.set_defaults(func=cmd_status)

    p_clear = sub.add_parser("clear", help="Drop the vector index.")
    p_clear.add_argument("--profile")
    p_clear.set_defaults(func=cmd_clear)

    args = ap.parse_args(argv)
    return cast(int, args.func(args))
