"""Minimal LSP client that drives a language server for diagnostics (T5-03R.1).

LSP is JSON-RPC over stdin/stdout with ``Content-Length: N\\r\\n\\r\\n``
framing. This module implements just enough of it to:

1. Launch the configured server (``pyright-langserver --stdio`` or
   ``pylsp`` by default for Python).
2. Send ``initialize`` + ``initialized``.
3. Send one ``textDocument/didOpen`` per target path.
4. Collect ``textDocument/publishDiagnostics`` notifications until
   every opened doc has reported (or a timeout fires).
5. Shut the server down (``shutdown`` + ``exit``).

Returns a flat ``list[Diagnostic]`` across every opened path.

Two callers:

- :mod:`athena.tools.diagnose` exposes :func:`diagnose` via the
  ``@tool`` registry so the agent can request diagnostics
  on-demand.
- T5-04's verifier calls the same :func:`diagnose` as a
  pre-commit gate. Both surfaces share one signature so a
  fix here flows to both consumers.

Graceful by design: missing server, unsupported language, server
crash, or timeout all return ``[]`` with a debug log. The agent
loop never sees an exception from this module.
"""

from __future__ import annotations

import enum
import json
import logging
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------


class Severity(enum.IntEnum):
    """LSP DiagnosticSeverity values (spec 3.17, section
    Diagnostic). Lower is worse — Error=1, Warning=2, Info=3,
    Hint=4."""

    ERROR = 1
    WARNING = 2
    INFORMATION = 3
    HINT = 4

    @classmethod
    def from_raw(cls, value: Any) -> Severity:
        try:
            return cls(int(value))
        except (TypeError, ValueError):
            return cls.INFORMATION


@dataclass(frozen=True)
class Diagnostic:
    """One issue reported by a language server for one file.

    ``line`` and ``col`` are 1-based for human-readable rendering
    (LSP uses 0-based; we convert on parse). ``code`` is the rule
    identifier (e.g. ``"reportMissingImports"``); empty string when
    the server doesn't emit one."""

    path: str
    line: int
    col: int
    severity: Severity
    code: str
    message: str

    @property
    def is_error(self) -> bool:
        return self.severity == Severity.ERROR


# ---------------------------------------------------------------------------
# Language → server command resolution
# ---------------------------------------------------------------------------


# Default servers per language extension. Each entry is an argv
# list passed to subprocess.Popen with shell=False. cfg can
# override.
_DEFAULT_SERVERS: dict[str, list[str]] = {
    "python": ["pyright-langserver", "--stdio"],
}


def _language_for_path(path: str) -> str | None:
    """``athena/foo.py`` → ``"python"``. Returns None for unknown
    extensions (the file is then skipped — no language server to
    consult)."""
    suffix = Path(path).suffix.lower()
    if suffix == ".py":
        return "python"
    return None


def _server_command(language: str, cfg: Any) -> list[str] | None:
    """Resolve the argv for ``language``.

    Reads ``cfg.lsp_server_command`` first (a dict
    ``{language: ["cmd", "arg", ...]}``); falls back to the
    built-in :data:`_DEFAULT_SERVERS` map. Returns ``None`` when
    the resolved command's first element isn't on PATH."""
    override = (cfg.lsp_server_command or {}).get(language) if cfg is not None else None
    cmd = override or _DEFAULT_SERVERS.get(language)
    if not cmd:
        return None
    binary = cmd[0]
    if shutil.which(binary) is None:
        return None
    return list(cmd)


# ---------------------------------------------------------------------------
# JSON-RPC framing
# ---------------------------------------------------------------------------


def _frame(payload: dict[str, Any]) -> bytes:
    """Encode one LSP JSON-RPC message with the
    ``Content-Length`` header LSP requires."""
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body


def _read_frame(stream: IO[bytes]) -> dict[str, Any] | None:
    """Read one JSON-RPC frame; returns the parsed object or
    ``None`` on EOF / malformed headers."""
    headers: dict[str, str] = {}
    while True:
        line = stream.readline()
        if not line:
            return None
        line = line.rstrip(b"\r\n")
        if not line:
            break
        try:
            k, v = line.decode("ascii").split(":", 1)
            headers[k.strip().lower()] = v.strip()
        except ValueError:
            continue
    length_str = headers.get("content-length")
    if not length_str:
        return None
    try:
        length = int(length_str)
    except ValueError:
        return None
    body = stream.read(length)
    if not body:
        return None
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


