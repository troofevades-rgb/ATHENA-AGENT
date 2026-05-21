# External coding-CLI delegation

Athena can hand a **scoped** coding task to another agentic CLI
(Codex, Aider, or any other CLI that exposes a non-interactive
exec mode), run it in an isolated git worktree, and surface the
resulting diff for review. **Never auto-merges.** The delegate's
output is treated as untrusted code until a reviewer (you, or
athena under your supervision) decides to land it.

## Why use it

Different agentic CLIs have different strengths. Rather than
compete with them, athena orchestrates them: hand off a
self-contained sub-task, get a reviewable diff back, keep athena
as the coordinator. Same "athena as broker" posture as T5-05's
capability routing — applied to peer agents instead of model
backends.

## Two integration shapes

| Shape | Used for | How |
|---|---|---|
| **Subprocess** (default) | Most CLIs | `delegate_to_cli` invokes the external CLI's non-interactive exec mode in an isolated worktree, captures stdout + diff |
| **Reverse-proxy** (optional) | OpenAI-compat CLIs where you want visibility into the delegate's reasoning, not just its diff | Point the external CLI at athena's proxy (T3-01) — athena brokers + logs every model call the delegate makes |

The subprocess shape is the primary deliverable. The
reverse-proxy shape is a documented alternative for cases where
you want to see (and audit) the delegate's intermediate calls.

## The tool surface

```text
delegate_to_cli(
    task: str,            # self-contained, with acceptance criteria
    repo_path: str,       # absolute path to the git repo
    base_ref: str = "HEAD",   # diff base + worktree branch source
    timeout_s: int = cfg.cli_delegate_timeout_s,
) -> JSON
```

JSON payload returned to the model:

```json
{
  "status": "done | timeout | error | rejected",
  "branch": "delegate/<uuid12>",
  "worktree": "/abs/path/to/delegate-<uuid12>",
  "diff": "diff --git a/x b/x\n+...",
  "exit_code": 0,
  "stdout": "delegate's stdout",
  "stderr": "delegate's stderr",
  "sandboxed": true,
  "next_step": "review the diff; `git merge <branch>` to land, ... to discard"
}
```

## The hard invariants

1. **Scope required.** An empty / whitespace task is rejected
   before any git op fires. The scope is the safety mechanism —
   "improve the codebase" is a runaway risk; "add `--json` to the
   `export` command, with a test" is reviewable and bounded.
2. **Isolated worktree.** `prepare_worktree` mints a fresh
   `delegate/<uuid12>` branch + a worktree outside the main
   checkout. Git's own worktree machinery enforces "no overlapping
   paths" — the delegate physically cannot write to the user's
   tree.
3. **Never auto-merges.** The diff is captured + surfaced; merging
   is a separate, explicit step the reviewer takes. Pinned by a
   test that asserts no `merge` / `push` / `commit` / `rebase` /
   `checkout` / `reset` git op fires anywhere in the delegation
   path.
4. **Sandboxed when configured.** With `cli_delegate_sandbox=True`
   (default), the whole delegate invocation goes through the T5-02
   bwrap sandbox runner — read-only system root, writable
   worktree only, no network by default. Defense-in-depth on top
   of any sandboxing the delegate may already do internally.
5. **Timeout-bounded.** Overrun → `status=timeout`,
   `exit_code=124`. The delegate is killed; the worktree is left
   in place so its partial work is recoverable.
6. **Target specifics isolated.** Vendor-specific command flags
   live in `cli_delegate_command` (config) + `DelegateAdapter`
   (one module). Swapping target CLIs is a one-file edit.

## Configuration

```toml
# Enable the feature. Default false (opt-in).
cli_delegate_enabled = true

# Invocation template — vendor-specific. {task} is the
# placeholder. Tokenisation happens via shlex BEFORE
# substitution, so a task containing spaces / quotes / shell
# metacharacters stays one argv element.
#
# Examples:
#   "codex exec --quiet {task}"
#   "aider --message {task} --yes"
#   "some-cli run -n {task}"
cli_delegate_command = "codex exec --quiet {task}"

# Wall-clock timeout in seconds for the delegate process.
cli_delegate_timeout_s = 600.0

# Where to put the worktree dir. None → tempfile.gettempdir().
# A dedicated dir is convenient for housekeeping ("clean every
# delegate-<uuid> under this root").
cli_delegate_worktree_root = "/var/tmp/athena-delegates"

# Wrap the delegate invocation in the T5-02 bwrap sandbox.
# Default true; turn off only if your delegate genuinely needs
# network or system access the sandbox blocks.
cli_delegate_sandbox = true
```

## Treating the delegate as untrusted

