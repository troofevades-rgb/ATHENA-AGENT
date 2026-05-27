"""``athena mcp {auth, token-status, revoke, list, test}``.

Operator surface for MCP HTTP/SSE servers configured in
``mcp.json``. The subcommands fall into three buckets:

- **Auth lifecycle**: ``auth`` (run the OAuth flow), ``revoke``
  (delete the stored token), ``token-status`` (show what we have).
- **Inspection**: ``list`` (show every configured server + its
  transport), ``test`` (connect to one server and dump its tools).

Stdio MCP servers are inspectable too — ``list`` shows them and
``test`` initializes them — but the auth flow only applies to
HTTP/SSE entries.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from ..config import mcp_config_paths
from ..mcp import oauth
from ..mcp.transport_resolver import open_transport

logger = logging.getLogger("athena.mcp.cli")


# ---- subcommand: list -------------------------------------------------


def cmd_list(args: argparse.Namespace) -> int:
    """Show every server in mcp.json with its transport + status."""
    servers = _load_server_configs(args.config)
    if not servers:
        sys.stdout.write("(no mcp servers configured)\n")
        return 0
    if args.json:
        out = [
            {
                "name": name,
                "transport": (cfg.get("transport") or "stdio"),
                "disabled": bool(cfg.get("disabled")),
                "url": cfg.get("url"),
                "command": cfg.get("command"),
                "has_oauth": bool(cfg.get("oauth")),
            }
            for name, cfg in servers.items()
        ]
        sys.stdout.write(json.dumps(out, indent=2) + "\n")
        return 0
    for name, cfg in servers.items():
        transport = (cfg.get("transport") or "stdio").lower()
        flags = []
        if cfg.get("disabled"):
            flags.append("disabled")
        if cfg.get("oauth"):
            flags.append("oauth")
        target = cfg.get("url") or cfg.get("command") or "?"
        suffix = f"  [{', '.join(flags)}]" if flags else ""
        sys.stdout.write(f"{name:24} {transport:6}  {target}{suffix}\n")
    return 0


# ---- subcommand: auth ------------------------------------------------


def cmd_auth(args: argparse.Namespace) -> int:
    """Run the OAuth authorization flow for one configured server."""
    servers = _load_server_configs(args.config)
    if args.server not in servers:
        sys.stderr.write(f"error: no server named {args.server!r} in mcp.json\n")
        return 2
    scfg = servers[args.server]
    oauth_raw = scfg.get("oauth")
    if not oauth_raw:
        sys.stderr.write(
            f"error: server {args.server!r} has no [oauth] config — stdio servers don't need auth\n"
        )
        return 2

    try:
        cfg = oauth.OAuthConfig(
            server_id=args.server,
            authorization_endpoint=oauth_raw["authorization_endpoint"],
            token_endpoint=oauth_raw["token_endpoint"],
            client_id=oauth_raw["client_id"],
            scopes=list(oauth_raw.get("scopes") or []),
            audience=oauth_raw.get("audience"),
        )
    except KeyError as e:
        sys.stderr.write(f"error: oauth config missing key {e}\n")
        return 2

    sys.stdout.write(f"opening browser for {args.server} (timeout {args.timeout}s)...\n")
    sys.stdout.flush()
    try:
        token = oauth.run_authorization_flow(
            cfg,
            open_browser=not args.no_browser,
            timeout_seconds=args.timeout,
        )
    except oauth.OAuthError as e:
        sys.stderr.write(f"error: oauth flow failed: {e}\n")
        return 1
    oauth.save_token(args.server, token)
    sys.stdout.write(f"saved token for {args.server} (expires at {token.expires_at.isoformat()})\n")
    return 0


# ---- subcommand: token-status ---------------------------------------


def cmd_token_status(args: argparse.Namespace) -> int:
    status = oauth.list_token_status()
    if args.json:
        sys.stdout.write(json.dumps(status, indent=2) + "\n")
        return 0
    if not status:
        sys.stdout.write("(no tokens stored)\n")
        return 0
    for server_id, info in status.items():
        delta = info["expires_in_seconds"]
        if delta < 0:
            human = f"expired {-delta}s ago"
        elif delta < 60:
            human = f"expires in {delta}s"
        elif delta < 3600:
            human = f"expires in {delta // 60}m"
        else:
            human = f"expires in {delta // 3600}h{(delta % 3600) // 60}m"
        refresh = "yes" if info["has_refresh_token"] else "no"
        scope = info["scope"] or "(none)"
        sys.stdout.write(f"{server_id:24}  {human:24}  refresh={refresh}  scope={scope}\n")
    return 0


# ---- subcommand: revoke ---------------------------------------------


def cmd_revoke(args: argparse.Namespace) -> int:
    removed = oauth.delete_token(args.server)
    if not removed:
        sys.stdout.write(f"no stored token for {args.server}\n")
        return 0
    sys.stdout.write(f"deleted token for {args.server}\n")
    return 0


# ---- subcommand: test ----------------------------------------------


def cmd_serve(args: argparse.Namespace) -> int:
    """``athena mcp serve`` — run a stdio MCP server exposing
    athena's curated tool surface (T3-02)."""
    from ..config import CONFIG_DIR, load_config
    from ..mcp.request_log import McpRequestLog
    from ..mcp.resources import AthenaMCPResources
    from ..mcp.server import AthenaMCPServer
    from ..mcp.tools import AthenaMCPTools
    from ..mcp.transport_stdio import run_stdio
    from ..safety.snapshots import SnapshotStore

    cfg = load_config()
    # Logs MUST go to stderr — stdout is the JSON-RPC wire.
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    workspace = Path(args.workspace).resolve() if args.workspace else Path.cwd()
    audit_dir = Path(args.audit_dir or (CONFIG_DIR / "audit")).expanduser()
    profile = args.profile or cfg.profile

    snapshot_store = SnapshotStore()
    tools = AthenaMCPTools(
        workspace=workspace,
        memory_profile=profile,
        audit_dir=audit_dir,
        snapshot_store=snapshot_store,
        allow_write=args.allow_write or cfg.mcp_allow_write,
    )
    resources = AthenaMCPResources(
        workspace=workspace,
        memory_profile=profile,
        audit_dir=audit_dir,
    )
    request_log = McpRequestLog(
        log_path=Path(args.log_path).expanduser()
        if args.log_path
        else Path(cfg.mcp_log_path).expanduser()
    )
    # T5-05.3 — differentiated capability surface (verified_write,
    # rollback_to, analyze_image, recall, ...). Manifest-driven:
    # only host-available tools land in tools/list.
    from ..mcp.differentiated import build_differentiated_tools

    differentiated = build_differentiated_tools(
        workspace=workspace,
        cfg=cfg,
        checkpoint_manager=None,  # CLI serve runs without an active session
    )
    server = AthenaMCPServer(
        tools=tools,
        resources=resources,
        request_log=request_log,
        differentiated=differentiated,
    )

    logging.getLogger("athena.mcp.cli").info(
        "athena mcp serve: stdio, workspace=%s, profile=%s, audit_dir=%s",
        workspace,
        profile,
        audit_dir,
    )

    transport = args.transport or cfg.mcp_default_transport
    if transport == "stdio":
        run_stdio(server)
        return 0
    if transport == "sse":
        sys.stderr.write(
            "athena mcp serve: SSE transport is reserved for a follow-up "
            "release. Use --transport stdio (the default) for now.\n"
        )
        return 2
    sys.stderr.write(f"athena mcp serve: unknown transport {transport!r}\n")
    return 2


