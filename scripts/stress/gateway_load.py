"""Gateway concurrent-session stress harness.

The 1.0 GA gate is: 100 concurrent sessions across 3 platforms for
24 hours with no crashes or memory leaks. A full 24-hour run is not
something you check into CI; this harness is the artifact that
*can* run it, plus the short-burn validation script that proves it
works.

What this exercises:

- :class:`GatewayDaemon` boot + adapter registration
- :meth:`SessionRouter.route` allocating one session per
  (platform, chat) pair from the configured agent pool
- Concurrent inbound dispatch through the photo-burst/text-merge
  semantics in :func:`gateway.base.merge_or_replace_pending`
- :class:`AgentPool` eviction under contention
- The Phase 17 snapshot/audit chain firing under load (curator
  forks may still trigger between turns)
- Reply emission via the stub adapter's :meth:`send_text`

What this DOES NOT exercise:

- Real network — every adapter here is a stub that records sends
  in memory. Use the live ``athena gateway run`` for actual
  Telegram / Slack / Discord traffic.
- Long-running cron / curator behavior — those run on hour+ timers.
  A 24-hour overnight run will exercise them; the 30-second smoke
  validation will not.

Two entry points::

    python -m scripts.stress.gateway_load --sessions 100 --duration 30
    python -m scripts.stress.gateway_load --sessions 100 --duration 86400 \\
        --report /tmp/24h-report.json

The report JSON carries percentile latencies, error breakdown, and
peak memory (via ``psutil`` when available; ``resource`` on POSIX).
"""
from __future__ import annotations

import argparse
import asyncio
import gc
import json
import logging
import os
import random
import statistics
import string
import sys
import time
import tracemalloc
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from athena.gateway.base import GatewayAdapter
from athena.gateway.daemon import GatewayDaemon
from athena.gateway.events import MessageEvent, MessageType

logger = logging.getLogger("athena.stress")


# ---- stub adapter ----------------------------------------------------------


class StressStubAdapter(GatewayAdapter):
    """No-network adapter. Records every outbound for later analysis."""

    def __init__(
        self,
        daemon: GatewayDaemon,
        platform_name: str,
        record: list[dict[str, Any]],
    ) -> None:
        self.name = platform_name
        super().__init__(daemon)
        self._record = record
        self.attachment_dir = Path("/tmp")

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def send_text(self, chat_id: str, text: str) -> str:
        self._record.append({
            "ts": time.perf_counter(),
            "kind": "text",
            "platform": self.name,
            "chat_id": chat_id,
            "text_len": len(text),
        })
        return f"{self.name}_{len(self._record)}"

    async def send_file(
        self, chat_id: str, file_path: str, *, caption: str = "",
    ) -> str:
        self._record.append({
            "ts": time.perf_counter(),
            "kind": "file",
            "platform": self.name,
            "chat_id": chat_id,
        })
        return f"{self.name}_{len(self._record)}"

    async def send_typing(self, chat_id: str) -> None:
        return None


# ---- stub provider (no network, returns canned text) ----------------------


class StubProvider:
    """Pretends to be a real provider — returns one canned text chunk
    and an end chunk. Latency simulates a tiny model so we exercise
    the gateway's async dispatch without paying real inference time."""

    name = "stub"

    def __init__(self, latency_ms: float = 30.0) -> None:
        self.latency_ms = latency_ms

    def stream_chat(
        self, *, model: str, messages: list, tools: list | None = None,
        **kwargs: Any,
    ):
        from athena.providers.base import StreamChunk

        last_user = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                last_user = m.get("content") or ""
                break

        time.sleep(self.latency_ms / 1000.0)
        reply = f"ack: {last_user[:60]}"
        yield StreamChunk("content", reply)
        yield StreamChunk("usage", {"prompt_tokens": 10, "completion_tokens": 3})
        yield StreamChunk("end", {"reason": "stop"})

    def parse_tool_calls(self, content: str, raw: dict) -> tuple[str, list]:
        return content, []

    def list_models(self) -> list[str]:
        return ["stub-model"]

    def show_model(self, model: str) -> dict:
        return {}

    def close(self) -> None:
        return None


# ---- metrics ----------------------------------------------------------------


