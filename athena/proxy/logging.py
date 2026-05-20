"""Structured JSONL logging for proxy traffic (T3-01.4).

Each completed proxy request gets one line in ``~/.athena/proxy.jsonl``
with the summary fields a reviewer needs to triage a session:
request id, timestamp, client User-Agent, requested model, provider
that actually served the request, latency, token counts, and the
finish reason. Full request and response bodies are kept under
``~/.athena/proxy_bodies/<request_id>.json`` only when
``log_bodies=True`` — payloads can easily exceed 50 KB and a busy
proxy fills disk fast.

Not credential material, so we don't route through
``secure_files`` — plain ``open("a")`` matches the existing
``athena/safety/audit.py`` pattern. A single ``threading.Lock``
serialises concurrent appends from the FastAPI worker(s); at proxy
volumes one writer per profile is fine.
"""

from __future__ import annotations

import contextlib
import dataclasses
import datetime
import json
import logging
import pathlib
import threading
import time
from collections.abc import Iterator
from typing import Any

logger = logging.getLogger(__name__)


_WRITE_LOCK = threading.Lock()


@dataclasses.dataclass
class ProxyLogger:
    """Append-only proxy traffic log.

    ``log_path`` and ``bodies_dir`` are absolute paths; the
    subcommand expands ``~/...`` before constructing the instance.
    """

    log_path: pathlib.Path
    bodies_dir: pathlib.Path
    log_bodies: bool = False

    def log_completed(
        self,
        *,
        request_id: str,
        client_ua: str,
        model_requested: str,
        provider_used: str,
        body: dict[str, Any],
        response: dict[str, Any] | None = None,
        latency_ms: float,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cache_read_tokens: int = 0,
    ) -> None:
        """Append one summary line. Idempotent on disk; multiple
        concurrent callers are serialised on the module lock."""
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        summary: dict[str, Any] = {
            "request_id": request_id,
            "ts": datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
            "client_ua": client_ua,
            "model_requested": model_requested,
            "provider_used": provider_used,
            "latency_ms": round(latency_ms, 2),
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cache_read_tokens": cache_read_tokens,
            "request_summary": {
                "message_count": len(body.get("messages", []) or []),
                "has_tools": bool(body.get("tools")),
                "stream": bool(body.get("stream", False)),
            },
        }
        if response is not None:
            first_choice = (response.get("choices") or [{}])[0]
            summary["response_summary"] = {
                "finish_reason": first_choice.get("finish_reason"),
                "has_tool_calls": bool((first_choice.get("message") or {}).get("tool_calls")),
            }

        line = json.dumps(summary, separators=(",", ":"), ensure_ascii=False)
        with _WRITE_LOCK:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")

        if self.log_bodies:
            self.bodies_dir.mkdir(parents=True, exist_ok=True)
            body_path = self.bodies_dir / f"{request_id}.json"
            try:
                with open(body_path, "w", encoding="utf-8") as f:
                    json.dump(
                        {"request": body, "response": response},
                        f,
                        indent=2,
                        ensure_ascii=False,
                    )
            except OSError as e:
                # Body capture is best-effort — never let a disk
                # error sink the response.
                logger.warning("proxy body capture failed for %s: %s", request_id, e)

    @contextlib.contextmanager
    def scope(
        self,
        *,
        request_id: str,
        client_ua: str,
        model_requested: str,
        provider_used: str,
        body: dict[str, Any],
    ) -> Iterator[LogScope]:
        """Sync context manager around a streaming response.

        The scope tracks latency from ``__enter__`` and emits a log
        line on exit; the caller can fill in token counts and the
        response summary via :meth:`LogScope.add_tokens` and
        :meth:`LogScope.set_response`.
        """
        scope = LogScope()
        start = time.time()
        try:
            yield scope
        finally:
            elapsed_ms = (time.time() - start) * 1000.0
            self.log_completed(
                request_id=request_id,
                client_ua=client_ua,
                model_requested=model_requested,
                provider_used=provider_used,
                body=body,
                response=scope.response_summary,
                latency_ms=scope.latency_ms or elapsed_ms,
                tokens_in=scope.tokens_in,
                tokens_out=scope.tokens_out,
                cache_read_tokens=scope.cache_read_tokens,
            )


@dataclasses.dataclass
class LogScope:
    """Mutable state carried inside :meth:`ProxyLogger.scope`. The
    streaming code fills these as it observes usage chunks; the
    context exit reads them when emitting the summary line."""

    latency_ms: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    cache_read_tokens: int = 0
    response_summary: dict[str, Any] | None = None

    def set_latency(self, seconds: float) -> None:
        self.latency_ms = seconds * 1000.0

    def add_tokens(self, in_: int = 0, out: int = 0, cache: int = 0) -> None:
        self.tokens_in += in_
        self.tokens_out += out
        self.cache_read_tokens += cache

    def set_response(self, summary: dict[str, Any]) -> None:
        self.response_summary = summary