def cmd_test(args: argparse.Namespace) -> int:
    """Connect to one server, run initialize + list_tools, print the
    tool catalog. Useful first-run validation."""
    servers = _load_server_configs(args.config)
    if args.server not in servers:
        sys.stderr.write(f"error: no server named {args.server!r} in mcp.json\n")
        return 2
    scfg = servers[args.server]
    if scfg.get("disabled"):
        sys.stdout.write(f"warning: server {args.server!r} is disabled in mcp.json\n")
    try:
        client = open_transport(args.server, scfg)
    except (ValueError, Exception) as e:
        sys.stderr.write(f"error: failed to open transport: {e}\n")
        return 1

    try:
        client.initialize()
        tools = client.list_tools()
    except Exception as e:
        sys.stderr.write(f"error: initialize / list_tools failed: {e}\n")
        try:
            client.close()
        except Exception:
            pass
        return 1

    if args.json:
        sys.stdout.write(json.dumps(tools, indent=2) + "\n")
    else:
        sys.stdout.write(f"{args.server}: {len(tools)} tools\n")
        for t in tools:
            name = t.get("name", "?")
            desc = (t.get("description") or "").split("\n")[0][:80]
            sys.stdout.write(f"  {name:30}  {desc}\n")
    client.close()
    return 0


# ---- subcommand: install -------------------- ---------------------


