# Goal loop recon (T5-07.1)

Pre-T5-07 surface of `/goal`. Map of where the passive invariant
lives, the seams where the active loop attaches, and the
behaviours that must stay intact under the upgrade.

## The passive invariant today

| File | Role |
|------|------|
| `athena/goal/invariant.py` | `goal_path`, `get_goal`, `set_goal`, `clear_goal`, `format_for_system_prompt`. Stores `<profile_dir>/goal.txt` (newline-terminated, stripped). |
| `athena/commands/goal.py` | `/goal` dispatcher. Subcommands today: bare or `show` (display), `clear` (delete), anything else (set + persist). |
| `athena/agent/core.py` | `Agent._load_goal()` (defensive read), `Agent.reload_goal()` (re-read + rebuild system message in place), `self.goal` field. Threaded into `build_system_prompt(goal=self.goal, ...)`. |
| `athena/prompts/system.py` | Appends the rendered goal block at the end of the system prompt when `goal` is truthy. |

The text file is human-editable on disk. There is no separate
state file — no concept of status, turns, or subgoals today.

## Seams the active loop attaches to

1. **Per-turn completion seam.** `Agent._run_turn_inner` (in
   `athena/agent/core.py`) — at the point where `not tool_calls`
   evaluates true, the turn is over and the model's final
   assistant text is in `assistant_text`. That's the point to
   call `maybe_continue_goal_after_turn` (T5-07.5). The
   adjacent `self.plugin_hooks.on_assistant_message(...)` call
   shows the hook style already in use.

2. **System prompt rebuild.** `Agent._build_system()` already
   passes `self.goal` through to `build_system_prompt`. T5-07.4
   will pass the GoalState's subgoals + sentinel contract
   through the same path. `Agent.reload_goal()` rebuilds the
   system message in place — the same affordance carries over
   for state changes (status, subgoals).

3. **Slash dispatcher.** `athena/commands/goal.py` is a single
   `@command("goal")`-decorated function. T5-07.4 will branch
   on the first token for `pause` / `resume` / `clear` /
   `status` and surface the rest as the new goal text. A
   parallel `/subgoal` command will live next to it.

4. **Gateway path.** `athena/gateway/agent_pool.py:155` —
   `await agent.run_turn(text)`. Because the continuation hook
   runs *inside* `run_turn`, gateway parity is automatic;
   nothing in the gateway needs to call the hook itself. Caps
   matter here most (no human present).

## Interrupt surfaces that must keep winning

- `Ctrl+C` during streaming → `interrupted=True`, the
  `_run_turn_inner` loop appends a system-style marker and
  returns. The active loop must check the same `interrupted`
  signal and set `status=paused`.
- `Ctrl+C` during tool execution → handled at line ~874, similar
  pattern, also returns. Same pause behaviour required.
- `/steer` (in `athena/commands/steer.py`) — already redirects
  current work without clearing goal. T5-07 must leave that
  command's semantics unchanged; the active loop must not
  fire a synthetic turn while a `/steer` is pending or just
  processed.
- A pending real user message — the REPL processes user input
  via `run_turn(user_input)`. The continuation hook will enqueue
  a synthetic turn only when no real input is queued. (In
  practice for the CLI REPL: the synthetic turn fires
  immediately because the loop is single-threaded; the REPL's
  input prompt comes back AFTER the loop yields.)

## What must not change

1. `goal.txt` stays human-editable, same path, same format.
2. The passive injection (the goal block in the system prompt)
   stays — the active loop is additive.
3. `/goal <text>` to set, `/goal clear` to remove — the two
   primary surface forms — keep working unchanged.
4. `Agent.goal: str | None` keeps the existing meaning. The new
   `Agent.goal_state: GoalState | None` is a parallel field.

## Soft dependency on T5-04

When `_verify_after_write` lands an outcome on the assistant's
last write (T5-04 already wired in `athena/tools/file_ops.py`),
the verification report is appended to the tool result the
model sees. The continuation hook reads `assistant_text` AFTER
those results, so a verified continuation is naturally part of
the loop without extra wiring. The pairing is "agent pursues
a goal AND doesn't leave the codebase broken" — both halves
just compose.

## Configuration today

There is no goal config block. T5-07.3 will add:

```python
goal_loop_enabled: bool = True
goal_max_turns: int = 25
goal_max_tokens: int = 200_000  # generous but finite
goal_continuation_prompt: str | None = None  # override default
goal_achieved_sentinel: str = "GOAL ACHIEVED"
goal_blocked_sentinel: str = "GOAL BLOCKED"
```

## ACP / external surfaces touching `/goal`

- `athena/acp/slash_commands.py` lists `/goal` as a recognised
  ACP slash command (so an external editor can route a `/goal`
  command into the agent). T5-07 changes nothing about that
  dispatch — the new subcommands are positional args, so the
  ACP entry point still works without surface changes.
- `athena/commands/help_cmd.py` describes `/goal` in the in-app
  help; T5-07.4 should extend that line to mention the new
  subcommands.

## Loop seam pseudocode

```python
# Agent._run_turn_inner, where the model emits no further tool_calls:
if not tool_calls:
    if assistant_text:
        self.plugin_hooks.on_assistant_message(assistant_text)
    self._fire_stop("completed")
    self._maybe_fire_review()

    # T5-07: the continuation hook attaches here, AFTER plugin
    # observation and review (those see the real turn first).
    if self.goal_state is not None and not interrupted:
        decision = maybe_continue_goal_after_turn(
            profile_dir=self._profile_dir(),
            state=self.goal_state,
            last_assistant_text=assistant_text,
            cfg=self.cfg,
        )
        if decision.should_continue:
            # Synthetic continuation — loop inside run_turn rather
            # than re-entering, so /steer + pending user input
            # processed at the REPL layer get a chance to land
            # before the next synthetic injection.
            user_input = decision.synthetic_prompt
            continue  # re-enter the outer step loop
        # else: status set by the hook; print stop_reason to user
    return
```

Whether to inline a continuation (above) or re-enqueue at the
REPL layer is a design choice for T5-07.5. Inlining keeps the
loop driver-agnostic (REPL and gateway both benefit). Pending
real input is handled at the REPL layer's read step.