# ---------------------------------------------------------------------------
# Session driver
# ---------------------------------------------------------------------------


def _path_to_uri(path: str) -> str:
    """``/home/x/foo.py`` → ``file:///home/x/foo.py``. POSIX-ish
    URI; LSP servers accept this on every platform we test."""
    p = Path(path).resolve()
    return p.as_uri()


def _read_text_safe(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _parse_diagnostic_notification(
    msg: dict[str, Any],
    uri_to_path: dict[str, str],
) -> tuple[str | None, list[Diagnostic]]:
    """Convert a ``textDocument/publishDiagnostics`` payload to a
    list of :class:`Diagnostic`. Returns ``(path, diagnostics)``."""
    params = msg.get("params") or {}
    uri = params.get("uri")
    if not isinstance(uri, str):
        return None, []
    path = uri_to_path.get(uri) or _uri_to_path(uri)
    raw_list = params.get("diagnostics") or []
    if not isinstance(raw_list, list):
        return path, []
    out: list[Diagnostic] = []
    for raw in raw_list:
        if not isinstance(raw, dict):
            continue
        rng = raw.get("range") or {}
        start = rng.get("start") or {}
        line = int(start.get("line") or 0) + 1  # 0-based → 1-based
        col = int(start.get("character") or 0) + 1
        sev = Severity.from_raw(raw.get("severity"))
        code = raw.get("code")
        if isinstance(code, (int, float)):
            code = str(code)
        elif not isinstance(code, str):
            code = ""
        message = str(raw.get("message") or "")
        out.append(
            Diagnostic(
                path=path,
                line=line,
                col=col,
                severity=sev,
                code=code,
                message=message,
            )
        )
    return path, out


def _uri_to_path(uri: str) -> str:
    """Best-effort reverse of :func:`_path_to_uri`. Used when the
    server hands us a uri for a doc we didn't open (rare; defensive)."""
    if uri.startswith("file://"):
        try:
            from urllib.parse import unquote, urlparse

            parsed = urlparse(uri)
            path = unquote(parsed.path)
            # Windows: parsed.path is "/C:/foo" → strip the leading /
            if os.name == "nt" and len(path) >= 3 and path[2] == ":":
                path = path[1:]
            return path
        except Exception:  # noqa: BLE001
            return uri
    return uri


# ---------------------------------------------------------------------------
# Transport abstraction (for tests)
# ---------------------------------------------------------------------------


class LSPTransport:
    """Minimal interface a transport must provide. The default
    transport is :class:`SubprocessTransport`; tests inject an
    in-memory transport that returns canned frames."""

    def write(self, payload: dict[str, Any]) -> None: ...

    def read(self, *, deadline: float) -> dict[str, Any] | None: ...

    def close(self) -> None: ...


class SubprocessTransport(LSPTransport):
    """Drive an LSP server over its stdin/stdout pipes."""

    def __init__(self, argv: list[str]) -> None:
        self._proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        assert self._proc.stdin is not None
        assert self._proc.stdout is not None
        self._stdin: IO[bytes] = self._proc.stdin
        self._stdout: IO[bytes] = self._proc.stdout
        self._lock = threading.Lock()

    def write(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self._stdin.write(_frame(payload))
            self._stdin.flush()

    def read(self, *, deadline: float) -> dict[str, Any] | None:
        # Blocking read; the caller enforces the overall timeout
        # by checking ``deadline`` between calls.
        if time.monotonic() >= deadline:
            return None
        return _read_frame(self._stdout)

    def close(self) -> None:
        try:
            self._stdin.close()
        except Exception:
            pass
        try:
            self._proc.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            try:
                self._proc.kill()
            except Exception:
                pass
        try:
            self._stdout.close()
        except Exception:
            pass
        try:
            if self._proc.stderr is not None:
                self._proc.stderr.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Top-level: diagnose
# ---------------------------------------------------------------------------


_DEFAULT_TIMEOUT_S: float = 30.0


def diagnose(
    paths: list[str],
    *,
    cfg: Any = None,
    transport_factory: Any = None,
) -> list[Diagnostic]:
    """Return diagnostics for ``paths`` from the appropriate
    language server.

    Behaviour:

    - Empty / unknown-language paths → returned as-is in the
      output, but with zero diagnostics each. The function never
      raises.
    - Server not on PATH → log a debug message, return ``[]``.
    - Server timeout → return what was collected before the
      deadline.
    - ``cfg.lsp_enabled = False`` → returns ``[]`` immediately
      (the gate the agent / verifier checks).
    """
    if not paths:
        return []
    if cfg is not None and not getattr(cfg, "lsp_enabled", False):
        return []

    timeout_s = float(
        getattr(cfg, "lsp_timeout_s", _DEFAULT_TIMEOUT_S) if cfg is not None else _DEFAULT_TIMEOUT_S
    )

    # Group paths by language.
    by_language: dict[str, list[str]] = {}
    for p in paths:
        lang = _language_for_path(p)
        if lang is None:
            logger.debug("LSP: skipping %s — no language mapping", p)
            continue
        by_language.setdefault(lang, []).append(p)

    out: list[Diagnostic] = []
    for language, lang_paths in by_language.items():
        argv = _server_command(language, cfg)
        if argv is None:
            logger.debug(
                "LSP: no server installed for %s — returning empty diagnostics for %d file(s)",
                language,
                len(lang_paths),
            )
            continue
        try:
            transport = (
                transport_factory(argv)
                if transport_factory is not None
                else SubprocessTransport(argv)
            )
        except (FileNotFoundError, OSError) as e:
            logger.debug("LSP: failed to start %s server: %s", language, e)
            continue
        try:
            out.extend(
                _run_session(
                    transport,
                    lang_paths,
                    timeout_s=timeout_s,
                )
            )
        except Exception as e:  # noqa: BLE001
            logger.debug("LSP: session error (%s): %s", language, e)
        finally:
            try:
                transport.close()
            except Exception:
                pass
    return out


def _run_session(
    transport: LSPTransport,
    paths: list[str],
    *,
    timeout_s: float,
) -> list[Diagnostic]:
    """One initialize → didOpen × N → collect diagnostics →
    shutdown cycle. Returns whatever diagnostics were collected
    within ``timeout_s``."""
    deadline = time.monotonic() + timeout_s
    next_id = 1
    # initialize
    transport.write(
        {
            "jsonrpc": "2.0",
            "id": next_id,
            "method": "initialize",
            "params": {
                "processId": os.getpid(),
                "rootUri": None,
                "capabilities": {
                    "textDocument": {
                        "publishDiagnostics": {"relatedInformation": False},
                    }
                },
            },
        }
    )
    next_id += 1
    # Drain until the initialize response lands, then send initialized.
    while time.monotonic() < deadline:
        msg = transport.read(deadline=deadline)
        if msg is None:
            return []
        if msg.get("id") == 1 and "result" in msg:
            break
    transport.write({"jsonrpc": "2.0", "method": "initialized", "params": {}})

    # didOpen each path
    uri_to_path: dict[str, str] = {}
    pending_paths: set[str] = set()
    for p in paths:
        uri = _path_to_uri(p)
        uri_to_path[uri] = p
        pending_paths.add(p)
        transport.write(
            {
                "jsonrpc": "2.0",
                "method": "textDocument/didOpen",
                "params": {
                    "textDocument": {
                        "uri": uri,
                        "languageId": "python",
                        "version": 1,
                        "text": _read_text_safe(p),
                    }
                },
            }
        )

    # Collect publishDiagnostics until every opened path reports
    # or the deadline fires.
    diagnostics: list[Diagnostic] = []
    while pending_paths and time.monotonic() < deadline:
        msg = transport.read(deadline=deadline)
        if msg is None:
            break
        if msg.get("method") != "textDocument/publishDiagnostics":
            continue
        path, diags = _parse_diagnostic_notification(msg, uri_to_path)
        if path is not None:
            pending_paths.discard(path)
            diagnostics.extend(diags)

    # Polite shutdown — best-effort; we already have what we need.
    try:
        transport.write({"jsonrpc": "2.0", "id": next_id, "method": "shutdown"})
        transport.write({"jsonrpc": "2.0", "method": "exit"})
    except Exception:  # noqa: BLE001
        pass
    return diagnostics
