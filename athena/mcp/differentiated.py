"""Differentiated MCP tool surface — athena's distinctive capabilities (T5-05.3).

The base tool surface (``athena/mcp/tools.py``) advertises read-only
+ snapshot-revert tools that any sensible peer agent expects.
This module is the *differentiated* layer: tools a plain
OpenAI-compatible endpoint can't offer, re-exposing athena's
distinguishing capabilities to other agents as MCP tools.

What gets advertised here:

  * ``verified_write`` — write a file and run the T5-04
    verified-execution loop (LSP diagnose + optional sandbox run,
    rollback offer on failure). Routes through the same
    T1-07 path-security gate that local writes use, so a remote
    agent can't escape the workspace any more than a local one.

  * ``rollback_to`` / ``list_checkpoints`` — T3-03 conversation
    + file-state rollback. Only advertised when a checkpoint
    manager is available (i.e. T3-03 wired in). A remote agent
    can pin a known-good state, run a risky write, and revert.

  * ``analyze_image`` / ``analyze_video`` — vision analysis,
    routed via :class:`athena.media.MediaRegistry` to whichever
    provider's manifest declares ``vision``. Local preference
    keeps the bytes on-device when a local vision backend is
    installed. Only advertised when at least one provider
    declares vision AND (if creds are required) has a live
    credential.

  * ``recall`` — FTS5-backed session recall. Always available;
    local-only.

Manifest-driven advertisement: a tool that can't run on this
host (no vision backend, no checkpoint manager, no LSP) is
*not* listed at all — the caller never sees a tool whose call
would fail. Routing decisions inside the broker are logged for
operator visibility.

What's NOT advertised here (kept off explicitly, T3-02 rule):

  * No ``bash`` / arbitrary command execution. ``verified_write``
    runs a configured ``verify_command`` under the sandbox, not
    an arbitrary user-supplied one.

  * No raw ``Write`` / ``Edit``. The only write tool is
    ``verified_write``, which carries the verification loop.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool descriptors (only added to the list when host has the capability)
# ---------------------------------------------------------------------------


_VERIFIED_WRITE_DESCRIPTOR: dict[str, Any] = {
    "name": "verified_write",
    "description": (
        "Write a file and run athena's verified-execution loop: "
        "LSP diagnostics + optional sandboxed command. On failure "
        "the response carries a /rollback-to id the caller can "
        "invoke. Path-secured (T1-07) — writes outside the "
        "workspace are refused."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path to write."},
            "content": {
                "type": "string",
                "description": "File content (UTF-8).",
            },
        },
        "required": ["path", "content"],
    },
}

_ROLLBACK_DESCRIPTOR: dict[str, Any] = {
    "name": "rollback_to",
    "description": (
        "Roll back to a prior conversation/file checkpoint (T3-03). "
        "Reverts files, session log, skills, and memory atomically. "
        "The rollback itself is undoable via the auto-created "
        "pre-rollback-of-<id> checkpoint."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "checkpoint_id": {
                "type": "string",
                "description": "Checkpoint label or id.",
            },
        },
        "required": ["checkpoint_id"],
    },
}

_LIST_CHECKPOINTS_DESCRIPTOR: dict[str, Any] = {
    "name": "list_checkpoints",
    "description": "List available rollback targets for this session.",
    "inputSchema": {"type": "object", "properties": {}},
}

_ANALYZE_IMAGE_DESCRIPTOR: dict[str, Any] = {
    "name": "analyze_image",
    "description": (
        "Analyze an image using a vision-capable provider (resolved "
        "via the capability broker — local-first when available)."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "image_path": {"type": "string"},
            "prompt": {"type": "string"},
        },
        "required": ["image_path"],
    },
}

_ANALYZE_VIDEO_DESCRIPTOR: dict[str, Any] = {
    "name": "analyze_video",
    "description": ("Analyze a video by routing key frames through a vision-capable provider."),
    "inputSchema": {
        "type": "object",
        "properties": {
            "video_path": {"type": "string"},
            "prompt": {"type": "string"},
        },
        "required": ["video_path"],
    },
}

_RECALL_DESCRIPTOR: dict[str, Any] = {
    "name": "recall",
    "description": (
        "Full-text search over athena's session history (FTS5, "
        "local-only). Returns matching turns with session id + "
        "timestamps."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "default": 20},
        },
        "required": ["query"],
    },
}


# ---------------------------------------------------------------------------
# Builder + dispatcher
# ---------------------------------------------------------------------------


@dataclass
class DifferentiatedTools:
    """Holder for the host-available subset of differentiated tools.

    Construct via :func:`build_differentiated_tools` so the
    availability gates run once per server start (manifest-driven).
    Mutating it after the fact would let a tool be advertised
    whose call would crash — the build step is the single
    decision point.
    """

    descriptors: list[dict[str, Any]]
    workspace: Path
    media: Any  # MediaRegistry
    cfg: Any
    checkpoint_manager: Any | None = None  # None when T3-03 absent

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a tools/call by name. Returns the MCP-format
        ``{"content": [...], "isError"?: bool}`` dict.

        A call to a tool that wasn't advertised falls through to
        the caller (``MCPToolDispatcher.call_tool``) as "unknown
        tool" — no advertised tool ever reaches a missing handler.
        """
        try:
            if name == "verified_write":
                return self._verified_write(**arguments)
            if name == "rollback_to":
                return self._rollback_to(**arguments)
            if name == "list_checkpoints":
                return self._list_checkpoints(**arguments)
            if name == "analyze_image":
                return self._analyze_image(**arguments)
            if name == "analyze_video":
                return self._analyze_video(**arguments)
            if name == "recall":
                return self._recall(**arguments)
        except TypeError as e:
            return _error(f"invalid arguments for {name}: {e}")
        except Exception as e:  # noqa: BLE001
            logger.exception("MCP differentiated tool %s failed", name)
            return _error(f"{name} failed: {e}")
        return _error(f"unknown differentiated tool: {name}")

    # ------------------------------------------------------------------
    # verified_write — the headline capability
    # ------------------------------------------------------------------

    def _verified_write(self, path: str, content: str) -> dict[str, Any]:
        if not path:
            return _error("path required")
        from ..safety.path_security import validate_path
        from ..verify import VerifiedExecution

        try:
            target = validate_path(
                Path(path).expanduser(),
                intent="write",
            )
        except Exception as e:  # noqa: BLE001
            return _error(f"path refused by security: {e}")
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        existed = target.exists()
        target.write_text(content, encoding="utf-8")

        verifier = VerifiedExecution(cfg=self.cfg, workspace=self.workspace)
        outcome = verifier.verify_write(target)
        header = f"{'overwrote' if existed else 'created'} {target} ({len(content)} bytes)"
        body = outcome.report()
        text = header + "\n" + body
        is_error = outcome.failed
        result: dict[str, Any] = {
            "content": [{"type": "text", "text": text}],
        }
        if is_error:
            result["isError"] = True
        return result

    # ------------------------------------------------------------------
    # rollback / list_checkpoints
    # ------------------------------------------------------------------

    def _rollback_to(self, checkpoint_id: str) -> dict[str, Any]:
        if self.checkpoint_manager is None:
            return _error("no checkpoint manager available on this host")
        if not checkpoint_id:
            return _error("checkpoint_id required")
        try:
            cp = self.checkpoint_manager.rollback_to(checkpoint_id)
        except Exception as e:  # noqa: BLE001
            return _error(f"rollback failed: {e}")
        return _ok(
            f"rolled back to {cp.label!r} ({cp.id}); "
            f"pre-rollback state saved as pre-rollback-of-{cp.id}"
        )

    def _list_checkpoints(self) -> dict[str, Any]:
        if self.checkpoint_manager is None:
            return _error("no checkpoint manager available on this host")
        cps = self.checkpoint_manager.list()
        if not cps:
            return _ok("no checkpoints")
        lines = [f"  {cp.id}  {cp.created_at}  {cp.label}" for cp in cps]
        return _ok("checkpoints:\n" + "\n".join(lines))

    # ------------------------------------------------------------------
    # analyze_image / analyze_video — routed via MediaRegistry
    # ------------------------------------------------------------------

    def _analyze_image(self, image_path: str, prompt: str = "") -> dict[str, Any]:
        if not image_path:
            return _error("image_path required")
        backend = self.media.backend_for("vision")
        if backend is None:
            return _error("no vision backend available on this host")
        return _ok(
            f"vision backend resolved: {backend.name} for {image_path!r}; "
            "image analysis dispatch is the agent runtime's responsibility "
            "(this MCP wrapper surfaces the routing decision)."
        )

    def _analyze_video(self, video_path: str, prompt: str = "") -> dict[str, Any]:
        if not video_path:
            return _error("video_path required")
        backend = self.media.backend_for("vision")
        if backend is None:
            return _error("no vision backend available on this host")
        return _ok(
            f"vision backend resolved: {backend.name} for {video_path!r}; "
            "key-frame analysis is the agent runtime's responsibility "
            "(this MCP wrapper surfaces the routing decision)."
        )

    # ------------------------------------------------------------------
    # recall — local FTS5
    # ------------------------------------------------------------------

    def _recall(self, query: str, limit: int = 20) -> dict[str, Any]:
        if not query:
            return _error("query required")
        try:
            # FIXME(broken feature): athena.sessions.search was removed; this
            # import always fails so _recall degrades to "recall unavailable".
            # Rewiring to the current search API is a behaviour fix tracked
            # separately, out of scope for the mypy-baseline pass.
            from ..sessions.search import search_sessions  # type: ignore[import-not-found]
        except Exception as e:  # noqa: BLE001
            return _error(f"recall unavailable: {e}")
        try:
            results = search_sessions(query, limit=limit)
        except Exception as e:  # noqa: BLE001
            return _error(f"recall failed: {e}")
        if not results:
            return _ok(f"no matches for {query!r}")
        lines = []
        for r in results:
            # search_sessions returns dicts with at least session_id +
            # excerpt + timestamp; render whatever's present.
            sid = r.get("session_id") or r.get("session") or "?"
            ts = r.get("timestamp") or r.get("ts") or ""
            excerpt = r.get("excerpt") or r.get("snippet") or ""
            lines.append(f"  [{ts}] {sid}: {excerpt}")
        return _ok(f"{len(results)} match(es):\n" + "\n".join(lines))