def cmd_install(args: argparse.Namespace) -> int:
    """Install an MCP server from a URL (e.g., mcpmarket.com installer).
    
    Fetches the installer script, runs it, and writes the resulting
    server configuration to mcp.json.
    """
    import subprocess
    import tempfile
    from urllib.request import urlopen
    from urllib.error import URLError, HTTPError

    try:
        # Fetch the installer script
        sys.stdout.write(f"fetching installer from {args.url}\n")
        sys.stdout.flush()
        try:
            with urlopen(args.url, timeout=30) as response:
                script = response.read().decode("utf-8")
        except HTTPError as e:
            sys.stderr.write(f"error: HTTP {e.code} from {args.url}\n")
            return 2
        except URLError as e:
            sys.stderr.write(f"error: failed to fetch {args.url}: {e}\n")
            return 2
    except Exception as e:
        sys.stderr.write(f"error: {e}\n")
        return 2

    # Run the installer script
    sys.stdout.write("running installer...\n")
    sys.stdout.flush()
    try:
        result = subprocess.run(
            ["bash", "-c", script],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except Exception as e:
        sys.stderr.write(f"error: installer failed: {e}\n")
        return 1

    if result.returncode != 0:
        sys.stderr.write(f"installer exited with code {result.returncode}\n")
        if result.stderr:
            sys.stderr.write(result.stderr)
        return 1

    # Read the generated mcp.json
    from ..config import CONFIG_DIR
    mcp_path = CONFIG_DIR / "mcp.json"
    if not mcp_path.exists():
        sys.stderr.write("error: installer did not create mcp.json\n")
        return 1

    try:
        data = json.loads(mcp_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        sys.stderr.write(f"error: failed to parse mcp.json: {e}\n")
        return 1

    sys.stdout.write(f"success: installed MCP server(s)\n")
    if "mcpServers" in data:
        for name in data["mcpServers"]:
            sys.stdout.write(f"  - {name}\n")

    return 0


# ---- helpers --------------------------------------------------------


def _load_server_configs(
    extra_path: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Merge every mcp.json in the search path. Later paths override
    earlier — matches the order :func:`load_mcp_servers` reads them."""
    paths = list(mcp_config_paths(Path.cwd()))
    if extra_path:
        paths.append(Path(extra_path).expanduser())
    merged: dict[str, dict[str, Any]] = {}
    for p in paths:
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        servers = data.get("mcpServers")
        if not isinstance(servers, dict):
            continue
        for name, scfg in servers.items():
            if isinstance(scfg, dict):
                merged[name] = scfg
    return merged


# ---- argument parser -----------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="athena mcp")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List every configured MCP server.")
    p_list.add_argument("--config", help="Extra mcp.json path to merge.")
    p_list.add_argument(
        "--json",
        action="store_true",
        help="JSON output for scripting.",
    )
    p_list.set_defaults(handler=cmd_list)

    p_auth = sub.add_parser(
        "auth",
        help="Run the OAuth flow for an HTTP/SSE server.",
    )
    p_auth.add_argument("server", help="server_id from mcp.json")
    p_auth.add_argument("--config", help="Extra mcp.json path to merge.")
    p_auth.add_argument(
        "--no-browser",
        action="store_true",
        help="Print the auth URL instead of opening a browser.",
    )
    p_auth.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Seconds to wait for the callback (default 300).",
    )
    p_auth.set_defaults(handler=cmd_auth)

    p_status = sub.add_parser(
        "token-status",
        help="Show stored token expiry / scope for each server.",
    )
    p_status.add_argument("--json", action="store_true")
    p_status.set_defaults(handler=cmd_token_status)

    p_revoke = sub.add_parser(
        "revoke",
        help="Delete the stored token for a server.",
    )
    p_revoke.add_argument("server", help="server_id whose token to delete")
    p_revoke.set_defaults(handler=cmd_revoke)

    p_serve = sub.add_parser(
        "serve",
        help="Run athena AS an MCP server (stdio) exposing curated tools.",
    )
    p_serve.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default=None,
        help="Transport (default: cfg.mcp_default_transport, usually stdio).",
    )
    p_serve.add_argument(
        "--workspace",
        help="Workspace for skill discovery (default: cwd).",
    )
    p_serve.add_argument(
        "--profile",
        help="Memory profile (default: cfg.profile).",
    )
    p_serve.add_argument(
        "--audit-dir",
        help="Audit log dir (default: ~/.athena/audit).",
    )
    p_serve.add_argument(
        "--allow-write",
        action="store_true",
        help="Enable write-capable tools (reserved; none ship yet).",
    )
    p_serve.add_argument(
        "--log-path",
        help="Override cfg.mcp_log_path (per-request JSONL audit log).",
    )
    p_serve.set_defaults(handler=cmd_serve)

    p_test = sub.add_parser(
        "test",
        help="Connect to one server and list its tools (validation).",
    )
    p_test.add_argument("server", help="server_id from mcp.json")
    p_test.add_argument("--config", help="Extra mcp.json path to merge.")
    p_test.add_argument("--json", action="store_true")
    p_test.set_defaults(handler=cmd_test)

    return ap


def main(argv: list[str]) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.handler(args) or 0)
