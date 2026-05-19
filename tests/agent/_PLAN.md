# tests/agent/ surface inventory and test plan (T1-04.1)

Written before any tests in this directory exist. Future contributors
reading this should understand WHY the fixtures and assertions look
the way they do — and where the spec skeletons in
`phase-T1-04-agent-tests.md` diverge from athena's actual surface.

## Files inventoried

### `athena/agent/core.py` (~1400 LOC)

- **Public surface (callable from outside the class):**
  - `Agent.__init__(cfg, workspace, *, model=None, client=None, provider=None, session_store=None, parent_session_id=None, plugin_hooks=None, resume_session_id=None)` — at line 255. Provider can be passed as `provider=` or legacy `client=`. When neither is passed, `resolve_provider(cfg.model, cfg, pool)` is called, which means a NetworkProvider may be constructed (Ollama → no network at construct time; hosted → still no network, just an httpx client).
  - `Agent.run_turn(user_input)` — sync; line 575. Pumps one user message through the model + tool loop.
  - `Agent.run_until_done(user_prompt="", *, max_iterations=None)` — sync; line 1090. Thin wrapper around `run_turn` that pins `max_turn_steps` for the call.
  - `Agent.close()` — line 1130 area. Lifecycle teardown.
  - `Agent.last_assistant_message()` — convenience reader for gateway dispatch.
  - `Agent.tool_call_trace()` — flat list of `{name, arguments, id}` recorded during a turn.

- **Side effects:**
  - Filesystem: `<profile_dir>/sessions/<id>.jsonl` writes per turn, `<profile_dir>/.status.json` atomic snapshot at end of every turn.
  - ContextVars: `_current_agent` (the agent currently running), `_write_origin` (provenance for mutations), approval callback (per-thread).
  - Plugin hooks: fires `on_session_start`, `on_user_message`, `pre_tool_call`, `post_tool_call`, `on_assistant_message`, `on_session_end`.
  - Network: only via `self.provider.stream_chat(...)` and `self.provider.list_models()` — both deferred to runtime.

- **Dependencies on other athena modules:** `athena.config`, `athena.providers.runtime_resolver`, `athena.sessions.store`, `athena.tools`, `athena.skills`, `athena.memory`, `athena.plugins.hooks`, `athena.commands.*`, `athena.provenance`, `athena.safety.approval_callback`, `athena.ui`, `athena.prompts.system`.

### `athena/agent/fork.py` (~250 LOC)

- **Public surface:**
  - `fork(parent_agent, *, enabled_toolsets, system_addendum, user_prompt="", conversation_history=None, max_iterations=16, write_origin=BACKGROUND_REVIEW, auxiliary_client=True, quiet=True, disabled_tools=None) -> ForkResult` — line 84. NOT a method on Agent; it's a module-level function that *receives* the parent agent.
  - `ForkAction` dataclass (line 57): represents a structured action extracted from the fork's tool-result hints.
  - `ForkResult` dataclass (line 73): `final_response`, `tool_calls`, `actions`, `stdout`, `stderr`, `error`, `duration_s`, `child_session_id`.

- **Side effects:**
  - Spawns one `threading.Thread(daemon=True)` per fork call.
  - Inside the thread: `set_current_write_origin(write_origin)`, `set_approval_callback(AUTO_DENY)`, `scope_fresh_approvals()`, `_current_agent.set(child)`. All released in a `finally` on thread exit.
  - Redirects stdout/stderr to per-call buffers when `quiet=True`.
  - Calls `build_auxiliary_client(parent_agent)` when `auxiliary_client=True` — that constructs a fresh provider instance (separate httpx client from parent).
  - Joins the thread synchronously (`t.join()`) before returning ForkResult. So fork() is **blocking** even though the child runs on a daemon thread.

- **Dependencies:** `athena.agent.core` (deferred import to break cycle), `athena.agent.auxiliary_client`, `athena.provenance`, `athena.safety.approval_callback`, `athena.safety.approval_guard`.

### `athena/agent/auxiliary_client.py` (~30 LOC)

- **Public surface:** `build_auxiliary_client(parent_agent) -> Provider`. Routes through `resolve_provider(parent.cfg.model, parent.cfg, global_pool())` and returns the resulting provider. Discards the bare-model return so the parent's `self.model` is what stays on the agent.

- **Side effects:** None at construction time. The Provider returned has its own httpx client (or whatever transport).

### `athena/providers/base.py`

**The spec's FakeProvider skeleton uses `async def stream_chat`. That is wrong for athena.** athena's `Provider.stream_chat` is **synchronous** and returns `Iterator[StreamChunk]`. The FakeProvider here must mirror that exactly:

```python
def stream_chat(
    self,
    *,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    **kwargs: Any,
) -> Iterator[StreamChunk]:
    ...
    yield StreamChunk(kind="content", payload="hi")
```

Likewise `Agent.run_turn` and `Agent.run_until_done` are **synchronous**, called from `asyncio.to_thread(...)` in the gateway path. Tests are plain `def`, not `async def`. No `@pytest.mark.asyncio` decoration on the agent tests.