@dataclass
class StressMetrics:
    started_at: float
    inbound_count: int = 0
    outbound_count: int = 0
    errors: list[str] = field(default_factory=list)
    latencies_ms: list[float] = field(default_factory=list)
    peak_rss_bytes: int = 0
    peak_tracemalloc_bytes: int = 0
    final_session_count: int = 0
    final_pool_size: int = 0

    def record_round_trip(self, ms: float) -> None:
        self.latencies_ms.append(ms)

    def summary(self) -> dict[str, Any]:
        lat = sorted(self.latencies_ms) if self.latencies_ms else [0.0]
        n = len(lat)
        def pct(p: float) -> float:
            if n == 0:
                return 0.0
            k = max(0, min(n - 1, int(round(p * (n - 1)))))
            return lat[k]
        return {
            "duration_s": time.perf_counter() - self.started_at,
            "inbound_count": self.inbound_count,
            "outbound_count": self.outbound_count,
            "error_count": len(self.errors),
            "errors_head": self.errors[:5],
            "latency_ms": {
                "min": min(lat) if lat else 0,
                "p50": pct(0.50),
                "p95": pct(0.95),
                "p99": pct(0.99),
                "max": max(lat) if lat else 0,
                "mean": (statistics.mean(lat) if lat else 0.0),
            },
            "peak_rss_bytes": self.peak_rss_bytes,
            "peak_tracemalloc_bytes": self.peak_tracemalloc_bytes,
            "final_session_count": self.final_session_count,
            "final_pool_size": self.final_pool_size,
        }


# ---- harness ---------------------------------------------------------------


def _build_cfg(home: Path, max_warm: int):
    """Synthesize a Config that points at a tmp home, uses the stub
    provider, and never tries to reach a real network."""
    from athena.config import Config, GatewayConfig
    cfg = Config()
    cfg.profile = "default"
    cfg.gateway = GatewayConfig()
    cfg.gateway.max_warm_agents = max_warm
    # Override profile path resolution by setting the env so every
    # subsystem that reads CONFIG_DIR sees our tmp home.
    return cfg


async def _run_session(
    daemon: GatewayDaemon,
    adapters: dict[str, StressStubAdapter],
    metrics: StressMetrics,
    *,
    session_id: int,
    duration_s: float,
    msgs_per_session_per_minute: float,
    text_corpus: list[str],
) -> None:
    """One synthetic 'user' that sends messages through a random platform
    at the configured rate, for ``duration_s`` seconds."""
    platforms = list(adapters.keys())
    period = 60.0 / max(msgs_per_session_per_minute, 1e-6)
    deadline = time.perf_counter() + duration_s
    chat_id = f"chat_{session_id}"
    user_id = f"user_{session_id}"
    msg_idx = 0
    while time.perf_counter() < deadline:
        platform = random.choice(platforms)
        adapter = adapters[platform]
        text = random.choice(text_corpus)
        msg_idx += 1
        event = MessageEvent(
            platform=platform,
            chat_id=chat_id,
            user_id=user_id,
            text=text,
            message_type=MessageType.TEXT,
            attachments=[],
            is_dm=True,
            reply_to_message_id=None,
            platform_message_id=f"{session_id}_{msg_idx}",
        )
        t0 = time.perf_counter()
        try:
            await adapter.handle_inbound(event)
            metrics.inbound_count += 1
            metrics.record_round_trip((time.perf_counter() - t0) * 1000)
        except Exception as e:
            metrics.errors.append(f"{type(e).__name__}: {e}")
        # Jitter the wait so we don't get thundering-herd behavior.
        await asyncio.sleep(period * random.uniform(0.5, 1.5))


def _measure_memory(metrics: StressMetrics) -> None:
    """Capture peak RSS via psutil when present; fall back to
    ``resource`` on POSIX; otherwise just record tracemalloc peak.
    Called periodically by a monitor task."""
    try:
        import psutil  # type: ignore
        rss = psutil.Process(os.getpid()).memory_info().rss
    except ImportError:
        try:
            import resource  # type: ignore
            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
        except ImportError:
            rss = 0
    metrics.peak_rss_bytes = max(metrics.peak_rss_bytes, rss)
    if tracemalloc.is_tracing():
        _, peak = tracemalloc.get_traced_memory()
        metrics.peak_tracemalloc_bytes = max(metrics.peak_tracemalloc_bytes, peak)


async def _memory_monitor(
    metrics: StressMetrics, deadline: float, interval_s: float,
) -> None:
    while time.perf_counter() < deadline:
        _measure_memory(metrics)
        await asyncio.sleep(interval_s)


# ---- runner ---------------------------------------------------------------


