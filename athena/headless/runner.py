"""Headless one-shot runner (T7-01.1).

Wraps the existing ``Agent`` + ``agent.run_turn(...)`` path in
a batch-friendly primitive. Every error mode produces a
:class:`RunResult` (not a Python exception) so the CLI
dispatcher's only job is mapping ``result.status`` to an
exit code + optionally writing the JSON envelope.

The agent loop itself is unchanged — this is purely a wrapper.
No changes to provenance / approval / write_origin paths.
"""

from __future__ import annotations

import datetime
import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable

from ..config import Config
from .result import RunResult, mint_run_id

logger = logging.getLogger(__name__)


# The dispatcher passes a UI callable so the runner doesn't
# hardcode where chatter goes (stderr in --json mode, stdout
# otherwise). Default is a no-op so unit tests don't have to
# care.
UIFn = Callable[[str], None]


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ"
    )


def _estimate_cost(stats: Any, model: str) -> float:
    """Best-effort cost estimate via the existing ui pricing
    table. Returns 0.0 when the model is unknown to the table —
    the envelope still ships, the cost field is just zero."""
    try:
        from ..ui import estimated_cost_usd
        return float(estimated_cost_usd(
            model=model,
            prompt_tokens=getattr(stats, "prompt_tokens", 0) or 0,
            eval_tokens=getattr(stats, "eval_tokens", 0) or 0,
        ))
    except Exception:  # noqa: BLE001
        return 0.0


def _tool_calls_summary(stats: Any) -> list[dict[str, Any]]:
    """[{name, count}] in descending-count order so the model /
    operator sees the busy tools first."""
    counts = dict(getattr(stats, "tool_call_counts", {}) or {})
    if not counts:
        return []
    return [
        {"name": name, "count": int(count)}
        for name, count in sorted(
            counts.items(), key=lambda kv: (-kv[1], kv[0]),
        )
    ]


def _tokens_dict(stats: Any) -> dict[str, int]:
    return {
        "prompt": int(getattr(stats, "prompt_tokens", 0) or 0),
        "completion": int(getattr(stats, "eval_tokens", 0) or 0),
        "cache_read": int(getattr(stats, "cache_read_tokens", 0) or 0),
        "cache_creation": int(getattr(stats, "cache_creation_tokens", 0) or 0),
    }