`StreamChunk` has just two fields:
- `kind: Literal["content", "tool_call", "usage", "end"]`
- `payload: Any` (str for content, dict for tool_call, dict for usage, str/None for end)

### `athena/config.py`

- `Config` dataclass with ~40 fields. Construction is free-of-side-effects; `load_config()` does the file read.
- `~/.athena/` is resolved via `Path.home() / ".athena"` lazily in `safety/context.py:_root_for()`. **There is no `ATHENA_HOME` env var.** The spec's `monkeypatch.setenv("ATHENA_HOME", ...)` will not work. Use `tests/conftest.py:isolated_home` which already monkeypatches `Path.home()` to a tmp path.

### `athena/provenance.py`

- ContextVar: `_write_origin` with default `FOREGROUND`. Setter `set_current_write_origin(origin) -> Token`, reader `get_current_write_origin() -> str`, restore `reset_current_write_origin(token)`. Validates origin against `{FOREGROUND, BACKGROUND_REVIEW, CURATOR, MIGRATION, SYSTEM}`.

### `athena/safety/approval_callback.py`

- ContextVar holding a callable `(tool_name, args) -> Literal["allow", "deny"]`. Default is the interactive console prompt. Forks install `AUTO_DENY` which returns `"deny"` for every call.

### `tests/conftest.py`

- Existing fixtures: `isolated_home` (monkeypatches `Path.home()` to a tmp path, makes `~/.athena/` tmp-rooted), `workspace` (a tmp_path/"workspace" dir), `write_skill` (factory for fabricating SKILL.md files).
- These already meet the spec's `isolated_profile_dir` need — reuse rather than re-invent.

### `tests/test_fork_full.py`

- Existing integration test. Uses a `FakeClient` (not FakeProvider — older naming) constructed inline. Goes through the FULL fork flow with a fake provider that yields canned chunks. Useful template; our FakeProvider here mirrors its shape but lives in `tests/agent/conftest.py` for reuse.

## Concrete divergences from the design doc skeletons

| Spec assumption | Actual athena reality |
|---|---|
| `async def stream_chat` | sync `def stream_chat` returning `Iterator[StreamChunk]` |
| `await agent.run_turn(...)` | `agent.run_turn(user_input)` — sync, no return value (sets state on `agent.messages`) |
| `ATHENA_HOME` env var | `Path.home() / ".athena"`; isolate via `monkeypatch.setattr(Path, "home", ...)` (already done in conftest) |
| `Agent(config=cfg, provider=fake_provider, profile_dir=...)` | `Agent(cfg, workspace, provider=fake_provider)` — no `profile_dir` kwarg; SessionStore resolves from `cfg.profile` |
| `tool_calls = agent.run_turn(...)` return value | `agent.run_turn` returns `None`. The result lives in `agent.messages`, `agent.stats.tool_call_counts`, `agent.tool_call_trace()` |
| `pytest.mark.asyncio` on every test | Not needed — agent tests are plain `def`, no async |

## Fixture file shape

JSONL files in `tests/agent/fixtures/` hold one scenario per file. Each
line is a JSON object that becomes one `StreamChunk`. Optional
`"scenario": N` key groups chunks into separate sequential calls
(for multi-turn scripts).

```jsonl
{"kind": "content", "payload": "Hello"}
{"kind": "content", "payload": ", world."}
{"kind": "usage", "payload": {"prompt_tokens": 10, "completion_tokens": 3}}
{"kind": "end", "payload": null}
```

For tool calls:

```jsonl
{"kind": "tool_call", "payload": {"id": "call_1", "name": "Read", "arguments": {"file_path": "foo.py"}}}
{"kind": "end", "payload": null}
```

## Proposed test files

- `test_agent_init.py` — Agent construction is offline; respects `enabled_toolsets`; loads `ATHENA.md`.
- `test_core_run_turn.py` — single-turn plain text; single tool call; provenance ContextVar visible to dispatch; KeyboardInterrupt handling; oversized tool output truncation.
- `test_core_run_until_done.py` — loop exits on no-more-tool-calls; respects `max_iterations`; drains pending steers; injects goal at system prompt rebuild; persists every message to SessionStore JSONL.
- `test_fork.py` — daemon thread; isolated write_origin ContextVar; auto-deny approval callback; stdout/stderr capture into `ForkResult`; structured actions extraction; distinct provider client.
- `test_auxiliary_client.py` — `build_auxiliary_client(parent)` returns a Provider with a distinct httpx client; closes cleanly on fork exit.

## Out of scope for T1-04

- Slash-command behavior (`athena/commands/*`) — separate `tests/commands/` phase.
- Provider internals — those have `tests/providers/` already.
- Plugin lifecycle — `tests/plugins/` exists.
- MCP transport — `tests/mcp/` exists.

## Coverage target

≥60% on `athena/agent/`. Current baseline before T1-04 lands: not measured per-module (the global `coverage.yml` gate is 60%, current global is 75%).

The integration test `tests/test_fork_full.py` already exercises significant fork-path coverage; the new unit tests in `tests/agent/test_fork.py` should drive that to a clean 60+% by targeting the branches `test_fork_full.py` misses (interrupt, error, structured-actions extraction, write_origin ContextVar).