The delegate is another agent generating code. Same trust model
as any other code from outside your team: read it before you
land it.

The guardrails:

- **Worktree isolation** — the delegate physically cannot touch
  the user's checkout.
- **Diff review** — what the delegate produced is surfaced as a
  diff, not applied.
- **No auto-merge** — landing the change requires a deliberate
  `git merge` from the reviewer.
- **Sandboxed execution** — when the delegate runs code (tests,
  builds) as part of its work, that execution happens inside the
  T5-02 sandbox.

These compose: even if the delegate emits malicious code, it
lands in a branch outside your tree, you see exactly what
changed before merging, and any code it ran while building the
diff ran without filesystem-or-network escape from the worktree.

## Subprocess vs reverse-proxy — when to use which

**Subprocess (the default).** Simple, isolated, and the delegate
is fully responsible for its own model calls. Use this when:

- You trust the delegate's own model + credentials handling.
- You only need the *output* (the diff), not visibility into the
  reasoning.
- The delegate isn't OpenAI-compatible OR you don't want to
  proxy.

**Reverse-proxy via T3-01.** Point the external CLI's
`OPENAI_BASE_URL` (or equivalent) at athena's proxy:

```bash
# In the shell where the delegate runs:
export OPENAI_BASE_URL="http://localhost:8765/v1"   # athena proxy
export OPENAI_API_KEY="<your-athena-side-key>"
```

The delegate now talks to athena's proxy, which:

- Brokers the actual model call via athena's `resolve_provider`
  (capability-routed; T3-01).
- Logs every request (T3-01's proxy traffic JSONL appender).
- Lets you fail-over between providers without the delegate
  knowing.

This is the visibility option — pick it when "I want to see what
the delegate is *thinking* about doing, not just what it
produced." It costs extra latency (one more hop) and adds athena
into the model-call hot path, so the default is subprocess +
post-hoc diff review.

The reverse-proxy shape doesn't change anything about
`delegate_to_cli` — the tool still runs the CLI in an isolated
worktree, still captures the diff, still requires the reviewer
to merge. The proxy just sits inside the delegate's model-call
path, transparently to the rest of the delegation flow.

## Reviewing the diff

After a successful delegation:

```text
status: done
branch: delegate/9a4f2c1b6d8e
worktree: /var/tmp/athena-delegates/delegate-9a4f2c1b6d8e
diff: <the full diff>
next_step: review the diff; `git merge delegate/9a4f2c1b6d8e` to land,
           `git worktree remove ... && git branch -D ...` to discard.
```

Two paths from here:

```bash
# Land the change.
git merge delegate/9a4f2c1b6d8e
git worktree remove --force /var/tmp/athena-delegates/delegate-9a4f2c1b6d8e
git branch -D delegate/9a4f2c1b6d8e

# OR — discard it entirely.
git worktree remove --force /var/tmp/athena-delegates/delegate-9a4f2c1b6d8e
git branch -D delegate/9a4f2c1b6d8e
```

Athena never picks for you. The merge step is deliberate; the
discard is symmetric.

## What this does not do

- **Doesn't apply the diff for you.** That's the entire point.
- **Doesn't pick a target CLI.** You configure
  `cli_delegate_command`; athena invokes it.
- **Doesn't try to handle multi-step delegations.** Each tool
  call is one scoped task → one worktree → one diff. If the
  delegate needs follow-up work, that's a new `delegate_to_cli`
  call against the merged branch.
- **Doesn't merge across delegations.** Each delegation gets its
  own branch off `base_ref`. Combining multiple delegates'
  outputs is up to the reviewer.

## Smoke

(With a target CLI installed + `cli_delegate_command` configured.)

```bash
athena                            # interactive
> delegate to the CLI: "add a --json flag to the export command,
                        with a test that asserts JSON parses."
  # → worktree delegate/<id>, status=done, diff returned
  # → next_step shows the merge / discard commands
# Review the diff.
# If good:
git merge delegate/<id>
# Otherwise:
git worktree remove --force /var/tmp/athena-delegates/delegate-<id>
git branch -D delegate/<id>
```

When no delegate is configured:

```bash
athena
> delegate to the CLI: anything
  # → status=rejected, reason: cli_delegate_enabled is False
  # → primary model gets a structured "not configured" payload
  # → primary reasons "no delegate; doing it myself" and continues
```

## Related

- [Verified execution](verified-execution.md) — what athena
  itself uses for its own writes; the same diff-then-review
  pattern at a different scope (per-write, not per-task)
- [Sandbox](sandbox.md) — the bwrap wrap the delegate runs under
  when `cli_delegate_sandbox=true`
- [Proxy](../proxy.md) — the reverse-proxy mechanism
