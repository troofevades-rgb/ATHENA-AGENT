"""Copy Hermes session transcripts to ocode v2's per-profile session store.

Each Hermes session is a ``<source>/sessions/<session_id>.jsonl`` file. The
first line is an optional metadata header (``{"_meta": {...}}``); subsequent
lines are individual messages. The importer:

1. Opens (or reuses) a :class:`SessionStore` at
   ``<dest>/profiles/<profile>/`` — this is what populates ``sessions.db``
   alongside the JSONL files.
2. ``open_session`` writes ``<id>.jsonl`` + ``<id>.meta.json`` and inserts
   the sessions row.
3. ``append_turn`` appends each message and indexes its content for FTS5.

Preserves message order exactly.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..sessions.store import SessionMeta, SessionStore
from .report import Report


_FILENAME_TS_RE = re.compile(r"^(?P<id>[^_]+?)(?:_(?P<ts>\d{8,}))?$")


def _read_meta_header(first_line: str) -> dict[str, Any]:
    try:
        obj = json.loads(first_line)
    except json.JSONDecodeError:
        return {}
    if isinstance(obj, dict) and "_meta" in obj and isinstance(obj["_meta"], dict):
        return obj["_meta"]
    return {}


def _build_meta(src_file: Path, header: dict[str, Any], profile: str) -> dict[str, Any]:
    """Resolve the per-session metadata: header wins, then filename, then mtime."""
    session_id = src_file.stem
    meta: dict[str, Any] = dict(header) if header else {}

    if not meta.get("started_at"):
        m = _FILENAME_TS_RE.match(session_id)
        if m and m.group("ts"):
            ts = int(m.group("ts"))
            meta["started_at"] = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        else:
            meta["started_at"] = datetime.fromtimestamp(
                src_file.stat().st_mtime, tz=timezone.utc
            ).isoformat()

    meta.setdefault("session_id", session_id)
    meta.setdefault("profile", profile)
    meta.setdefault("model", header.get("model", "unknown"))
    meta.setdefault("provider", header.get("provider", "unknown"))
    meta.setdefault("imported_at", datetime.now(timezone.utc).isoformat())
    meta["source"] = str(src_file)
    return meta


def _ingest_session(
    src_file: Path,
    store: SessionStore,
    *,
    report: Report,
    profile: str,
    dry_run: bool,
) -> None:
    session_id = src_file.stem
    lines = src_file.read_text(encoding="utf-8").splitlines()
    if not lines:
        report.add("session_skipped_empty", {"source": str(src_file)})
        return

    header = _read_meta_header(lines[0])
    body_lines = lines[1:] if header else lines
    messages: list[dict[str, Any]] = []
    for raw in body_lines:
        s = raw.strip()
        if not s:
            continue
        try:
            messages.append(json.loads(s))
        except json.JSONDecodeError:
            continue

    meta_dict = _build_meta(src_file, header, profile)

    if not dry_run:
        started = datetime.fromisoformat(
            meta_dict["started_at"].replace("Z", "+00:00")
        )
        store.open_session(SessionMeta(
            session_id=session_id,
            profile=profile,
            model=meta_dict.get("model", "unknown"),
            provider=meta_dict.get("provider", "unknown"),
            workspace=meta_dict.get("workspace"),
            parent_session_id=meta_dict.get("parent_session_id"),
            started_at=started,
            tags=list(meta_dict.get("tags") or []),
        ))
        # Patch the meta sidecar to also carry import provenance.
        sidecar = store.sessions_dir / f"{session_id}.meta.json"
        if sidecar.exists():
            try:
                existing = json.loads(sidecar.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                existing = {}
            existing.update({
                "imported_at": meta_dict["imported_at"],
                "source": meta_dict["source"],
            })
            sidecar.write_text(json.dumps(existing, indent=2), encoding="utf-8")
        for msg in messages:
            store.append_turn(session_id, msg)

    report.add("imported_session", {
        "session_id": session_id,
        "source": str(src_file),
        "destination": str(store.sessions_dir / f"{session_id}.jsonl"),
        "message_count": len(messages),
        "dry_run": dry_run,
    })


def import_sessions(
    source: Path,
    dest: Path,
    *,
    profile: str = "default",
    report: Report,
    dry_run: bool = False,
) -> None:
    sessions_src = source / "sessions"
    if not sessions_src.exists():
        report.add("sessions_warning", {
            "reason": "no_sessions_dir",
            "path": str(sessions_src),
        })
        return

    profile_root = dest / "profiles" / profile
    if dry_run:
        # Don't materialize the destination on dry-run; just record planned imports.
        for jsonl in sorted(sessions_src.glob("*.jsonl")):
            lines = jsonl.read_text(encoding="utf-8").splitlines()
            header = _read_meta_header(lines[0]) if lines else {}
            body = lines[1:] if header else lines
            valid = sum(1 for ln in body if ln.strip())
            report.add("imported_session", {
                "session_id": jsonl.stem,
                "source": str(jsonl),
                "destination": str(profile_root / "sessions" / jsonl.name),
                "message_count": valid,
                "dry_run": True,
            })
        return

    profile_root.mkdir(parents=True, exist_ok=True)
    store = SessionStore(profile_root)
    try:
        for jsonl in sorted(sessions_src.glob("*.jsonl")):
            _ingest_session(jsonl, store, report=report, profile=profile, dry_run=dry_run)
    finally:
        store.close()