def run_headless(
    task: str,
    *,
    cfg: Config,
    workspace: Path,
    model: str | None = None,
    run_id: str | None = None,
    timeout_s: float | None = None,
    on_info: UIFn = lambda _m: None,
    agent: Any | None = None,
    _agent_factory: Callable[..., Any] | None = None,
) -> RunResult:
    """Execute one task headlessly and return its outcome.

    Every error condition is captured in the returned
    :class:`RunResult`; this function does not raise (the CLI
    dispatcher needs a guaranteed exit code).

    Arguments:
      ``task`` — the prompt to run. Empty / whitespace-only →
        ``status="invalid"``.
      ``cfg`` — the loaded :class:`Config`.
      ``workspace`` — the resolved workspace path. Must exist +
        be a directory; otherwise ``status="invalid"``.
      ``model`` — model tag override (else ``cfg.model``).
      ``run_id`` — operator-supplied correlation key; minted
        as ``r-<uuid12>`` when None.
      ``timeout_s`` — wall-clock timeout. None disables.
      ``on_info`` — UI callback for progress chatter (no-op
        default). The CLI passes a stderr writer when
        ``--json`` is set.
      ``agent`` — pre-built :class:`Agent` to reuse instead of
        constructing a new one. The CLI dispatcher passes the
        agent it already built (so MCP loading + the Ollama
        reachability check happen once). The runner still
        calls ``agent.close()`` at teardown.
      ``_agent_factory`` — test seam for injecting a fake
        Agent. Defaults to constructing the real one when
        ``agent`` is None.
    """
    rid = run_id or mint_run_id()
    started_iso = _now_iso()
    t0 = time.monotonic()

    # ----- validation up front (no Agent construction yet) -----

    if not task or not str(task).strip():
        return _invalid(
            rid, started_iso, t0,
            task=task or "", workspace=str(workspace),
            model=model or cfg.model, profile=cfg.profile or "default",
            error="task is empty",
        )

    if not workspace.exists():
        return _invalid(
            rid, started_iso, t0,
            task=task, workspace=str(workspace),
            model=model or cfg.model, profile=cfg.profile or "default",
            error=f"workspace does not exist: {workspace}",
        )
    if not workspace.is_dir():
        return _invalid(
            rid, started_iso, t0,
            task=task, workspace=str(workspace),
            model=model or cfg.model, profile=cfg.profile or "default",
            error=f"workspace is not a directory: {workspace}",
        )

    # ----- construct the agent + arm the timeout -----

    on_info(f"[run_id={rid}] starting headless run")
    if agent is None:
        if _agent_factory is None:
            from ..agent.core import Agent

            agent = Agent(cfg, workspace, model=model)
        else:
            agent = _agent_factory(cfg=cfg, workspace=workspace, model=model)

    timed_out = {"flag": False}
    timer: threading.Timer | None = None
    if timeout_s is not None and timeout_s > 0:

        def _fire_timeout() -> None:
            # Cancel the agent's in-flight work via the same
            # mechanism the interactive ESC handler uses:
            # ``cancel_pending`` is checked at the top of every
            # tool round and ``_cancel_in_flight`` aborts the
            # current HTTP stream so the worker unblocks
            # immediately. The previous implementation used
            # ``_thread.interrupt_main`` which raises
            # KeyboardInterrupt in the PROCESS main thread, not
            # whichever thread invoked run_headless -- batch /
            # gateway adapters that call run_headless from a
            # worker thread would either kill the wrong thread or
            # land the KeyboardInterrupt outside the try/except
            # window (after timer.cancel() / agent.close()).
            timed_out["flag"] = True
            try:
                agent.cancel_pending = True
            except Exception:
                pass
            cancel = getattr(agent, "_cancel_in_flight", None)
            if callable(cancel):
                try:
                    cancel()
                except Exception:
                    pass

        timer = threading.Timer(float(timeout_s), _fire_timeout)
        timer.daemon = True
        timer.start()

    status: Any = "ok"
    error: str | None = None

    try:
        agent.run_turn(task)
    except KeyboardInterrupt:
        # External SIGINT (Ctrl+C). The timeout path above no
        # longer raises KeyboardInterrupt, so reaching here means
        # the operator actually hit Ctrl+C.
        status = "interrupted"
        error = "interrupted by user (SIGINT)"
    except Exception as e:  # noqa: BLE001
        logger.exception("headless run failed")
        status = "error"
        error = f"{type(e).__name__}: {e}"
    finally:
        if timer is not None:
            timer.cancel()
        if timed_out["flag"] and status == "ok":
            # run_turn returned cleanly after we requested cancel —
            # mark as timeout for the envelope. If the agent raised
            # something else first that's already in ``status``.
            status = "timeout"
            error = f"wall-clock timeout after {timeout_s:.1f}s"
        try:
            agent.close()
        except Exception:  # noqa: BLE001
            logger.debug("agent.close() failed at headless teardown", exc_info=True)

    finished_iso = _now_iso()
    duration_s = time.monotonic() - t0

    stats = getattr(agent, "stats", None)
    return RunResult(
        run_id=rid,
        status=status,
        started_at=started_iso,
        finished_at=finished_iso,
        duration_s=duration_s,
        task=task,
        workspace=str(workspace),
        model=getattr(agent, "model", model or cfg.model),
        profile=cfg.profile or "default",
        session_id=getattr(agent, "session_id", None),
        tool_calls=_tool_calls_summary(stats),
        tokens=_tokens_dict(stats),
        cost_est=_estimate_cost(stats, getattr(agent, "model", model or cfg.model)),
        assistant_text=getattr(agent, "_last_assistant_text", "") or "",
        error=error,
    )


def _invalid(
    rid: str,
    started_iso: str,
    t0: float,
    *,
    task: str,
    workspace: str,
    model: str,
    profile: str,
    error: str,
) -> RunResult:
    """Build a ``status="invalid"`` result without touching the
    Agent. Used by the up-front validation checks."""
    return RunResult(
        run_id=rid,
        status="invalid",
        started_at=started_iso,
        finished_at=_now_iso(),
        duration_s=time.monotonic() - t0,
        task=task,
        workspace=workspace,
        model=model,
        profile=profile,
        session_id=None,
        tool_calls=[],
        tokens={"prompt": 0, "completion": 0, "cache_read": 0, "cache_creation": 0},
        cost_est=0.0,
        assistant_text="",
        error=error,
    )
