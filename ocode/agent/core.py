"""Agent loop: ferry messages between user, Ollama, and tools until done."""
from __future__ import annotations
import contextvars
import json
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import hooks, tools, ui
from ..safety.approval_callback import get_approval_callback
from ..config import Config
from ..ollama_client import OllamaClient
from ..prompts import build_system_prompt


_FENCE_RE = re.compile(r"```(?:json)?\s*(.+?)\s*```", re.S)
_TOOL_CALL_TAG_RE = re.compile(r"<tool_call>\s*(.+?)\s*</tool_call>", re.S)
# harmony / GPT-OSS style: <function=name>\n<parameter=key>\nvalue\n</parameter>\n</function>
_FUNCTION_TAG_RE = re.compile(r"<function=([^>\s]+)>(.*?)</function>", re.S)
_PARAMETER_TAG_RE = re.compile(r"<parameter=([^>\s]+)>(.*?)</parameter>", re.S)
_STRAY_TC_RE = re.compile(r"</?tool_call>")


def _coerce_arg(v: str) -> Any:
    """Best-effort type coercion for harmony-style string params (int, bool, json)."""
    s = v.strip()
    if not s:
        return ""
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return s

# Cap for OCODE.md / MEMORY.md when injecting into the system prompt. Anything
# larger gets truncated with a notice so a runaway document can't blow context.
_MAX_DOCUMENT_BYTES = 32_000


# ContextVar so a fork running on its own thread can register itself as the
# current parent for any grand-children it spawns, without clobbering the
# foreground agent on the main thread.
_current_agent: contextvars.ContextVar["Agent | None"] = contextvars.ContextVar(
    "ocode_current_agent", default=None
)


def get_current_agent() -> "Agent | None":
    """Return the Agent whose run_turn is currently active on this context, or None."""
    return _current_agent.get()


def _normalize_tool_call(obj: Any) -> list[dict]:
    """Normalize various tool-call shapes into Ollama's wrapped format."""
    if isinstance(obj, list):
        out: list[dict] = []
        for item in obj:
            out.extend(_normalize_tool_call(item))
        return out
    if not isinstance(obj, dict):
        return []
    if "name" in obj and "arguments" in obj and isinstance(obj.get("arguments"), (dict, str)):
        return [{"function": {"name": obj["name"], "arguments": obj["arguments"]}}]
    if "function" in obj and isinstance(obj["function"], dict):
        fn = obj["function"]
        if "name" in fn:
            return [{"function": {"name": fn["name"], "arguments": fn.get("arguments", {})}}]
    if "tool_calls" in obj and isinstance(obj["tool_calls"], list):
        return _normalize_tool_call(obj["tool_calls"])
    return []


def _extract_text_tool_calls(text: str) -> tuple[str, list[dict]]:
    """Recover tool calls from content text when the model emits them as JSON
    or as <tool_call>...</tool_call> tags instead of using Ollama's tool_calls
    field. Some Ollama+model combos leak tool calls into content under
    streaming; this fallback makes ocode robust to that failure mode.
    """
    s = text.strip()
    if not s:
        return text, []

    # Qwen's native <tool_call>...</tool_call> XML tags (sometimes leaked as text)
    tag_matches = _TOOL_CALL_TAG_RE.findall(s)
    if tag_matches:
        all_calls: list[dict] = []
        bad = 0
        for m in tag_matches:
            try:
                obj = json.loads(m)
                all_calls.extend(_normalize_tool_call(obj))
            except json.JSONDecodeError:
                bad += 1
                continue
        if all_calls:
            residual = _TOOL_CALL_TAG_RE.sub("", s).strip()
            return residual, all_calls
        if bad:
            ui.warn(f"found {bad} <tool_call> tag(s) but none parsed as JSON")

    # Harmony / GPT-OSS style <function=name><parameter=key>val</parameter></function>
    fn_matches = list(_FUNCTION_TAG_RE.finditer(s))
    if fn_matches:
        all_calls: list[dict] = []
        for fm in fn_matches:
            name = fm.group(1).strip()
            body = fm.group(2)
            args: dict[str, Any] = {}
            for pm in _PARAMETER_TAG_RE.finditer(body):
                args[pm.group(1).strip()] = _coerce_arg(pm.group(2))
            all_calls.append({"function": {"name": name, "arguments": args}})
        if all_calls:
            residual = _FUNCTION_TAG_RE.sub("", s)
            residual = _STRAY_TC_RE.sub("", residual).strip()
            return residual, all_calls

    # Whole-text JSON
    try:
        obj = json.loads(s)
        calls = _normalize_tool_call(obj)
        if calls:
            return "", calls
    except json.JSONDecodeError:
        pass

    # Code-fenced JSON
    m = _FENCE_RE.search(s)
    if m:
        try:
            obj = json.loads(m.group(1))
            calls = _normalize_tool_call(obj)
            if calls:
                return (s[: m.start()] + s[m.end() :]).strip(), calls
        except json.JSONDecodeError:
            pass

    return text, []



