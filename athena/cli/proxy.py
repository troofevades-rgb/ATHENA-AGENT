"""``athena proxy`` — local OpenAI-compatible HTTP endpoint (T3-01.8).

Spawns a FastAPI server backed by athena's full provider stack —
caching, retry, rate-limit tracking — so any third-party tool that
speaks OpenAI Chat Completions can use athena as its backend
without learning a new CLI.

Default binds to 127.0.0.1 on port 11434 (Ollama's port; the proxy
slots in cleanly when Ollama isn't running and any tool already
configured for Ollama works against it unchanged). ``--bind-public``
is required to expose 0.0.0.0 — defense-in-depth, since the proxy
holds your API keys.
"""

from __future__ import annotations

import argparse
import logging
import sys

from .. import ui
from ..config import load_config
from ..providers.credential_pool import global_pool


def _parse(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="athena proxy",
        description=(
            "Run a local OpenAI-compatible HTTP endpoint backed by "
            "athena. Routes incoming /v1/chat/completions requests to "
            "the active provider, applies athena's caching / retry / "
            "rate-limit machinery, and logs each translated pair to "
            "~/.athena/proxy.jsonl."
        ),
    )
    ap.add_argument("--host", default=None, help="Bind host (default: cfg.proxy_bind_host).")
    ap.add_argument("--port", type=int, default=None, help="Port (default: cfg.proxy_bind_port).")
    ap.add_argument(
        "--bind-public",
        action="store_true",
        help=(
            "Bind 0.0.0.0 instead of loopback. "
            "Requires explicit opt-in; the proxy uses your API keys "
            "to fulfil any request that reaches it."
        ),
    )
    ap.add_argument(
        "--provider",
        help=("Default provider for unrouted requests (overrides cfg.proxy_default_provider)."),
    )
    ap.add_argument(
        "--log-bodies",
        action="store_true",
        help="Persist full request/response bodies under ~/.athena/proxy_bodies/.",
    )
    ap.add_argument(
        "--no-translate",
        action="store_true",
        help=(
            "Passthrough mode for debugging — accept the request, route "
            "to the named provider, return the upstream response "
            "unmodified. No translation, no caching, no retry."
        ),
    )
    return ap.parse_args(argv)


def main(argv: list[str]) -> int:
    args = _parse(argv)
    cfg = load_config()
    if args.provider:
        cfg.proxy_default_provider = args.provider
    if args.log_bodies:
        cfg.proxy_log_bodies = True
    cfg.proxy_no_translate = args.no_translate

    host = args.host or cfg.proxy_bind_host
    port = args.port if args.port is not None else cfg.proxy_bind_port

    if args.bind_public:
        host = "0.0.0.0"
    if host == "0.0.0.0":
        ui.warn(
            "athena proxy binding to 0.0.0.0 — accessible from any host "
            "on the network. The proxy forwards using your API keys; "
            "make sure your firewall is configured."
        )

    try:
        from .. import providers as _providers  # noqa: F401 — registers built-ins
        from ..proxy.server import make_app
    except RuntimeError as e:
        # FastAPI not installed.
        ui.error(str(e))
        return 2

    try:
        import uvicorn
    except ImportError:
        ui.error(
            "athena proxy requires uvicorn. Install with:\n"
            '    pipx install --force "athena-coder[proxy]"'
        )
        return 2

    pool = global_pool()
    app = make_app(cfg=cfg, pool=pool)

    logging.basicConfig(level=logging.INFO)
    ui.info(f"athena proxy listening on http://{host}:{port}")
    ui.info(f"default provider: {cfg.proxy_default_provider}")
    ui.info("OpenAI-compatible clients: point --openai-api-base at this host")

    uvicorn.run(app, host=host, port=port, log_level="info")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