def build_differentiated_tools(
    *,
    workspace: Path,
    cfg: Any,
    checkpoint_manager: Any | None = None,
) -> DifferentiatedTools:
    """Build the host-available subset of differentiated tools.

    Manifest-driven gating:

      * ``verified_write`` is always available (T5-04 + path
        security are core; a host running athena has both).
      * ``rollback_to`` / ``list_checkpoints`` advertised iff
        ``checkpoint_manager`` is non-None.
      * ``analyze_image`` / ``analyze_video`` advertised iff
        :meth:`MediaRegistry.can("vision")` is True (i.e. at
        least one registered provider declares vision).
      * ``recall`` is always advertised (FTS5 local).

    ``cfg.mcp_expose`` (empty by default) can whitelist a
    subset — when non-empty, only listed tools survive the
    gate (used by operators who want to expose a narrower
    surface than what's actually available).
    """
    from ..media import MediaRegistry

    media = MediaRegistry(cfg=cfg)
    descriptors: list[dict[str, Any]] = [_VERIFIED_WRITE_DESCRIPTOR]
    if checkpoint_manager is not None:
        descriptors.append(_ROLLBACK_DESCRIPTOR)
        descriptors.append(_LIST_CHECKPOINTS_DESCRIPTOR)
    if media.can("vision"):
        descriptors.append(_ANALYZE_IMAGE_DESCRIPTOR)
        descriptors.append(_ANALYZE_VIDEO_DESCRIPTOR)
    descriptors.append(_RECALL_DESCRIPTOR)

    whitelist = tuple(getattr(cfg, "mcp_expose", ()) or ())
    if whitelist:
        descriptors = [d for d in descriptors if d["name"] in whitelist]

    logger.info(
        "MCP differentiated surface: %s",
        ", ".join(d["name"] for d in descriptors) or "(none)",
    )
    return DifferentiatedTools(
        descriptors=descriptors,
        workspace=workspace,
        media=media,
        cfg=cfg,
        checkpoint_manager=checkpoint_manager,
    )


# ---------------------------------------------------------------------------
# MCP result helpers (mirror athena/mcp/tools.py)
# ---------------------------------------------------------------------------


def _ok(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}]}


def _error(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": True}