# System prompt is assembled dynamically from ocode.prompts.build_system_prompt().
# Sections live in ocode/prompts/system.py.


@dataclass
class Stats:
    prompt_tokens: int = 0
    eval_tokens: int = 0
    tool_calls: int = 0
    turns: int = 0
    started: float = field(default_factory=time.time)


class Agent:
    def __init__(self, cfg: Config, workspace: Path, model: str | None = None):
        self.cfg = cfg
        self.workspace = workspace.resolve()
        self.model = model or cfg.model
        self.client = OllamaClient(cfg.ollama_host)
        self.messages: list[dict[str, Any]] = []
        self.stats = Stats()
        # Cache for Modelfile SYSTEM keyed by model name; avoids re-fetching
        # on every /clear or /resume. Invalidated implicitly by /model switching
        # to an unseen model name.
        self._model_system_cache: dict[str, str] = {}
        # Serializes run_turn so the REPL thread and a /loop thread cannot
        # interleave turns or corrupt self.messages.
        self._turn_lock = threading.Lock()
        # Configure tools with workspace
        tools.file_ops.set_workspace(self.workspace, max_read=cfg.max_file_read)
        tools.shell.set_max_output(cfg.max_bash_output)
        # Load hooks from user + workspace settings.json
        hooks.load_hooks(self.workspace)
        # Build initial system message
        self.messages.append({"role": "system", "content": self._build_system()})

    def _build_system(self) -> str:
        # Modelfile SYSTEM (persona); Ollama drops it when we send our own
        # system message, so re-include it ourselves. Cached per-model.
        if self.model in self._model_system_cache:
            ms = self._model_system_cache[self.model]
        else:
            ms = ""
            try:
                info = self.client.show_model(self.model)
                ms = (info.get("system") or "").strip()
                if ms:
                    ui.info(f"inherited SYSTEM from {self.model} ({len(ms)} chars)")
            except Exception as e:
                ui.info(f"could not fetch model SYSTEM ({e}); using rules only")
            self._model_system_cache[self.model] = ms
        model_system: str | None = ms or None

        project_context: str | None = None
        ocode_md = self.workspace / "OCODE.md"
        if ocode_md.exists():
            try:
                raw = ocode_md.read_text(encoding="utf-8")
                if len(raw) > _MAX_DOCUMENT_BYTES:
                    ui.warn(
                        f"OCODE.md is {len(raw)} bytes; truncating to "
                        f"{_MAX_DOCUMENT_BYTES} for context safety"
                    )
                    project_context = raw[:_MAX_DOCUMENT_BYTES] + "\n\n[truncated]"
                else:
                    project_context = raw
                ui.info(f"loaded OCODE.md ({len(project_context)} bytes)")
            except OSError:
                pass

        memory_index: str | None = None
        try:
            from ..memory import load_memory_index
            memory_index = load_memory_index(self.workspace)
            if memory_index:
                if len(memory_index) > _MAX_DOCUMENT_BYTES:
                    ui.warn(
                        f"MEMORY.md is {len(memory_index)} bytes; truncating to "
                        f"{_MAX_DOCUMENT_BYTES} for context safety"
                    )
                    memory_index = memory_index[:_MAX_DOCUMENT_BYTES] + "\n\n[truncated]"
                ui.info(f"loaded MEMORY.md ({len(memory_index)} bytes)")
        except Exception as e:
            ui.info(f"memory load failed: {e}")

        return build_system_prompt(
            workspace=self.workspace,
            model=self.model,
            project_context=project_context,
            memory_index=memory_index,
            model_modelfile_system=model_system,
            lean=self.cfg.lean_prompt,
            disabled_sections=self.cfg.disabled_prompt_sections,
        )

    def reset(self) -> None:
        """Wipe history but keep the system prompt."""
        self.messages = [{"role": "system", "content": self._build_system()}]
        self.stats = Stats()
        ui.info("conversation cleared")

    def run_turn(self, user_input: str) -> None:
        """Run one user turn to completion (model may call tools several times)."""
        with self._turn_lock:
            token = _current_agent.set(self)
            try:
                self._run_turn_inner(user_input)
            finally:
                _current_agent.reset(token)

    def _run_turn_inner(self, user_input: str) -> None:
        # UserPromptSubmit hook — can cancel the turn
        allow, msg = hooks.fire("UserPromptSubmit", payload={"prompt": user_input})
        if not allow:
            ui.error(f"prompt cancelled by hook: {msg}")
            return
        self.messages.append({"role": "user", "content": user_input})
        self.stats.turns += 1

        # Loop until the model produces a final assistant message with no tool calls.
        max_steps = max(1, int(self.cfg.max_turn_steps))
        for step in range(max_steps):
            assistant_text, tool_calls, raw_done = self._stream_one()
            interrupted = bool(raw_done and raw_done.get("_interrupted"))

            # Track usage if Ollama reported it (skip phantom raw on interrupt)
            if raw_done and not interrupted:
                self.stats.prompt_tokens += raw_done.get("prompt_eval_count", 0) or 0
                self.stats.eval_tokens += raw_done.get("eval_count", 0) or 0

            # Record the assistant message (with tool_calls if any) into history
            assistant_msg: dict[str, Any] = {"role": "assistant", "content": assistant_text}
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            self.messages.append(assistant_msg)

            if interrupted:
                # The stream was cut mid-flight. If the model had emitted tool_calls
                # before the interrupt, mark them DENIED so the next turn doesn't
                # see dangling calls. Then leave a marker so the model knows.
                for call in tool_calls or []:
                    fname = (call.get("function") or {}).get("name", "?")
                    self._record_tool_result(call, fname, "DENIED: response interrupted by user (Ctrl+C)")
                self.messages.append({
                    "role": "user",
                    "content": "[previous response was interrupted by the user]",
                })
                # No Stop hook — the turn didn't complete.
                return

            if not tool_calls:
                self._fire_stop("completed")
                return

            # Execute each tool call and append a tool message for it.
            # If the user interrupts mid-loop, mark unexecuted calls DENIED so
            # the assistant message's tool_calls are all paired with replies.
            asst_idx = len(self.messages) - 1
            try:
                for call in tool_calls:
                    self._handle_tool_call(call)
            except KeyboardInterrupt:
                ui.warn("interrupted during tool execution")
                # Count is robust to interrupts firing anywhere in the loop body.
                recorded = sum(1 for m in self.messages[asst_idx + 1:] if m.get("role") == "tool")
                for missing in tool_calls[recorded:]:
                    fname = (missing.get("function") or {}).get("name", "?")
                    self._record_tool_result(missing, fname, "DENIED: tool execution interrupted by user (Ctrl+C)")
                self.messages.append({
                    "role": "user",
                    "content": "[previous tool execution was interrupted by the user]",
                })
                return

        ui.warn(f"reached step limit ({max_steps}); stopping for safety.")
        self._fire_stop("step_limit")

    def _fire_stop(self, reason: str) -> None:
        hooks.fire("Stop", payload={
            "reason": reason,
            "stats": {
                "turns": self.stats.turns,
                "tool_calls": self.stats.tool_calls,
                "prompt_tokens": self.stats.prompt_tokens,
                "eval_tokens": self.stats.eval_tokens,
            },
        })

    def _stream_one(self) -> tuple[str, list[dict[str, Any]], dict[str, Any] | None]:
        """One model turn. Streams text to stdout, returns (text, tool_calls, final_chunk)."""
        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        final: dict[str, Any] | None = None

        # Spinner during the silent first-token wait (partial-offload models can
        # take 5-30s before the first chunk). Stop it the moment any chunk lands.
        status = ui.console.status("[dim]thinking…[/]", spinner="dots")
        status.start()
        first = True
        try:
            for chunk in self.client.chat(
                model=self.model,
                messages=self.messages,
                tools=tools.ollama_schema(
                    enabled_toolsets=self.cfg.enabled_toolsets,
                    disabled=self.cfg.disabled_tools,
                ),
                num_ctx=self.cfg.context_window,
            ):
                if first and (chunk.content or chunk.tool_calls):
                    status.stop()
                    ui.console.print("[bold #00ff00]▌[/] ", end="")
                    first = False
                if chunk.content:
                    ui.console.print(chunk.content, end="", soft_wrap=True, highlight=False)
                    text_parts.append(chunk.content)
                if chunk.tool_calls:
                    tool_calls.extend(chunk.tool_calls)
                if chunk.done:
                    final = chunk.raw
        except KeyboardInterrupt:
            if first:
                status.stop()
            ui.console.print()
            ui.warn("interrupted")
            # Signal interruption to run_turn via a sentinel on raw_done.
            return "".join(text_parts), tool_calls, {"_interrupted": True}
        except Exception as e:
            if first:
                status.stop()
            ui.console.print()
            ui.error(f"ollama error: {e}")
            return "".join(text_parts), [], None
        finally:
            # Tool-only or empty responses never trip the in-loop stop().
            if first:
                status.stop()
        ui.console.print()  # newline after the streamed reply
        if final:
            ui.stream_stats(final)
        text = "".join(text_parts)
        # Recovery: if the model emitted tool-call JSON as content instead of
        # using Ollama's tool_calls field, parse it out and treat as tool calls.
        if not tool_calls and text.strip():
            residual, recovered = _extract_text_tool_calls(text)
            if recovered:
                tool_calls = recovered
                text = residual
                ui.info(f"recovered {len(recovered)} tool call(s) from content")
        return text, tool_calls, final

    def _handle_tool_call(self, call: dict[str, Any]) -> None:
        fn = call.get("function", {}) or {}
        name = fn.get("name", "")
        args_raw = fn.get("arguments", {})
        # Ollama may give us a dict or a JSON string depending on model
        if isinstance(args_raw, str):
            try:
                args = json.loads(args_raw) if args_raw.strip() else {}
            except json.JSONDecodeError:
                args = {}
        else:
            args = args_raw or {}

        ui.tool_call_summary(name, args)
        self.stats.tool_calls += 1

        # Plan-mode gate: only read-only tools are allowed
        from ..tools import plan as plan_mod
        if plan_mod.is_plan_mode() and name not in plan_mod.PLAN_MODE_ALLOWED:
            denied = (
                f"BLOCKED: tool {name!r} is not allowed in plan mode. "
                "Use Read/Glob/Grep/WebFetch/WebSearch to investigate, then "
                "call ExitPlanMode with the proposed plan."
            )
            self._record_tool_result(call, name, denied)
            ui.warn(denied)
            return

        t = tools.get_tool(name)
        # Confirmation gate for destructive tools.
        # For Bash, an allowlist short-circuits the prompt.
        if t and t.requires_confirmation and not self.cfg.auto_approve_tools:
            allowed = False
            if name in ("Bash", "bash"):
                cmd = (args.get("command") or "").strip()
                # Word-boundary match: prefix "ls" must not allow "lsof".
                allowed = any(cmd == p or cmd.startswith(p + " ") for p in self.cfg.bash_allowlist)
            if not allowed:
                preview = args.get("command") or json.dumps(args)
                ui.console.print(f"[yellow]command:[/] [white]{preview}[/]")
                if get_approval_callback()(name, args) != "allow":
                    result = "DENIED by user"
                    self._record_tool_result(call, name, result)
                    return

        # PreToolUse hook can block
        allow, hook_msg = hooks.fire("PreToolUse", tool_name=name, payload={"tool_args": args})
        if not allow:
            blocked = f"BLOCKED by PreToolUse hook: {hook_msg}"
            self._record_tool_result(call, name, blocked)
            ui.warn(blocked)
            return

        # Show diffs for Write/write_file before they happen
        if name in ("Write", "write_file"):
            self._preview_write(args)

        result = tools.dispatch(name, args)
        ui.tool_result(name, result)

        # PostToolUse hook is informational only
        hooks.fire("PostToolUse", tool_name=name, payload={"tool_args": args, "result": result})

        self._record_tool_result(call, name, result)

    def _preview_write(self, args: dict[str, Any]) -> None:
        # Accept both Claude-Code-style file_path/content and ocode-style path/content
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
        msg: dict[str, Any] = {"role": "tool", "name": name, "content": result}
        # Some Ollama models send a tool_call_id; preserve when present
        if "id" in call:
            msg["tool_call_id"] = call["id"]
        self.messages.append(msg)

    def close(self) -> None:
        self.client.close()


# Bind fork() as an Agent method. Done at module load so `Agent(...).fork(...)`
# works without circular-import gymnastics in callers.
from .fork import fork as _fork_impl  # noqa: E402

def _agent_fork(self, **kwargs):
    return _fork_impl(self, **kwargs)

Agent.fork = _agent_fork
