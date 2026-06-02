"""/compact — manually trigger context compression.

Routes through ``athena.agent.context_compressor`` so the manual
slash and the automatic watermark trigger share one summarisation
path. Forces compression regardless of the watermark (watermark=0.0
means "compress now") and uses the full head/middle/tail layout.

Side-effect: after a successful compaction, fires the user-model
backend's ``ingest_session`` in a detached thread (controlled by
``cfg.user_model.ingest_on_compact``). Fire-and-forget — the
extraction never blocks the REPL.
"""

from __future__ import annotations

import threading
import uuid
from typing import Any

from .. import ui
from ..agent.context_compressor import CompressionConfig, compress
from . import command


@command("compact")
def cmd_compact(agent: Any, arg: str = "") -> str:
    if len(agent.messages) <= 2:
        ui.info("nothing to compact")
        return ""

    cfg = CompressionConfig(
        model_context_window=agent.cfg.context_window,
        # Force compression regardless of watermark.
        watermark=0.0,
        tail_protection_ratio=agent.cfg.tail_protection_ratio,
        tool_output_prune_tokens=agent.cfg.tool_output_prune_tokens,
        summary_budget_ratio=agent.cfg.summary_budget_ratio,
        summary_budget_cap_tokens=agent.cfg.summary_budget_cap_tokens,
        head_message_indices=1,
    )

    def _summarizer(prompt_messages: list, target_tokens: int) -> str:
        chunks: list[str] = []
        for chunk in agent.provider.stream_chat(
            model=agent.model,
            messages=prompt_messages,
            tools=None,
            max_tokens=target_tokens,
            num_ctx=agent.cfg.context_window,
        ):
            if chunk.kind == "content":
                payload = chunk.payload or ""
                if isinstance(payload, str):
                    chunks.append(payload)
        return "".join(chunks)

    # Mirror the runtime._maybe_compress_context try/except: a
    # summarizer failure (provider 404 from a misrouted model,
    # transport blip, auth rejection on the summary call) must
    # NEVER propagate. Without this wrap the HTTPStatusError
    # bubbled out of cmd_compact, into the REPL's slash-command
    # dispatch, up to main() -- a fatal crash on what should be
    # a no-op. Same bug class as commit 6056381 surfaced for the
    # automatic compressor; this is the manual-trigger sibling.
    try:
        result = compress(agent.messages, summarizer=_summarizer, cfg=cfg)
    except Exception as e:  # noqa: BLE001
        ui.error(f"compaction failed: {type(e).__name__}: {e}")
        return ""
    if result.middle_message_count == 0:
        ui.info("nothing to compact (head + tail already span the conversation)")
        return ""

    # Snapshot the pre-compaction transcript BEFORE we rebind
    # ``agent.messages`` — the user-model ingest wants the full
    # conversation, not the compacted head+summary+tail view.
    pre_compact_messages = list(agent.messages)

    agent.messages = result.new_messages
    if len(result.new_messages) > 1:
        agent._persist_message(result.new_messages[1])
    ui.info(
        f"compacted: {result.tokens_before:,} → {result.tokens_after:,} tokens "
        f"({100 * (1 - result.compression_ratio):.0f}% reduction; "
        f"{result.middle_message_count} messages → "
        f"{result.summary_tokens:,}-token summary)"
    )

    _maybe_fire_user_model_ingest(agent, pre_compact_messages)
    return ""


def _maybe_fire_user_model_ingest(agent: Any, transcript: list[dict]) -> None:
    """Kick off ``ingest_session`` on a detached thread when the
    user-model backend is configured to fire on compaction. Catches
    every exception inside the worker — a misbehaving extractor
    must never bubble up to the REPL."""
    cfg = getattr(agent, "cfg", None)
    if cfg is None or not getattr(cfg, "user_model", None):
        return
    if not cfg.user_model.ingest_on_compact:
        return
    if cfg.user_model.backend in ("none", "", None):
        return

    def _worker() -> None:
        import asyncio

        try:
            from ..tools import file_ops
            from ..tools.memory_query_tool import _build_llm_call
            from ..user_model import get_user_model_backend
        except ImportError:
            return
        try:
            backend = get_user_model_backend(
                cfg,
                llm_call=_build_llm_call(agent),
                workspace=file_ops._WORKSPACE,
            )
        except (ValueError, NotImplementedError):
            return
        session_id = getattr(agent, "session_id", None) or uuid.uuid4().hex
        try:
            asyncio.run(backend.ingest_session(transcript, session_id=session_id))
        except Exception:  # noqa: BLE001 — fire-and-forget
            return

    threading.Thread(target=_worker, name="athena-user-model-ingest", daemon=True).start()
