"""MCP capability bucket.

Verifies the agent can discover MCP servers via the workspace's
``mcp.json``, invoke their tools, and surface the results. The
verifier reads each task's call-log JSONL (written by the mock
server) to confirm the RIGHT tool was called with the RIGHT args
— catches the "model said it called X but actually called Y"
class of bug that text-eval misses.

Each task's setup_fn:
  1. Writes ``workspace/mcp.json`` pointing at a mock server.
  2. Initializes an empty ``mcp_call_log.jsonl`` so verifier knows
     where to look.

Each task's verify_fn:
  1. Reads the call log.
  2. Confirms the expected tool fired with matching args.
  3. (Optionally) Confirms the assistant text reflects the result.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from ..task import EvalTask, VerifyContext
from ._mcp_helpers import (
    demo_server_config,
    find_call,
    mock_users_server_config,
    read_call_log,
    write_workspace_mcp_config,
)

_BUCKET = "mcp"


# ---------------------------------------------------------------------------
# Setup helpers: write workspace/mcp.json + pre-create empty call log
# ---------------------------------------------------------------------------


def _setup_demo_server(ws: Path) -> None:
    write_workspace_mcp_config(ws, {"demo": demo_server_config(ws)})


def _setup_users_server(ws: Path) -> None:
    write_workspace_mcp_config(ws, {"users": mock_users_server_config(ws)})


def _setup_both_servers(ws: Path) -> None:
    write_workspace_mcp_config(
        ws,
        {"demo": demo_server_config(ws), "users": mock_users_server_config(ws)},
    )


# ---------------------------------------------------------------------------
# 1. echo: simplest MCP tool call
# ---------------------------------------------------------------------------


def _verify_echo(ctx: VerifyContext) -> bool:
    log = read_call_log(ctx.workspace)
    call = find_call(log, tool="echo", arg_match={"text": "hello athena"})
    return call is not None


_echo_call = EvalTask(
    id="mcp.echo_call",
    prompt=(
        "There's an MCP server called 'demo' available with an "
        "'echo' tool that takes a 'text' parameter. Call the echo "
        "tool with the text 'hello athena'."
    ),
    setup_fn=_setup_demo_server,
    verify_fn=_verify_echo,
    bucket=_BUCKET,
    description="Call demo MCP's echo tool with a specific string.",
)


# ---------------------------------------------------------------------------
# 2. add: numeric MCP tool with two args
# ---------------------------------------------------------------------------


def _verify_add(ctx: VerifyContext) -> bool:
    log = read_call_log(ctx.workspace)
    # Accept int or float arg shapes (the model may pass either).
    for entry in log:
        if entry.get("tool") != "add":
            continue
        args: dict[str, Any] = entry.get("args") or {}
        try:
            # args.get(...) is Any | None; None raises TypeError, caught below.
            a = float(cast("Any", args.get("a")))
            b = float(cast("Any", args.get("b")))
        except (TypeError, ValueError):
            continue
        if {a, b} == {17.0, 25.0}:
            return True
    return False


_add_call = EvalTask(
    id="mcp.add_call",
    prompt=(
        "Use the demo MCP server's 'add' tool to compute 17 + 25. "
        "The tool takes two numeric arguments: 'a' and 'b'."
    ),
    setup_fn=_setup_demo_server,
    verify_fn=_verify_add,
    bucket=_BUCKET,
    description="Call demo MCP's add tool with two specific numeric args.",
)


# ---------------------------------------------------------------------------
# 3. add with answer surfaced in assistant reply
# ---------------------------------------------------------------------------


def _verify_add_and_report(ctx: VerifyContext) -> bool:
    log = read_call_log(ctx.workspace)
    if not _verify_add(ctx):  # ensure the right call fired
        return False
    # Plus: the assistant should mention the result (42) in its reply.
    for m in reversed(ctx.agent_messages):
        if m.get("role") == "assistant":
            c = m.get("content")
            if isinstance(c, str) and "42" in c:
                return True
            break
    return False


_add_and_report = EvalTask(
    id="mcp.add_and_report",
    prompt=(
        "Use the demo MCP server's 'add' tool to compute 17 + 25, "
        "then tell me the result in your reply. Include the number "
        "in your response."
    ),
    setup_fn=_setup_demo_server,
    verify_fn=_verify_add_and_report,
    bucket=_BUCKET,
    description="Call MCP add and surface the result in the reply.",
)


# ---------------------------------------------------------------------------
# 4. current_time: zero-arg tool
# ---------------------------------------------------------------------------


def _verify_current_time(ctx: VerifyContext) -> bool:
    log = read_call_log(ctx.workspace)
    return find_call(log, tool="current_time", arg_match={}) is not None


_current_time = EvalTask(
    id="mcp.current_time",
    prompt=(
        "The demo MCP server exposes a 'current_time' tool that "
        "returns the current ISO-8601 timestamp and takes no "
        "arguments. Call it."
    ),
    setup_fn=_setup_demo_server,
    verify_fn=_verify_current_time,
    bucket=_BUCKET,
    description="Call MCP tool with no arguments.",
)


# ---------------------------------------------------------------------------
# 5. get_user: targeted lookup
# ---------------------------------------------------------------------------


def _verify_get_user(ctx: VerifyContext) -> bool:
    log = read_call_log(ctx.workspace)
    return find_call(log, tool="get_user", arg_match={"id": "3"}) is not None


_get_user = EvalTask(
    id="mcp.get_user",
    prompt=(
        "The 'users' MCP server exposes a 'get_user' tool that takes "
        "an 'id' parameter (a string). Look up the user with id '3'."
    ),
    setup_fn=_setup_users_server,
    verify_fn=_verify_get_user,
    bucket=_BUCKET,
    description="Call get_user with a specific id string.",
)


# ---------------------------------------------------------------------------
# 6. get_user + surface the name in assistant reply
# ---------------------------------------------------------------------------


def _verify_get_user_surface_name(ctx: VerifyContext) -> bool:
    # The right call must have fired AND the assistant's reply must
    # mention "Linus" (the fixture name for id=3).
    if not _verify_get_user(ctx):
        return False
    for m in reversed(ctx.agent_messages):
        if m.get("role") == "assistant":
            c = m.get("content")
            if isinstance(c, str) and "Linus" in c:
                return True
            break
    return False


_get_user_surface_name = EvalTask(
    id="mcp.get_user_surface_name",
    prompt=(
        "Use the 'users' MCP server's get_user tool to look up the "
        "user with id '3', then tell me their name in your reply."
    ),
    setup_fn=_setup_users_server,
    verify_fn=_verify_get_user_surface_name,
    bucket=_BUCKET,
    description="Call MCP, surface a specific result field in the reply.",
)


# ---------------------------------------------------------------------------
# 7. list_users: tool with no required args
# ---------------------------------------------------------------------------


def _verify_list_users(ctx: VerifyContext) -> bool:
    log = read_call_log(ctx.workspace)
    return find_call(log, tool="list_users", arg_match={}) is not None


_list_users = EvalTask(
    id="mcp.list_users",
    prompt=(
        "The 'users' MCP server has a 'list_users' tool that takes "
        "no arguments and returns every user. Call it."
    ),
    setup_fn=_setup_users_server,
    verify_fn=_verify_list_users,
    bucket=_BUCKET,
    description="Call MCP list_users (zero-arg, returns all).",
)


# ---------------------------------------------------------------------------
# 8. Don't make a bogus call when no MCP is available
# ---------------------------------------------------------------------------


def _setup_no_mcp(ws: Path) -> None:
    # Deliberately NO mcp.json — exercise the "I don't have that
    # tool, I'll explain" path. Empty call log expected.
    pass


def _verify_no_phantom_calls(ctx: VerifyContext) -> bool:
    log = read_call_log(ctx.workspace)
    return len(log) == 0


_no_phantom_calls = EvalTask(
    id="mcp.no_phantom_calls",
    prompt=(
        "There's no MCP server configured in this workspace. Don't "
        "try to call any external tool — just reply briefly that you "
        "can't perform the request."
    ),
    setup_fn=_setup_no_mcp,
    verify_fn=_verify_no_phantom_calls,
    bucket=_BUCKET,
    description="Negative test: don't call MCP tools that don't exist.",
)


# ---------------------------------------------------------------------------
# 9. Composition: two MCP calls (echo then add)
# ---------------------------------------------------------------------------


def _verify_two_calls(ctx: VerifyContext) -> bool:
    log = read_call_log(ctx.workspace)
    has_echo = find_call(log, tool="echo") is not None
    has_add = find_call(log, tool="add") is not None
    return has_echo and has_add


_two_calls = EvalTask(
    id="mcp.two_calls",
    prompt=(
        "The demo MCP server has both an 'echo' tool (takes a 'text' "
        "arg) and an 'add' tool (takes 'a' and 'b'). Call echo once "
        "with text='ready', then call add with a=10 and b=20."
    ),
    setup_fn=_setup_demo_server,
    verify_fn=_verify_two_calls,
    bucket=_BUCKET,
    description="Sequence two MCP tool calls in one turn.",
    timeout_s=90.0,
)


# ---------------------------------------------------------------------------
# 10. Choose the right tool from two available servers
# ---------------------------------------------------------------------------


def _verify_picked_users_server(ctx: VerifyContext) -> bool:
    """Asked to look up a user — should call users.get_user, NOT
    demo.echo or demo.add."""
    log = read_call_log(ctx.workspace)
    return (
        find_call(log, tool="get_user", arg_match={"id": "1"}) is not None
        and find_call(log, tool="echo") is None
    )


_pick_right_server = EvalTask(
    id="mcp.pick_right_server",
    prompt=(
        "Two MCP servers are configured: 'demo' (echo, add, "
        "current_time) and 'users' (get_user, list_users). Look up "
        "the user with id '1' — pick the right tool for the job."
    ),
    setup_fn=_setup_both_servers,
    verify_fn=_verify_picked_users_server,
    bucket=_BUCKET,
    description="Select the right MCP tool among multiple servers.",
    timeout_s=90.0,
)


TASKS: list[EvalTask] = [
    _echo_call,
    _add_call,
    _add_and_report,
    _current_time,
    _get_user,
    _get_user_surface_name,
    _list_users,
    _no_phantom_calls,
    _two_calls,
    _pick_right_server,
]

__all__ = ["TASKS"]
