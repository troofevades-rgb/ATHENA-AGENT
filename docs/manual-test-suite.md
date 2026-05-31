# Manual Test Suite

User-driven test suite for hunting bugs across the full athena surface.
14 independent phases — work through linearly or pick the phase that maps to a
subsystem you've recently changed. Paste back any unexpected behavior with the
command that surfaced it.

PowerShell syntax throughout (the project's primary development shell). Bash
equivalents differ only in env-var syntax (`$env:X` → `X=...`) and path
separators.

---

## Phase 0 — Setup

```powershell
$env:ATHENA_BOOT_TRACE = "1"   # keep the silent-exit trap armed
cd C:\Users\dev\projects\ocodev2
git status                      # baseline; should be clean
athena doctor                   # baseline green
```

---

## Phase 1 — Subcommands (one-shot, no REPL)

```powershell
athena --version                          # version prints; exit 0
athena --help                             # full --help
athena doctor --json | ConvertFrom-Json   # parses cleanly
athena doctor --strict                    # FAIL → 1, WARN → 1
athena status                             # snapshot of latest session
athena profiles list                      # at least "default"
athena memory list                        # lists global memory files
athena model list                         # available + pulled models
athena mcp list                           # configured MCP servers
athena reindex --help                     # reindex subcommand help
athena -bogus-flag                        # → "did you mean --bogus"?
athena bogus-subcommand                   # unknown verb error
```

**Hunts:** subcommand routing, JSON envelope shape, --help completeness,
single-dash typo rewriter, argparse error messages.

---

## Phase 2 — Headless one-shot

```powershell
athena -p ""                              # empty → status=invalid, exit 2
athena -p "say hi"                        # exit 0, model replies
athena -p "say hi" --json                 # one JSON line on stdout
athena --task does-not-exist.txt          # exit 2 + clear message
"What is 2+2?" | Out-File task.txt -Encoding utf8
athena --task task.txt                    # reads file, runs
athena -p "say hi" --timeout 1            # → status=timeout, exit 124
athena -p "say hi" --run-id my-test-001   # echoed in --json envelope
athena -p "what is 17*23"                 # tool calls Bash or math, completes
athena -p "say hi" -C C:\does\not\exist   # exit 2, workspace error
```

**Hunts:** headless `run_headless` wrappers, timeout cancellation, --task file
IO, JSON envelope correctness, run-id echo.

---

## Phase 3 — Interactive REPL launch + exit

```powershell
athena         # TUI launches, banner renders, prompt shows ▸▸
# Type: /quit         → exits cleanly
athena         # again
# Press: Ctrl+C       → exits cleanly, no orphan threads
athena         # again
# Press: Ctrl+D       → exits cleanly
```

After each exit:

```powershell
echo $LASTEXITCODE
Get-Process | Where-Object {$_.ProcessName -like "*athena*" -or $_.ProcessName -like "*node*"} | Select-Object ProcessName, Id
```

**Hunts:** clean exit, orphaned Node TUI subprocesses, MCP server subprocess
leaks, exit code correctness, the silent-exit-2 bug we're trapping with
`boot_trace`.

---

## Phase 4 — Slash commands (one big interactive session)

Launch `athena`, then in order:

```
/help                                    → SLASH_HELP renders
/status                                  → snapshot renders
/cost                                    → token counters
/model                                   → picker renders, multi-provider list
/model 1                                 → picker index switch
/model anthropic/claude-opus-4-7         → cross-provider switch + warn if temp deprecated
/model athropic/claude-opus-4-7          → typo guard fires
/model bogus/no-such                     → resolve fails cleanly
/model qwen2.5-coder:14b                 → back to local Ollama
/dump                                    → live system prompt renders, no truncation
/cwd                                     → missing-arg error
/cwd C:\Users\dev\projects             → rebuild, system prompt updates
/cwd Z:\nope                             → bad path error
/cwd C:\Users\dev\projects\ocodev2     → back
/cost                                    → counters updated
/clear                                   → history wiped, session continues
say hi                                   → model replies (turn works post-clear)
/queue                                   → empty queue
/steer "always be concise"               → queues
say what is 2+2                          → model sees the steer
/goal "list every .py file under athena/" → goal set
/goal                                    → status shows active
say start                                → goal loop fires; turn 1/N
/goal clear                              → cleared
/godmode                                 → status (only if you've opted in)
/mcp                                     → connected clients table
/mcp logs red-team-mcp                   → stderr tail (if configured)
/compact                                 → context compression test
say what's the time                      → turn works post-compact
/memory                                  → memory module entry
/skills                                  → skills catalog
/help bogus                              → /help with unknown arg
/blargh                                  → unknown command error
/quit
```

**Hunts:** every command surface, missing/bad arg handling, state mutations
(system-prompt rebuild, goal injection, steer drain), the compact→turn
interaction that surfaced the compressor crash.

---

## Phase 5 — Sessions: clear / resume / persistence

```powershell
athena -p "remember the magic word is BANANA"
# Note the session id from output
athena status                            # latest session listed
```

In a new interactive shell:

```
/resume                                  → picker of recent sessions
# pick the one above
say what was the magic word?             → should recall BANANA from history
/clear                                   → wipes
say what was the magic word?             → should NOT recall (history gone)
/quit
```

**Hunts:** JSONL ↔ SQLite mirror, resume picker, history rehydration, `/clear`
scope.

---

## Phase 6 — Tools: Read / Write / Edit / Bash / Grep / Glob

In interactive session:

```
read athena/__main__.py and tell me the first function defined
grep for "circuit_breaker" in athena/ and list every file
find every .py file modified in the last 24h
create a file at C:\temp\athena-probe.txt with content "hello world"
read C:\temp\athena-probe.txt back to me
edit C:\temp\athena-probe.txt — change "hello" to "goodbye"
delete C:\temp\athena-probe.txt
run dir on C:\temp                       → uses Bash on Windows? Or PowerShell wrapper?
run Get-Date in powershell               → triggers approval flow
```

For each: watch for delta-lint output, approval prompts on Bash, post-write
hook firing. Run with `--auto-approve` flag too:

```powershell
athena --auto-approve -p "create C:\temp\probe2.txt with content X, then read it back"
```

**Hunts:** tool dispatch, delta-lint, approval-callback ContextVar, parallel
tool batching, Bash subprocess on Windows.

---

## Phase 7 — Agent forks (sub-agents)

In interactive session:

```
use the Agent tool to read athena/agent/runtime.py and report back the first 5 imports
use the Agent tool twice in parallel: one to grep for "_fire_stop", one to grep for "_log_event"
```

While forks are running:

```powershell
# In another shell:
Get-ChildItem $env:USERPROFILE\.athena\logs\
Get-ChildItem $env:USERPROFILE\.athena\sessions\
```

**Hunts:** daemon-thread fork lifecycle, `AUTO_DENY` approval callback in
forks, KV-cache isolation, session-id per-fork.

---

## Phase 8 — Provider hopping (cost + token consistency)

```
/cost                                    → note current tokens
/model ollama/qwen2.5-coder:14b
say hi
/cost                                    → tokens incremented for Ollama
/model anthropic/claude-opus-4-7
say hi
/cost                                    → tokens incremented separately; cache stats appear
/model openrouter/nousresearch/hermes-4-405b
say hi
/cost                                    → openrouter usage appears
/model openrouter/no-tools/model         → if you can find one without tools, warn fires
/model qwen2.5-coder:14b
```

**Hunts:** provider rebuild on switch, prefix-strip correctness across
providers (the openrouter doubled-prefix bug class), Anthropic temperature
deprecation handling, OpenRouter tool-support warning.

---

## Phase 9 — Goal loop edge cases

```
/goal "echo the number 1, then echo 2, then say GOAL ACHIEVED"
say start
                                         → loop runs to "GOAL ACHIEVED" then stops
/goal                                    → status: achieved
/goal clear
/goal "echo the number 1, then echo 2 forever"
say start
                                         → should hit max_turns and exhaust
/goal clear
/goal "do something that requires an unreachable provider"
/model bogus/typo
say start                                → goal pauses on circuit_breaker
/goal                                    → paused
/goal clear
/model qwen2.5-coder:14b
```

**Hunts:** goal achievement sentinel, exhaustion, **the breaker-pause path**,
`/goal resume`, status persistence.

---

## Phase 10 — Steer queue

```
/steer "after every reply, count to 3"
say what's your favorite color
                                         → reply includes 1, 2, 3 somewhere
/queue                                   → drained
# Bigger steer pileup:
/steer "rule A"
/steer "rule B"
/steer "rule C"
/queue                                   → 3 queued
say next reply
                                         → all 3 drain before user prompt
```

**Hunts:** steer FIFO ordering, drain-before-prompt invariant, persistence
across turns.

---

## Phase 11 — Godmode (if opted in)

Requires `ATHENA_ALLOW_GODMODE=1` in env or `~/.athena/.env`.

```
/godmode                                 → status
/godmode steer "be unhinged"             → steer-queue variant
/godmode auto                            → autoscore against the active model
/godmode race "say something edgy"       → race across ULTRAPLINIAN_MODELS
/godmode prefill                         → prefill mode info
/godmode clear                           → reset
```

**Hunts:** godmode jailbreak system-prompt mutation, race orchestration across
providers, autoscore correctness, mode-aware clear.

---

## Phase 12 — Background curator

```powershell
Remove-Item env:ATHENA_DISABLE_BACKGROUND_CURATOR   # default = enabled
athena
```

Do 10+ turns of a real task. Then:

```powershell
Get-ChildItem $env:USERPROFILE\.athena\profiles\default\curator\
```

**Hunts:** curator fork race (the one we trapped earlier), REPORT.md emission,
7-day interval gating.

```powershell
$env:ATHENA_DISABLE_BACKGROUND_CURATOR = "1"
athena
# curator should skip
```

---

## Phase 13 — Edge / abuse / off-happy-path

```powershell
athena -p ""                             # empty → invalid
athena -p "   "                          # whitespace only → invalid
athena -p ("x" * 50000)                  # very long prompt → triggers compressor or rejects
athena -p "say hi`nover`nmultiple`nlines"  # newlines in prompt
athena -p "say 🦉 with emoji and Ünïcødé"  # non-ASCII
$env:OLLAMA_HOST = "http://localhost:99999"  # bogus
athena -p "say hi"                       # → exit 2 "cannot reach Ollama"
Remove-Item env:OLLAMA_HOST
```

In a long interactive session, deliberately:

```
type 50 prompts in a row to force token watermark and compression
ctrl+C mid-turn                          → interrupt path
/clear after interrupt
/resume after Ctrl+C exit                → does the half-finished turn replay?
```

**Hunts:** input validation, encoding, compressor boundary, interrupt
semantics, resume after dirty exit.

---

## Phase 14 — Crash recovery

```powershell
# Force a crash deliberately:
python -c "import sys; sys.path.insert(0, 'athena'); from crash_log import _athena_excepthook; import sys; raise ValueError('synthetic')" 2>&1 | Out-Null

Get-ChildItem $env:USERPROFILE\.athena\crashes\ | Sort-Object LastWriteTime -Descending | Select-Object -First 1
# Should show one new crash record

Get-Content $env:USERPROFILE\.athena\crashes\crash-*.json | Select-Object -First 1 | ConvertFrom-Json
# Schema renders; secrets scrubbed

# Confirm bounded rotation:
1..60 | ForEach-Object { python -c "raise SystemExit(99)" 2>&1 | Out-Null }
(Get-ChildItem $env:USERPROFILE\.athena\crashes\).Count
# Should be <= 50 (MAX_CRASH_RECORDS)
```

**Hunts:** crash log schema, secret scrub, rotation cap, doctor surface
integration.

---

## Phase 15 — Cleanup

```powershell
Remove-Item env:ATHENA_BOOT_TRACE
Get-Content $env:USERPROFILE\.athena\boot-trace.jsonl | Select-Object -Last 20   # any silent-exits?
Remove-Item $env:USERPROFILE\.athena\boot-trace.jsonl
```

If `boot-trace.jsonl` contains any sequence missing `atexit`, that's the
intermittent launch bug we're hunting — paste the trace.

---

## Reporting bugs surfaced by this suite

For each anomaly:

1. The exact command that surfaced it
2. Expected behavior (from this doc)
3. Actual behavior (output, exit code, screenshot if TUI)
4. `~/.athena/crashes/` newest entry if applicable
5. `~/.athena/boot-trace.jsonl` newest entries if applicable
6. `athena doctor --json` snapshot

Three bugs from this session's dogfood matched the pattern surfaced by Phase 4
(`/model athropic/...` typo) and Phase 9 (goal loop ignored circuit breaker)
plus an unrelated fatal in the compressor — all fixed in `6056381`.
