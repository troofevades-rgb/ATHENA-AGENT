# `/goal` — passive invariant + autonomous continuation loop

Athena's `/goal` has two layers:

1. **Passive invariant** — a single objective kept at the end of
   the system prompt across every turn. Shapes decisions without
   driving them. (Phase 6.)
2. **Active continuation loop** — after each real assistant turn,
   if a goal is active and the safety caps haven't fired, athena
   injects a synthetic "keep going" turn so the agent advances
   without the user prompting each step. (T5-07.)

The passive invariant is still there — the loop is additive. You
get the same "keep this in mind" effect on every prompt, plus
the option of "actually finish this thing yourself."

## Subcommands

```text
/goal <text>      set / replace the goal (status=active, turns=0)
/goal             show goal text, status, turn count, subgoals
/goal status      alias of bare /goal
/goal pause       stop the continuation loop (status=paused)
/goal resume      restart the loop; if was exhausted, grant
                  another cfg.goal_max_turns on top of turns_taken
/goal clear       remove goal.txt + goal_state.json

/subgoal           show ordered subgoals (✓ / •)
/subgoal <text>    append a pending subgoal
/subgoal done      mark the FIRST not-done subgoal complete
```

Subgoals are **advisory** — ordered breadcrumbs the model can use
to sequence work. The continuation loop doesn't gate on them; it
only stops on sentinels or caps. They render into the goal block
so the model knows the breakdown you have in mind.

## The sentinel contract

Achievement is the **model's** call, verified by a deterministic
sentinel:

```text
GOAL ACHIEVED
```

on its own line ends the loop with `status=achieved`. The agent
announces "Goal achieved in N turn(s)."

When the agent is blocked and needs you:

```text
GOAL BLOCKED: <reason>
```

ends the loop with `status=paused` and surfaces the reason. Use
`/goal resume` once you've unblocked things.

The sentinels are case-insensitive, anchored to a line start, and
tolerant of markdown lead-ins (`#`, `>`, `*`, `-`, `•`) so the
model's natural formatting doesn't break the contract. They're
documented in the goal block injected into the system prompt, AND
reinforced in the continuation nudge every turn — the model sees
the contract twice per cycle.

## The safety caps

The runaway risk is the whole reason for the caps. Caps are
mandatory; there is no unbounded mode.

| Cap                    | Default       | Behaviour                                  |
|------------------------|---------------|--------------------------------------------|
| `goal_max_turns`       | 25            | `turns_taken >= max_turns` → `exhausted`   |
| `goal_max_tokens`      | 200_000       | tokens used since loop start > cap → `exhausted` |

Setting `goal_max_tokens = 0` disables the token cap (turn cap
still applies). Setting `goal_loop_enabled = false` disables the
active driver entirely — the passive invariant stays.

`/goal resume` after exhaustion bumps `max_turns` by
`cfg.goal_max_turns` without resetting `turns_taken` — the
status reads `30/50`, `55/75`, etc. The total work stays
visible. (Resetting to 0 would hide runaway.)

## Interrupts always win

Three interrupt paths, all of which pause the goal:

1. **Ctrl+C during streaming** — the in-flight turn is cut; the
   continuation hook sees `_last_turn_interrupted = True` and
   pauses (even when the cut-off text contained a `GOAL ACHIEVED`
   line that would normally win). The interrupted turn does not
   count toward `turns_taken`.
2. **Ctrl+C during tool execution** — same behaviour. The agent
   honours the user's intent to stop.
3. **A real user message** — drained at the top of every turn
   before any synthetic continuation, so a queued user input
   beats the loop to the next turn. Combine with `/steer` to
   redirect the current work without clearing the goal.

`/goal pause` is the explicit version — the user-initiated stop
that doesn't require an interrupt.

## Configuration

```toml
# Enable / disable the active driver. Default true.
goal_loop_enabled = true

# Turn cap. Hitting this exhausts the goal.
goal_max_turns = 25

# Token cap. Tokens used SINCE THE LOOP STARTED (not session
# total). 0 disables the token cap.
goal_max_tokens = 200000

# Override the per-turn continuation nudge. None → built-in
# default that reinforces the sentinel contract.
# goal_continuation_prompt = "..."
```

## State on disk

Two files per profile in `<profile_dir>/`:

| File                | Owner          | Contents                            |
|---------------------|----------------|-------------------------------------|
| `goal.txt`          | human-editable | the objective text (one line)       |
| `goal_state.json`   | machine-managed| status / turns / max_turns / subgoals / timestamps |

Both can be deleted independently. State survives restart —
mid-loop a session crash, athena re-reads both files at next
start and `/goal status` shows the same status / turn count /
subgoals. `/goal resume` continues; it doesn't restart.

A malformed `goal_state.json` falls through to default-active
(rather than blocking startup), and unknown status values get
normalised to `active` — forward-compat for future status
additions.

## Gateway parity

The continuation loop runs inside `Agent.run_turn`. The gateway
(`athena/gateway/agent_pool.py`) calls `await agent.run_turn(text)`
on each incoming message, so gateway runs get the **same** caps,
the **same** sentinel contract, and the **same** interrupt
semantics with **no extra wiring**. This matters most on the
gateway path where there's no human present — the caps are the
backstop.

## Pairs with T5-04 verified-execution

When the verified-execution loop (T5-04) is wired in (it is by
default — see [verified-execution.md](verified-execution.md)),
each continuation turn that writes code is verified
(diagnose → optional sandboxed run → rollback offer on failure)
**before** the next continuation fires. The verification report
appears in the tool result the model sees, so the agent's next
continuation factors in "did my last write introduce a new
error?". That's the "pursues a goal AND doesn't leave the
codebase broken" combination.

If T5-04 is off (`verify_on_write = "off"`), the continuation
loop still works — it just doesn't auto-verify.

## What the loop does not do

- **Doesn't decide achievement on its own.** Only the model's
  `GOAL ACHIEVED` sentinel stops the loop with `status=achieved`.
  No silent self-congratulation.
- **Doesn't enforce subgoal ordering.** Subgoals are advisory.
  The model can address them in any order; `/subgoal done` only
  flips the first not-done one.
- **Doesn't override interrupts.** Ctrl+C / pending user messages
  / `/steer` always win.
- **Doesn't unlock you in a loop.** A real user message processed
  in the REPL between turns lands before the next synthetic
  injection — the loop never holds the input prompt hostage.

## Smoke

```bash
athena
> /goal create a fizzbuzz module and a passing test for it
  # continuation turns fire automatically; agent ends with
  # GOAL ACHIEVED → loop stops
> /goal status
  # shows turns N/25, no subgoals

> /goal something open-ended that won't finish
  # ... let it hit the cap → "goal not completed after 25 turn(s)"
> /goal resume
  # bump cap to 50; loop continues

> (Ctrl+C mid-loop)
  # status flips to paused
> /goal resume
  # back to active

> /goal clear
  # both files removed
```

## Related

- [Verified execution](verified-execution.md) — the per-write
  safety layer that pairs with the per-turn goal loop
- [Steer](steer.md) — redirecting current work without clearing
  the goal