async def run_stress(
    *,
    sessions: int,
    platforms: list[str],
    duration_s: float,
    msgs_per_session_per_minute: float,
    max_warm: int,
    home: Path | None = None,
    report_path: Path | None = None,
) -> dict[str, Any]:
    """Drive ``sessions`` concurrent synthetic users across
    ``platforms`` for ``duration_s`` seconds. Returns the
    metrics summary dict (also written to ``report_path`` if given)."""
    home = home or Path.cwd() / "stress-home"
    home.mkdir(parents=True, exist_ok=True)
    profile_dir_path = home / "profiles" / "default"
    profile_dir_path.mkdir(parents=True, exist_ok=True)

    # Redirect athena's CONFIG_DIR / profile resolution to the tmp home.
    os.environ["ATHENA_HOME"] = str(home)
    from athena import config as cfg_mod
    cfg_mod.CONFIG_DIR = home
    cfg_mod.CONFIG_PATH = home / "config.toml"
    cfg_mod.SESSIONS_DIR = home / "sessions"

    cfg = _build_cfg(home, max_warm)

    # Build an agent_factory that returns a no-network agent backed by
    # the stub provider. Otherwise the daemon's default factory tries
    # to reach Ollama for every spawned session.
    # Forward-declare so the factory closes over the daemon.
    daemon_ref: list[GatewayDaemon] = []

    async def stub_agent_factory(session_id: str):
        from athena.agent.core import Agent
        return Agent(
            cfg, home, provider=StubProvider(),
            # Share the daemon's single SessionStore across every
            # spawned agent — otherwise each agent owns its own
            # sqlite connection, gets closed on eviction, and
            # leaves dangling-write warnings under load.
            session_store=daemon_ref[0].session_store,
            resume_session_id=session_id,
        )

    daemon = GatewayDaemon(cfg, agent_factory=stub_agent_factory)
    daemon_ref.append(daemon)

    metrics = StressMetrics(started_at=time.perf_counter())
    outbound_record: list[dict[str, Any]] = []
    adapters: dict[str, StressStubAdapter] = {}
    for p in platforms:
        a = StressStubAdapter(daemon, p, outbound_record)
        daemon.register(a)
        adapters[p] = a

    await daemon.start()

    # Catch errors that happen inside the gateway's background
    # dispatch task — they only land on the root logger otherwise, and
    # the harness reports a false-green run.
    class _ErrorCounter(logging.Handler):
        def __init__(self) -> None:
            super().__init__(level=logging.ERROR)

        def emit(self, record: logging.LogRecord) -> None:
            if record.levelno >= logging.ERROR:
                try:
                    msg = record.getMessage()
                except Exception:
                    msg = str(record.msg)
                metrics.errors.append(f"{record.name}: {msg}")
    err_handler = _ErrorCounter()
    logging.getLogger("athena.gateway").addHandler(err_handler)
    logging.getLogger("athena.gateway.base").addHandler(err_handler)
    logging.getLogger("athena.agent").addHandler(err_handler)

    tracemalloc.start()
    corpus = [
        "hello",
        "what is 2+2?",
        "summarize the docs",
        "list files in this dir",
        "explain " + "".join(random.choices(string.ascii_lowercase, k=20)),
    ]

    deadline = time.perf_counter() + duration_s
    monitor_interval = min(max(duration_s / 60.0, 1.0), 30.0)
    monitor = asyncio.create_task(
        _memory_monitor(metrics, deadline, monitor_interval),
    )

    tasks = [
        asyncio.create_task(_run_session(
            daemon, adapters, metrics,
            session_id=i,
            duration_s=duration_s,
            msgs_per_session_per_minute=msgs_per_session_per_minute,
            text_corpus=corpus,
        ))
        for i in range(sessions)
    ]
    await asyncio.gather(*tasks, return_exceptions=False)
    monitor.cancel()

    # Final settle: give the daemon a moment to flush any in-flight
    # dispatches before we measure outbound count.
    await asyncio.sleep(2.0)
    metrics.outbound_count = len(outbound_record)
    try:
        cur = daemon.router._db.execute(  # type: ignore[attr-defined]
            "SELECT COUNT(*) FROM routes"
        ).fetchone()
        metrics.final_session_count = int(cur[0]) if cur else -1
    except Exception:
        metrics.final_session_count = -1
    try:
        metrics.final_pool_size = len(daemon.pool._cache)  # type: ignore[attr-defined]
    except (AttributeError, TypeError):
        metrics.final_pool_size = -1

    _measure_memory(metrics)
    tracemalloc.stop()
    await daemon.stop()
    gc.collect()

    summary = metrics.summary()
    if report_path is not None:
        report_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        logger.info("wrote %s", report_path)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gateway-stress")
    parser.add_argument("--sessions", type=int, default=100)
    parser.add_argument(
        "--platforms", default="telegram,slack,discord",
        help="Comma-separated platform names to register as stubs.",
    )
    parser.add_argument(
        "--duration", type=float, default=30.0,
        help="Wall-clock seconds to drive load (default 30).",
    )
    parser.add_argument(
        "--rate", type=float, default=4.0,
        help="Messages per session per minute (default 4).",
    )
    parser.add_argument("--max-warm", type=int, default=50)
    parser.add_argument("--home", type=Path, default=None)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    summary = asyncio.run(run_stress(
        sessions=args.sessions,
        platforms=[p.strip() for p in args.platforms.split(",") if p.strip()],
        duration_s=args.duration,
        msgs_per_session_per_minute=args.rate,
        max_warm=args.max_warm,
        home=args.home,
        report_path=args.report,
    ))
    sys.stdout.write(json.dumps(summary, indent=2) + "\n")
    if summary["error_count"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
