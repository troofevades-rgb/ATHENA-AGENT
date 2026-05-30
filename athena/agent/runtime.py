"""Hot-loop runtime mixin for :class:`~athena.agent.core.Agent`.

R1 stage 3 of the inheritance split. Owns the methods that run
during a user turn:

  * The outer loop (:meth:`run_turn`, :meth:`_run_turn_inner`,
    :meth:`run_until_done`)
  * Provider streaming (:meth:`_stream_one`,
    :meth:`_recover_tool_calls_from_text`)
  * Tool execution (:meth:`_handle_tool_call`,
    :meth:`_maybe_store_tool_result`, :meth:`_preview_write`,
    :meth:`_record_tool_result`)
  * Session-state side-effects (:meth:`_persist_message`,
    :meth:`_inject_pending_steers`)
  * Context-window hygiene (:meth:`_maybe_compress_context`,
    :meth:`_messages_with_cache_markers`)
  * Background-review handoff
    (:meth:`_wait_for_background_review`, :meth:`_maybe_fire_review`)
  * Long-turn UX (:meth:`_start_progress_ticker`,
    :meth:`_fire_stop`)

Every method stays on the public :class:`Agent` surface via the
mixin -- callers (gateway, CLI, tests) keep using ``Agent.run_turn``
etc. unchanged. The mixin reaches into ~20 attributes populated by
:meth:`Agent.__init__`; the TYPE_CHECKING block documents the
contract.

The ``_current_agent`` ContextVar moved to :mod:`athena.agent.context`
to break the ``core <-> runtime`` import cycle this mixin would
otherwise create.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .. import tools, ui
from ..safety.approval_callback import get_approval_callback
from .context import _current_agent
from .param_policy import PolicyInput
from .progress import emit_progress

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..config import Config
    from ..plugins.hooks import HookDispatcher
    from ..providers import Provider
    from ..sessions.store import SessionStore
    from .checkpoints import CheckpointManager
    from .param_policy import ParamPolicy

logger = logging.getLogger(__name__)


def _emit_tool_round_progress(tool_calls: list[dict[str, Any]]) -> None:
    """Emit a one-line summary of the tools about to run this round to
    the bound progress sink. No-op when no sink is bound (terminal /
    forks). Deduplicates names while preserving order so a round of
    three ``Read`` calls reads ``running Read (x3)`` rather than a
    repetitive list."""
    counts: dict[str, int] = {}
    for call in tool_calls:
        name = (call.get("function") or {}).get("name") or "tool"
        counts[name] = counts.get(name, 0) + 1
    if not counts:
        return
    parts = [(f"{name} (x{n})" if n > 1 else name) for name, n in counts.items()]
    emit_progress("🔧 running: " + ", ".join(parts))


class AgentRuntime:
    """Mixin providing the per-turn hot-loop methods for :class:`Agent`.

    Expects the concrete :class:`Agent` to populate (via its
    ``__init__``) the attributes the mixin reads or mutates:
    ``cfg``, ``workspace``, ``model``, ``provider``, ``messages``,
    ``stats``, ``session_id``, ``session_store``, ``plugin_hooks``,
    ``checkpoint_manager``, ``skill_metrics_store``,
    ``tool_result_storage``, ``_turn_lock``, ``_active_review_thread``,
    ``_param_policy``, ``_last_assistant_text``, ``_last_turn_interrupted``,
    ``cancel_pending``, ``_goal_loop_tokens_used``.
    """

    if TYPE_CHECKING:  # pragma: no cover - typing only
        cfg: Config
        workspace: Path
        model: str
        provider: Provider
        messages: list[dict[str, Any]]
        session_id: str | None
        session_store: SessionStore | None
        plugin_hooks: HookDispatcher
        checkpoint_manager: CheckpointManager | None
        skill_metrics_store: Any
        tool_result_storage: Any
        _turn_lock: threading.Lock
        _active_review_thread: threading.Thread | None
        _param_policy: ParamPolicy
        _last_assistant_text: str
        _last_turn_interrupted: bool
        cancel_pending: bool

    def run_turn(self, user_input: str) -> None:
        """Run one user turn to completion (model may call tools several times).

        T5-07: when an active GoalState is present, run_turn loops
        through synthetic continuation turns until the goal is
        achieved, blocked, or exhausted (turn cap OR token cap),
        or the user interrupts via Ctrl+C. Real user input always
        wins — a synthetic turn is only injected when the prior
        turn was NOT interrupted and the continuation hook says
        keep going. The /steer mechanism (drained at the top of
        each _run_turn_inner) preempts synthetic turns naturally.
        """
        from ..skills.metrics import set_active_store as _set_metrics_store
        from .checkpoints import set_active_checkpoint_manager

        with self._turn_lock:
            # Wait for any in-flight background review fork to finish
            # before we start a new foreground turn. Without this,
            # the review's child agent makes its own Ollama calls
            # concurrently with the foreground turn's calls, which
            # serializes on Ollama's single-inference-at-a-time
            # behavior and makes BOTH calls feel slow. Reviews are
            # best-effort observability — they should run when the
            # GPU is idle, never compete with the user-visible turn.
            self._wait_for_background_review(timeout=3.0)

            token = _current_agent.set(self)
            set_active_checkpoint_manager(self.checkpoint_manager)
            _set_metrics_store(self.skill_metrics_store)
            # T6-01: bind the per-session vector store on the
            # ContextVar so _persist_message's record_turn finds
            # it without explicit threading. Lazy-built once and
            # reused across run_turn calls in the same session.
            from ..recall import (
                build_vector_store as _build_vs,
            )
            from ..recall import (
                set_active_vector_store,
            )

            if not hasattr(self, "_vector_store"):
                try:
                    self._vector_store = _build_vs(cfg=self.cfg, profile_dir=self._profile_dir())
                except Exception:  # noqa: BLE001
                    self._vector_store = None
            set_active_vector_store(self._vector_store)
            # Spawn the progress ticker so long turns surface as
            # periodic flashes rather than appearing hung.
            progress_stop = self._start_progress_ticker()
            try:
                current_input = user_input
                tokens_at_loop_start = self.stats.prompt_tokens + self.stats.eval_tokens
                while True:
                    # 0.3.0 observability: time each inner turn so
                    # /status surfaces p50/p95/p99 turn latency.
                    # perf_counter avoids wall-clock skew if the
                    # system clock jumps mid-turn.
                    import time as _time
                    _turn_start = _time.perf_counter()
                    try:
                        self._run_turn_inner(current_input)
                    finally:
                        self.stats.record_turn_duration(
                            _time.perf_counter() - _turn_start
                        )
                    next_input = self._consult_goal_continuation(
                        tokens_at_loop_start=tokens_at_loop_start,
                    )
                    if next_input is None:
                        return
                    current_input = next_input
            finally:
                progress_stop.set()
                set_active_vector_store(None)
                _set_metrics_store(None)
                set_active_checkpoint_manager(None)
                _current_agent.reset(token)

    def _run_turn_inner(self, user_input: str) -> None:
        # Clear any stale cancel flag so a True left from a previous
        # turn doesn't immediately abort this one.
        self.cancel_pending = False
        # T5-07: per-turn tracking the continuation loop in run_turn
        # consults after this method returns. Reset on entry.
        self._last_assistant_text = ""
        self._last_turn_interrupted = False
        # Per-plugin veto on the user prompt. The first plugin to return
        # (False, reason) cancels the turn. The bundled ShellHookPlugin
        # bridges the settings.json UserPromptSubmit hook into this
        # check, so existing user configs keep working without going
        # through the legacy athena.hooks path.
        allow, msg = self.plugin_hooks.check_user_message(user_input)
        if not allow:
            ui.error(f"prompt cancelled by plugin: {msg}")
            return
        # Plugin chain: each plugin sees the output of the prior one. A
        # plugin returning None is a pass-through. The chained result is
        # what lands in history and goes to the model.
        user_input = self.plugin_hooks.on_user_message(user_input)
        # Drain any pending /steer messages BEFORE the user prompt so the
        # model sees in-flight redirects first. Each steer becomes its own
        # synthetic user message; the actual prompt follows.
        self._inject_pending_steers()
        user_msg = {"role": "user", "content": user_input}
        self.messages.append(user_msg)
        self._persist_message(user_msg)
        self.stats.turns += 1

        # Loop until the model produces a final assistant message with no tool calls.
        max_steps = max(1, int(self.cfg.max_turn_steps))
        for step in range(max_steps):
            # T2-04: check token watermark before each provider call.
            # The compressor is a no-op when below threshold; when
            # above, it replaces self.messages with [head, summary, tail].
            self._maybe_compress_context()
            # External cancel check (ACP session/cancel sets this).
            # Honored between tool rounds — the in-flight stream
            # itself completes naturally, but no further rounds spawn.
            if self.cancel_pending:
                ui.info("turn cancelled by external request")
                self.messages.append(
                    {
                        "role": "user",
                        "content": "[turn cancelled by the user]",
                    }
                )
                self._fire_stop("cancelled")
                return
            assistant_text, tool_calls, raw_done = self._stream_one(tool_call_round=step)
            interrupted = bool(raw_done and raw_done.get("_interrupted"))

            # Track usage if the provider reported it (skip phantom raw on
            # interrupt). Accept both Ollama-flavoured field names
            # (prompt_eval_count / eval_count) and the OpenAI-style names
            # used by every hosted provider's usage chunk
            # (prompt_tokens / completion_tokens) so cross-provider token
            # accounting keeps working without per-provider branching here.
            if raw_done and not interrupted:
                self.stats.prompt_tokens += (
                    raw_done.get("prompt_eval_count") or raw_done.get("prompt_tokens") or 0
                )
                self.stats.eval_tokens += (
                    raw_done.get("eval_count") or raw_done.get("completion_tokens") or 0
                )
                # Anthropic prompt-cache counters (T2-01).
                self.stats.cache_read_tokens += raw_done.get("cache_read_input_tokens") or 0
                self.stats.cache_creation_tokens += raw_done.get("cache_creation_input_tokens") or 0

            # Record the assistant message (with tool_calls if any) into history
            assistant_msg: dict[str, Any] = {"role": "assistant", "content": assistant_text}
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            self.messages.append(assistant_msg)
            self._persist_message(assistant_msg)

            if interrupted:
                # T5-07: signal interrupt to the continuation loop in
                # run_turn so it pauses the goal instead of injecting
                # another synthetic turn.
                self._last_turn_interrupted = True
                # The stream was cut mid-flight. If the model had emitted tool_calls
                # before the interrupt, mark them DENIED so the next turn doesn't
                # see dangling calls. Then leave a marker so the model knows.
                for call in tool_calls or []:
                    fname = (call.get("function") or {}).get("name", "?")
                    self._record_tool_result(
                        call, fname, "DENIED: response interrupted by user (Ctrl+C)"
                    )
                self.messages.append(
                    {
                        "role": "user",
                        "content": "[previous response was interrupted by the user]",
                    }
                )
                # No Stop hook — the turn didn't complete.
                return

            if not tool_calls:
                # Plugin observation — fire on the final assistant message
                # only (intermediate tool-calling rounds aren't surfaced).
                if assistant_text:
                    self.plugin_hooks.on_assistant_message(assistant_text)
                self._fire_stop("completed")
                self._maybe_fire_review()
                # T5-07: surface the final assistant text for the
                # continuation hook in run_turn.
                self._last_assistant_text = assistant_text or ""
                return

            # Execute each tool call and append a tool message for it.
            # Phase 18.2 stage 2: walk the calls in batches of contiguous
            # parallel-safe siblings instead of one at a time. Stage 2
            # dispatches every batch serially -- the batch shape is a
            # no-op structural change here; stage 3 will dispatch
            # multi-call batches concurrently via ThreadPoolExecutor.
            # Order of the synthesized tool messages stays identical to
            # the model's call order so the provider's tool_use <->
            # tool_result pairing keeps working.
            # If the user interrupts mid-loop, mark unexecuted calls
            # DENIED so the assistant message's tool_calls are all
            # paired with replies.
            ui.tool_round_header()
            asst_idx = len(self.messages) - 1
            batches = self._partition_tool_calls(tool_calls)
            # Surface what's running to any bound progress sink (the
            # gateway ships these to chat) so a long multi-tool turn
            # doesn't look hung. No-op on the terminal, which already
            # streams tool rounds live.
            _emit_tool_round_progress(tool_calls)
            try:
                for batch in batches:
                    self._dispatch_batch(batch)
            except KeyboardInterrupt:
                self._last_turn_interrupted = True
                ui.warn("interrupted during tool execution")
                # Count is robust to interrupts firing anywhere in the loop body.
                recorded = sum(1 for m in self.messages[asst_idx + 1 :] if m.get("role") == "tool")
                for missing in tool_calls[recorded:]:
                    fname = (missing.get("function") or {}).get("name", "?")
                    self._record_tool_result(
                        missing, fname, "DENIED: tool execution interrupted by user (Ctrl+C)"
                    )
                self.messages.append(
                    {
                        "role": "user",
                        "content": "[previous tool execution was interrupted by the user]",
                    }
                )
                return

        ui.warn(f"reached step limit ({max_steps}); stopping for safety.")
        self._fire_stop("step_limit")

    def _wait_for_background_review(self, *, timeout: float = 3.0) -> None:
        """Block at most ``timeout`` seconds for an in-flight background-review
        thread before starting the foreground turn. No-op when no review
        is in flight.

        Past the timeout, surface a visible status hint and proceed.
        The review keeps running on its daemon thread; on local Ollama
        it'll briefly serialize with the foreground call, which is far
        better than making the user wait indefinitely.

        Only local providers pay this wait. The whole reason it exists
        is Ollama's single-inference-at-a-time behaviour: a review
        fork's calls would serialize with the foreground turn and make
        both feel slow. Hosted providers (which gateway deployments
        typically use) handle concurrent requests fine — the credential
        pool already rotates on 429 — so blocking the user's turn up to
        ``timeout`` there is pure added latency for no benefit.
        """
        t = self._active_review_thread
        if t is None or not t.is_alive():
            return
        try:
            if not self.provider.capabilities(self.model).is_local:
                return
        except Exception:  # noqa: BLE001 — capability probe is best-effort
            # If we can't tell, keep the historical (safe) behaviour
            # and wait — better a small latency than a thrashed local GPU.
            pass
        import time as _time

        t0 = _time.monotonic()
        t.join(timeout=timeout)
        elapsed = _time.monotonic() - t0
        if t.is_alive():
            try:
                ui.info(
                    f"background review still running after {elapsed:.1f}s; "
                    f"proceeding (review will finish in background)"
                )
            except Exception:
                pass

    def _maybe_fire_review(self) -> None:
        """Hand off to the per-turn review orchestrator. Background reviews
        run on a daemon thread and never block this method."""
        from ..provenance import is_background

        # Gateway turns opt out entirely: the review fork's child agent
        # makes its own provider calls, which on a local Ollama serialize
        # against the user-facing reply and make a chat turn crawl (or
        # stall). The review's memory/skill suggestions are never seen by
        # a chat user anyway, so on the gateway it's pure contention.
        # Set by the gateway agent factory.
        if getattr(self, "_suppress_background_review", False):
            return
        # Don't recursively spawn reviews from inside background forks.
        if is_background():
            return
        # Skip if the previous review is still running. Stacking review
        # threads (one per turn boundary) compounds httpx connection
        # pressure and races for provider rate limits against the
        # foreground turn. The nudge counter still increments, so the
        # next idle boundary will trigger a fresh review.
        prior = self._active_review_thread
        if prior is not None and prior.is_alive():
            return
        try:
            from ..review.orchestrator import maybe_fire_review

            fired = maybe_fire_review(self)
            if fired is not None:
                self.stats.review_fired_count += 1
                # Record the thread on the agent so the next
                # run_turn can wait for it before competing for
                # Ollama. Without this the review's child agent
                # fights the next foreground turn for GPU time.
                self._active_review_thread = fired
        except Exception:
            # The review path must never break a foreground turn.
            ui.info("background review failed to fire (logged)")

    def _start_progress_ticker(self) -> threading.Event:
        """Spawn a daemon thread that emits a status.flash every
        ~30s if the turn hasn\'t finished. Returns the stop event;
        caller sets it in the run_turn finally block to terminate.

        The flash text shows tool-call count and elapsed time so
        the user sees ongoing progress even when the model is
        between tool calls and not streaming. Without this, long
        local-model turns look indistinguishable from a hang
        (caught during step-12 visual testing).
        """
        stop = threading.Event()
        start_at = time.monotonic()
        tools_at_start = self.stats.tool_calls

        def _tick() -> None:
            # Wait 30s before first flash so short turns don't flash at all.
            while not stop.wait(timeout=30.0):
                elapsed = int(time.monotonic() - start_at)
                tools_this_turn = self.stats.tool_calls - tools_at_start
                msg = f"still working — {tools_this_turn} tool call(s), {elapsed}s elapsed"
                try:
                    ui._emit_flash("info", msg)
                except Exception:  # noqa: BLE001
                    # Flash is informational; never break the turn.
                    pass

        threading.Thread(
            target=_tick,
            name="athena-progress-ticker",
            daemon=True,
        ).start()
        return stop

    def _fire_stop(self, reason: str) -> None:
        stats = {
            "turns": self.stats.turns,
            "tool_calls": self.stats.tool_calls,
            "prompt_tokens": self.stats.prompt_tokens,
            "eval_tokens": self.stats.eval_tokens,
        }
        # Per-turn end-of-turn hook. The bundled ShellHookPlugin
        # bridges the settings.json Stop event into this dispatch.
        try:
            self.plugin_hooks.on_turn_end(reason, stats)
        except Exception:  # noqa: BLE001
            logger.debug("plugin on_turn_end raised", exc_info=True)
        # Phase 16: refresh the on-disk status snapshot so
        # ``athena status`` (running in another terminal) sees the
        # post-turn counters.
        try:
            self.write_status_snapshot()
        except Exception:
            # Status snapshot is observability, not correctness — a
            # failed write must never break the turn.
            pass

    def _stream_one(
        self, tool_call_round: int = 0
    ) -> tuple[str, list[dict[str, Any]], dict[str, Any] | None]:
        """One model turn. Streams text to stdout, returns (text, tool_calls, usage).

        ``tool_call_round`` is the iteration index inside the current
        user turn (0 = first stream, 1 = after one round of tool calls,
        etc.) — passed through to the parseltongue param policy so
        rules like "drop temperature when we're deep in a tool chain"
        have something to fire on.

        ``usage`` is the Ollama-flavored dict the caller already knows how to
        read — ``prompt_eval_count`` / ``eval_count`` / ``eval_duration`` for
        Ollama; the same keys with zeros (and tokens from the provider's
        ``usage`` chunk) for other providers.
        """
        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        usage: dict[str, Any] | None = None

        # Spinner during the silent first-token wait (partial-offload models can
        # take 5-30s before the first chunk). Stop it the moment any chunk lands.
        status = ui.console.status("[dim]thinking…[/]", spinner="dots")
        status.start()
        first = True
        # Render streamed text via the typewriter helper so we can swap
        # to a Rich.Markdown view at the end without polluting the
        # terminal with both the plain stream and the rendered copy.
        typewriter = ui.TypewriterStream(prefix="▌ ", prefix_style="bold #00ff00")
        msgs_to_send = self._messages_for_api()
        tool_schemas = tools.ollama_schema(
            enabled_toolsets=self.cfg.enabled_toolsets,
            disabled=self.cfg.disabled_tools,
        )
        # Parseltongue: ask the policy for this turn's inference params.
        # The policy returns a dict that goes into stream_chat as kwargs;
        # the provider filters to whichever options it actually accepts.
        policy_input = PolicyInput(
            messages=msgs_to_send,
            tools_available=[
                (t.get("function") or {}).get("name", "")
                for t in (tool_schemas or [])
                if isinstance(t, dict)
            ],
            tool_calls_so_far=tool_call_round,
        )
        policy_params = self._param_policy.params_for(policy_input)
        try:
            for chunk in self.provider.stream_chat(
                model=self.model,
                messages=msgs_to_send,
                tools=tool_schemas,
                num_ctx=self.cfg.context_window,
                **policy_params,
            ):
                if first and chunk.kind in ("content", "tool_call"):
                    status.stop()
                    if chunk.kind == "content":
                        typewriter.start()
                    first = False
                if chunk.kind == "content":
                    text = chunk.payload or ""
                    if text:
                        typewriter.feed(text)
                        text_parts.append(text)
                elif chunk.kind == "tool_call":
                    # Stream cuts to a tool call — finalize the
                    # typewriter on whatever text accumulated so the
                    # tool-call summary panel renders on a fresh line.
                    typewriter.finalize(markdown=False)
                    p = chunk.payload or {}
                    tool_calls.append(
                        {
                            "function": {
                                "name": p.get("name", ""),
                                "arguments": p.get("arguments", {}),
                            },
                            **({"id": p["id"]} if p.get("id") else {}),
                        }
                    )
                elif chunk.kind == "usage":
                    usage = dict(chunk.payload or {})
                # "end" chunk is informational; loop falls through naturally.
        except KeyboardInterrupt:
            if first:
                status.stop()
            typewriter.finalize(markdown=False)
            ui.warn("interrupted")
            # Signal interruption to run_turn via a sentinel on the usage dict.
            return "".join(text_parts), tool_calls, {"_interrupted": True}
        except Exception as e:
            if first:
                status.stop()
            typewriter.finalize(markdown=False)
            ui.error(f"provider error: {e}")
            # 0.3.0 observability: count provider failures so /status
            # surfaces "the model endpoint is flaky" without operators
            # having to grep logs.
            self.stats.record_provider_error()
            return "".join(text_parts), [], None
        finally:
            # Tool-only or empty responses never trip the in-loop stop().
            if first:
                status.stop()
        # Final render — Markdown when the assembled text looks like
        # it'd benefit (code blocks, headings, lists). Plain text
        # responses re-render as plain.
        typewriter.finalize(markdown=True)
        # ``ui.stream_stats`` (per-turn token+throughput footer)
        # was removed during the UI cleanup — the Ink TUI's
        # bottom StatusBar already shows model/tokens/elapsed
        # continuously, so a per-turn footer was redundant.
        text = "".join(text_parts)
        # Recovery: if the model emitted tool-call JSON as content instead of
        # using the provider's native tool_calls field, parse it out and treat
        # as tool calls. Phase 9 routes this through the provider's
        # parse_tool_calls (which dispatches to the per-(provider, model)
        # parser registry); if that returns nothing, fall back to the in-agent
        # generic recovery for older patterns.
        if not tool_calls and text.strip():
            recovered_calls = self._recover_tool_calls_from_text(text)
            if recovered_calls:
                tool_calls = recovered_calls[0]
                text = recovered_calls[1]
                ui.info(f"recovered {len(tool_calls)} tool call(s) from content")
        return text, tool_calls, usage

    def _recover_tool_calls_from_text(self, text: str) -> tuple[list[dict[str, Any]], str] | None:
        """Try the per-(provider, model) parser registry first; if it
        returns no tool calls, fall through to the in-agent generic
        recovery. Returns (canonical_tool_calls, residual_content) on hit,
        or None if no recovery was possible.
        """
        try:
            cleaned, calls = self.provider.parse_tool_calls(text, {"model": self.model})
            if calls:
                normalized = [
                    {
                        "function": {
                            "name": c.get("name", ""),
                            "arguments": c.get("arguments", {}),
                        },
                        **({"id": c["id"]} if c.get("id") else {}),
                    }
                    for c in calls
                ]
                return normalized, cleaned
        except Exception:
            ui.info("provider parse_tool_calls raised; falling back to generic recovery")

        # Deferred to avoid a runtime -> core import cycle. The helper
        # lives in core.py for now; R1's final stage may move it to a
        # shared module.
        from .core import _extract_text_tool_calls

        residual, recovered = _extract_text_tool_calls(text)
        if recovered:
            return recovered, residual
        return None

    def _partition_tool_calls(
        self, tool_calls: list[dict[str, Any]]
    ) -> list[list[dict[str, Any]]]:
        """Group contiguous parallel-safe calls into batches.

        Each returned batch is a list of one or more tool calls that
        appeared consecutively in ``tool_calls`` and are all flagged
        :attr:`~athena.tools.registry.Tool.parallel_safe`. A
        non-parallel-safe call sits in a batch of its own. The batch
        order preserves the model's emit order so the synthesized
        tool messages, when appended in batch-then-within-batch
        order, match the provider's tool_use sequence exactly.

        Contiguous-only grouping is intentional: a model that emits
        ``[Read(a), Read(b), Edit(c), Read(d)]`` likely intends the
        Edit to consume what the two Reads found and the trailing
        Read to inspect the Edit's effect. Reordering across the
        Edit would change semantics, so the partitioning never
        crosses a non-parallel-safe call.

        Stage 2 dispatches every batch serially; stage 3 swaps the
        per-batch loop for a ThreadPoolExecutor when ``len(batch) >
        1``. Unknown tool names (not in the registry) are treated as
        non-parallel-safe so a typoed call doesn't accidentally race
        with its siblings.
        """
        batches: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        current_is_safe = False

        for call in tool_calls:
            name = ((call.get("function") or {}).get("name") or "")
            t = tools.get_tool(name)
            is_safe = bool(t and t.parallel_safe)
            if current and is_safe and current_is_safe:
                current.append(call)
                continue
            if current:
                batches.append(current)
            current = [call]
            current_is_safe = is_safe
        if current:
            batches.append(current)
        return batches

    def _dispatch_batch(self, batch: list[dict[str, Any]]) -> None:
        """Run every call in ``batch`` and append the synthesised tool
        messages in original call order.

        Stage 3 behaviour:

        * Single-call batch -- always serial, regardless of
          ``cfg.parallel_tool_workers``. No thread-pool spin-up cost
          when there's nothing to fan out.
        * Multi-call batch + ``parallel_tool_workers <= 1`` -- serial,
          same loop as stages 1 / 2.
        * Multi-call batch + ``parallel_tool_workers > 1`` -- workers
          dispatch concurrently via a ThreadPoolExecutor sized to
          ``min(len(batch), parallel_tool_workers)``. Each worker runs
          under its own ``contextvars.copy_context()`` snapshot so the
          parent's workspace / plan-mode / current-agent / vector-store
          ContextVars propagate. Tool messages are buffered by index
          and recorded on the main thread in batch order; the
          provider's tool_use <-> tool_result pairing depends on this.

        A ``KeyboardInterrupt`` from any worker bubbles up so the
        enclosing ``_run_turn_inner`` catches it and marks unexecuted
        calls DENIED -- order-preserving cleanup still works because
        ``messages.append`` only happens on the main thread.
        """
        # Single-call or serial-mode fast path.
        workers = max(1, int(getattr(self.cfg, "parallel_tool_workers", 1) or 1))
        if len(batch) <= 1 or workers <= 1:
            for call in batch:
                self._handle_tool_call(call)
            return

        # Parallel-dispatch path. Workers stash their (call, name,
        # result) into ``slots`` by index; the main thread then walks
        # ``slots`` and calls the real ``_record_tool_result`` in
        # order. Early-return branches inside ``_handle_tool_call``
        # (plan-blocked, plugin-vetoed, confirmation-denied) all go
        # through ``record`` too, so even those land in the right slot.
        import contextvars
        from concurrent.futures import ThreadPoolExecutor

        slots: list[tuple[dict[str, Any], str, str] | None] = [None] * len(batch)

        def _make_sink(idx: int):
            def _sink(call: dict[str, Any], name: str, result: str) -> None:
                slots[idx] = (call, name, result)
            return _sink

        # Capture the foreground thread's context snapshot once per
        # worker. ``contextvars.copy_context()`` returns a fresh
        # snapshot each call -- mutations inside one worker's
        # ``ctx.run(...)`` don't leak to siblings.
        ctx_snapshots = [contextvars.copy_context() for _ in batch]
        max_workers = min(len(batch), workers)
        interrupted = False
        with ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="athena-tool",
        ) as pool:
            futures = [
                pool.submit(
                    ctx.run,
                    self._handle_tool_call,
                    call,
                    record_sink=_make_sink(idx),
                )
                for idx, (ctx, call) in enumerate(zip(ctx_snapshots, batch))
            ]
            # Stage 5: if Ctrl+C fires mid-batch, ``.result()`` on
            # the offending future re-raises ``KeyboardInterrupt``
            # on the main thread. We catch it here -- NOT in the
            # caller -- so we can:
            #   * cancel every still-pending future (those that
            #     hadn't started running),
            #   * give in-flight workers a brief grace window to
            #     finish their tool body cleanly so their slot
            #     populates,
            #   * record whatever completed in declared order
            #     (preserving the model's tool_use <-> tool_result
            #     pairing for the work that actually ran),
            #   * mark any uncompleted call DENIED in its declared
            #     slot,
            #   * re-raise so the outer ``_run_turn_inner`` recovery
            #     handles cross-batch cleanup (subsequent batches'
            #     calls get DENIED and the ``[previous tool execution
            #     was interrupted]`` user marker is appended).
            try:
                for f in futures:
                    f.result()
            except KeyboardInterrupt:
                interrupted = True
                for f in futures:
                    f.cancel()
                # Best-effort: wait briefly for already-running
                # workers to write their slot. Python can't kill
                # a running thread; the tool body finishes either
                # way, so giving it a short window lets us record
                # the result instead of dropping it.
                # NOTE: catch ``BaseException`` here -- the worker
                # that originally raised KeyboardInterrupt will
                # re-raise it on every subsequent ``.result()``,
                # and a bare ``except Exception`` would let it
                # propagate past the recording loop, silently
                # dropping all the completed slots' results.
                for f in futures:
                    try:
                        f.result(timeout=0.1)
                    except BaseException:
                        # Includes TimeoutError, KeyboardInterrupt
                        # (re-raised from the offending worker),
                        # and any worker exception. We've already
                        # decided to interrupt -- everything else
                        # is noise.
                        pass

        # Record completed slots in order; DENY the rest. Stage 3
        # already preserved order for the happy path; stage 5
        # extends the same ordering guarantee to the interrupted
        # path so the provider's pairing keeps working.
        denied_msg = (
            "DENIED: tool execution interrupted by user (Ctrl+C)"
        )
        for idx, entry in enumerate(slots):
            if entry is not None:
                self._record_tool_result(*entry)
            elif interrupted:
                call = batch[idx]
                name = (call.get("function") or {}).get("name", "?")
                self._record_tool_result(call, name, denied_msg)
            else:
                # No interrupt + no slot entry should be impossible
                # (every successful ``_handle_tool_call`` calls its
                # sink). Skip defensively -- the next round's
                # tool_use<->tool_result mismatch will surface the
                # bug noisily.
                continue

        if interrupted:
            self._last_turn_interrupted = True
            raise KeyboardInterrupt

    def _handle_tool_call(
        self,
        call: dict[str, Any],
        *,
        record_sink: Any = None,
    ) -> None:
        """Run one tool call to completion and record its result.

        ``record_sink`` is the callable invoked to materialise the
        tool message (signature ``(call, name, result_str) -> None``).
        Defaults to :meth:`_record_tool_result`, which appends to
        ``self.messages`` and the session JSONL synchronously. The
        parallel-dispatch path in :meth:`_run_turn_inner` passes a
        sink that just stashes ``(call, name, result_str)`` into an
        ordered slot so the main thread can record the batch in
        original call order after every worker completes -- preserving
        the provider's tool_use <-> tool_result pairing.
        """
        record = record_sink if record_sink is not None else self._record_tool_result
        fn = call.get("function", {}) or {}
        name = fn.get("name", "")
        args_raw = fn.get("arguments", {})
        # Ollama may give us a dict or a JSON string depending on model
        if isinstance(args_raw, str):
            stripped = args_raw.strip()
            if not stripped:
                args = {}
            else:
                # T2-05: route through the JSON sanitiser before the
                # raw json.loads. Recovers smart quotes / single quotes
                # / trailing commas / unquoted keys without speculating
                # about missing values. Gated by cfg.tool_call_sanitize.
                to_parse = stripped
                if getattr(self.cfg, "tool_call_sanitize", True):
                    from ..providers.schema_sanitizer import sanitize_tool_call_args

                    sanitized, fixes = sanitize_tool_call_args(stripped, tool_name=name)
                    if sanitized is not None:
                        if fixes:
                            ui.info(f"sanitised tool-call args for {name}: {', '.join(fixes)}")
                        to_parse = sanitized
                try:
                    args = json.loads(to_parse)
                except json.JSONDecodeError:
                    args = {}
        else:
            args = args_raw or {}

        # Stages 3 + 4: locks around the per-call non-atomic
        # mutations. ``getattr`` with a nullcontext fallback covers
        # SimpleNamespace stubs that bypass Agent.__init__.
        # ``_ui_lock`` keeps the multi-line tool_call_summary /
        # tool_result panels from interleaving under parallel
        # dispatch; ``_stats_lock`` keeps the Stats counter +
        # breakdown-dict mutations atomic. Both serial-path-uncontended.
        import contextlib
        ui_lock = getattr(self, "_ui_lock", None) or contextlib.nullcontext()
        stats_lock = getattr(self, "_stats_lock", None) or contextlib.nullcontext()
        with ui_lock:
            ui.tool_call_summary(name, args)
        with stats_lock:
            self.stats.record_tool_call(name)

        # Plan-mode gate: only read-only tools are allowed
        from ..tools import plan as plan_mod

        if plan_mod.is_plan_mode() and name not in plan_mod.PLAN_MODE_ALLOWED:
            denied = (
                f"BLOCKED: tool {name!r} is not allowed in plan mode. "
                "Use Read/Glob/Grep/WebFetch/WebSearch to investigate, then "
                "call ExitPlanMode with the proposed plan."
            )
            record(call, name, denied)
            ui.warn(denied)
            return

        t = tools.get_tool(name)
        # Confirmation gate for destructive tools.
        # For Bash, an allowlist short-circuits the prompt.
        if t and t.requires_confirmation and not self.cfg.auto_approve_tools:
            allowed = False
            if name in ("Bash", "bash"):
                from ..safety.shell_policy import DEFAULT_DENYLIST, ShellPolicy

                cmd = (args.get("command") or "").strip()
                # Word-boundary match via ShellPolicy: prefix "ls"
                # must not allow "lsof"; "git" must not allow "gitleaks".
                bash_cfg = self.cfg.bash
                deny = tuple(DEFAULT_DENYLIST) + tuple(bash_cfg.extra_denylist or ())
                policy = ShellPolicy(bash_cfg.allowlist, deny)
                allowed = policy.evaluate(cmd).allowed
            if not allowed:
                preview = args.get("command") or json.dumps(args)
                ui.console.print(f"[yellow]command:[/] [white]{preview}[/]")
                if get_approval_callback()(name, args) != "allow":
                    result = "DENIED by user"
                    record(call, name, result)
                    return

        # Plugin veto: first plugin to return False from pre_tool_call
        # blocks. ShellHookPlugin bridges settings.json PreToolUse hooks
        # into this path so existing user configs keep working.
        plugin_allow, blocker = self.plugin_hooks.pre_tool_call(name, args)
        if not plugin_allow:
            blocked = f"BLOCKED by plugin {blocker!r}"
            record(call, name, blocked)
            ui.warn(blocked)
            return

        # Show diffs for Write/write_file before they happen
        if name in ("Write", "write_file"):
            self._preview_write(args)

        # 0.3.0 observability: time the dispatch so /status surfaces
        # per-tool p50/p95/p99 and tool_errors (dispatch-raised count).
        # The histogram is what reveals "tool X went from 50ms p95 to
        # 5s p95 after rebuild Y" -- the kind of regression that
        # eval suites miss.
        import time as _time
        _tool_start = _time.perf_counter()
        try:
            result = tools.dispatch(name, args)
        except Exception:
            self.stats.record_tool_error()
            raise
        finally:
            self.stats.record_tool_duration(
                name, _time.perf_counter() - _tool_start
            )
        with ui_lock:
            ui.tool_result(name, result)

        # Relay the result to a gateway chat if this tool opted in
        # (gateway_relay=True) -- e.g. skills_list, whose output is itself
        # what the user asked to see. Emitted on the RAW result, before
        # the large-output blob-handle swap below, so the chat gets the
        # real content rather than a storage reference. No-op when no
        # gateway sink is bound (terminal / forks).
        if t is not None and getattr(t, "gateway_relay", False):
            from .tool_relay import emit_tool_result

            emit_tool_result(name, result if isinstance(result, str) else str(result))

        # Plugin observation; cannot affect control flow. ShellHookPlugin
        # bridges settings.json PostToolUse hooks here.
        self.plugin_hooks.post_tool_call(name, args, result)

        # T2-06: out-of-band storage for large tool outputs. The
        # original `result` is still passed to the hooks above (so
        # observers see the raw text); only the message stored in
        # conversation history is replaced with the handle.
        result = self._maybe_store_tool_result(name, result)
        record(call, name, result)

    def _maybe_store_tool_result(self, tool_name: str, result: str) -> str:
        """T2-06: if the tool result exceeds the configured threshold,
        persist it to a content-addressed blob and return the short
        reference handle. Below threshold passes through unchanged.
        """
        storage = getattr(self, "tool_result_storage", None)
        if storage is None:
            return result
        threshold = getattr(self.cfg, "tool_result_threshold_bytes", 1_000_000)
        if not isinstance(result, str):
            return result
        from ..tools.tool_result_storage import maybe_store_result

        return maybe_store_result(
            content=result,
            tool_name=tool_name,
            threshold_bytes=threshold,
            storage=storage,
        )

    def _preview_write(self, args: dict[str, Any]) -> None:
        # Accept both Claude-Code-style file_path/content and athena-style path/content
        path = args.get("file_path") or args.get("path")
        new = args.get("content", "")
        if not path:
            return
        target = (self.workspace / path) if not Path(path).is_absolute() else Path(path)
        old = ""
        if target.exists() and target.is_file():
            try:
                old = target.read_text(encoding="utf-8")
            except OSError:
                pass
        ui.show_diff(path, old, new)

    def _record_tool_result(self, call: dict[str, Any], name: str, result: str) -> None:
        # 0.3.0 hardening tier 0 #4: wrap the tool result with the
        # per-session nonce markers so injected content inside a Read /
        # WebFetch / MCP response can't break out of the wrapper by
        # emitting literal ``</tool_result>`` or similar -- the closing
        # marker uses a random nonce minted in Agent.__init__ that the
        # attacker can't pre-guess. The system-prompt instructs the
        # model to treat content between the markers as DATA, not
        # instructions; see ``athena.prompts.system.build_system_prompt``.
        # Stub agents in unit tests (and forks that bypass
        # AgentLifecycle.__init__) won't have ``_tool_result_nonce`` --
        # ``getattr`` keeps the wrapping off in that case, preserving
        # back-compat for everything that constructs an AgentRuntime via
        # ``__new__``. Production Agents always get the nonce.
        nonce = getattr(self, "_tool_result_nonce", None)
        wrapped = (
            f"[TOOL_RESULT.{nonce}]\n{result}\n[/TOOL_RESULT.{nonce}]"
            if nonce
            else result
        )
        msg: dict[str, Any] = {"role": "tool", "name": name, "content": wrapped}
        # Some Ollama models send a tool_call_id; preserve when present
        if "id" in call:
            msg["tool_call_id"] = call["id"]
        self.messages.append(msg)
        self._persist_message(msg)

    def _inject_pending_steers(self) -> None:
        """Drain any pending /steer messages and append them as synthetic
        user messages before the next prompt. Steers are delivered in
        FIFO order.
        """
        if self.session_id is None:
            return
        from ..steer.queue import GLOBAL_STEER_QUEUE

        steers = GLOBAL_STEER_QUEUE.drain(self.session_id)
        for steer in steers:
            steer_msg = {"role": "user", "content": f"[/steer] {steer}"}
            self.messages.append(steer_msg)
            self._persist_message(steer_msg)

    def _persist_message(self, message: dict[str, Any]) -> None:
        """Append the message to the session store if one is active.

        Strips any Anthropic ``cache_control`` markers before writing —
        the current call path never plants them in ``self.messages``
        (they're applied to a deepcopy in ``_messages_with_cache_markers``)
        but the strip makes the invariant explicit and prevents a
        future regression from polluting the JSONL.
        """
        if self.session_store is None or self.session_id is None:
            return
        from .prompt_caching import strip_cache_markers

        clean = strip_cache_markers([message])[0]
        try:
            self.session_store.append_turn(self.session_id, clean)
        except Exception as e:  # pragma: no cover — defensive
            ui.info(f"session append failed (continuing): {e}")
            return

        # T6-01: incremental embedding for semantic recall. Best
        # effort — a recall-side failure must never block a
        # session write. The active vector store comes from the
        # recall ContextVar bound in run_turn (similar to T3-03's
        # checkpoint manager pattern).
        try:
            from ..recall import record_turn

            # turn_index = current length minus the just-appended
            # message (so this turn's persisted offset matches the
            # JSONL line count after append).
            turn_index = max(0, len(self.messages) - 1)
            record_turn(
                session_id=self.session_id,
                turn_index=turn_index,
                role=str(clean.get("role", "")),
                content=clean.get("content", ""),
                workspace=str(self.workspace),
            )
        except Exception:  # noqa: BLE001
            import logging as _logging

            _logging.getLogger(__name__).debug("record_turn failed", exc_info=True)

    def _maybe_compress_context(self) -> None:
        """T2-04: compress ``self.messages`` if total tokens exceed
        the configured watermark. No-op when below threshold or when
        the head + tail already span the entire context (nothing in
        the middle to summarise).

        When compression runs, the synthetic summary message is
        persisted to the session JSONL so a resumed session sees the
        same compressed shape.
        """
        from .context_compressor import CompressionConfig, compress, should_compress

        cfg = CompressionConfig(
            model_context_window=self.cfg.context_window,
            watermark=self.cfg.context_compress_watermark,
            tail_protection_ratio=self.cfg.tail_protection_ratio,
            tool_output_prune_tokens=self.cfg.tool_output_prune_tokens,
            summary_budget_ratio=self.cfg.summary_budget_ratio,
            summary_budget_cap_tokens=self.cfg.summary_budget_cap_tokens,
            head_message_indices=1,
        )
        if not should_compress(self.messages, cfg):
            return

        def _summarizer(prompt_messages: list[dict[str, Any]], target_tokens: int) -> str:
            chunks: list[str] = []
            for chunk in self.provider.stream_chat(
                model=self.model,
                messages=prompt_messages,
                tools=None,
                max_tokens=target_tokens,
                num_ctx=self.cfg.context_window,
            ):
                if chunk.kind == "content":
                    payload = chunk.payload or ""
                    if isinstance(payload, str):
                        chunks.append(payload)
            return "".join(chunks)

        result = compress(self.messages, summarizer=_summarizer, cfg=cfg)
        if result.middle_message_count == 0:
            return
        ui.info(
            f"context compressed: {result.tokens_before:,} → "
            f"{result.tokens_after:,} tokens "
            f"({100 * (1 - result.compression_ratio):.0f}% reduction; "
            f"{result.middle_message_count} messages folded)"
        )
        self.messages = result.new_messages
        # Persist the synthetic summary (the new messages[1]) so a
        # resumed session sees the compressed shape rather than
        # re-replaying the original middle.
        if len(result.new_messages) > 1:
            self._persist_message(result.new_messages[1])

    def _messages_for_api(self) -> list[dict[str, Any]]:
        """Build the message list the provider's ``stream_chat`` sees.

        Same ordering as :meth:`_messages_with_cache_markers` (system,
        history) with the godmode prefill messages spliced in between
        when ``cfg.agent_prefill_messages_file`` is set. Prefill is
        ephemeral -- it lives only inside the API call:

          * Never appended to ``self.messages``.
          * Never persisted to JSONL (the persistence path runs on
            ``self.messages`` appends, which prefill skips entirely).
          * Never visible in ``/save`` transcripts (same reason).
          * Re-read from disk only when
            :meth:`reload_prefill_messages` invalidates the cache.

        Mirrors hermes-agent's prefill_messages_file integration:
        the model sees prior conversation context establishing a
        pattern of compliance, but the persisted session record
        shows only real user / assistant turns. Operators tailing
        the JSONL never see the priming.
        """
        msgs = self._messages_with_cache_markers()
        load = getattr(self, "_load_prefill_messages", None)
        prefill = load() if callable(load) else []
        if not prefill:
            return msgs
        # Splice: system stays at index 0, prefill comes next, then
        # the rest of the history. When there's no system message
        # (unusual but possible in test stubs), prefill leads.
        if msgs and msgs[0].get("role") == "system":
            return [msgs[0], *prefill, *msgs[1:]]
        return [*prefill, *msgs]

    def _messages_with_cache_markers(self) -> list[dict[str, Any]]:
        """Return ``self.messages`` with cache_control markers if the
        active provider has declared support for Anthropic-shape
        ``cache_control`` markers and caching is enabled in
        ``cfg.cache_strategy``. Pure copy — does not mutate
        ``self.messages``.

        Whether the provider wants markers is read from
        :attr:`Capabilities.anthropic_cache_markers` rather than a
        hardcoded provider-name allowlist; that lets new providers
        opt in by setting the capability instead of editing this
        method. Providers whose prompt caching is automatic (OpenAI
        server-side prefix detection) declare ``prompt_caching=True``
        without the marker flag and get this method as a no-op.
        """
        strategy = getattr(self.cfg, "cache_strategy", "none")
        if strategy == "none":
            return self.messages
        try:
            caps = self.provider.capabilities(self.model)
        except Exception:
            return self.messages
        if not getattr(caps, "anthropic_cache_markers", False):
            return self.messages
        from .prompt_caching import apply_cache_markers

        provider_name = getattr(self.provider, "name", "")
        return apply_cache_markers(
            self.messages,
            strategy=strategy,  # type: ignore[arg-type]
            ttl=getattr(self.cfg, "prompt_cache_ttl", "5m"),  # type: ignore[arg-type]
            native_anthropic=(provider_name == "anthropic"),
        )

    def run_until_done(self, user_prompt: str = "", *, max_iterations: int | None = None) -> None:
        """Run a single user turn to completion (loops internally over tool
        rounds). ``max_iterations``, when given, overrides ``cfg.max_turn_steps``
        for this call only — used by ``Agent.fork`` to cap fork loop length."""
        if max_iterations is not None:
            saved = self.cfg.max_turn_steps
            self.cfg.max_turn_steps = max_iterations
            try:
                self.run_turn(user_prompt)
            finally:
                self.cfg.max_turn_steps = saved
        else:
            self.run_turn(user_prompt)
