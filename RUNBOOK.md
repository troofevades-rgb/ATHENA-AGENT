# Athena RUNBOOK

End-to-end test plan for athena's interactive surface. The unit suite
(`pytest tests/`) covers code; this runbook covers behaviour you can
only see by running the binary against a real model.

Three tiers, increasing in scope:

- **Tier 1 — Smoke pass** (~15 min): one-shot checks that every fix
  from the recent scaffolding work behaves as documented.
- **Tier 2 — Integration scenarios** (~45 min): multi-feature
  workflows that catch composition bugs.
- **Tier 3 — Failure-mode probes** (~30 min): break things on
  purpose and verify graceful degradation.

Run Tier 1 before every release. Tier 2 quarterly or after significant
agent-loop / goal-loop changes. Tier 3 when paranoid.

---

## Preflight

```
cd C:\Users\mtt_j\projects\ocodev2
pip install -e .
pytest tests/ -q
```

The unit suite **must** be green before starting interactive tests.
If a Tier-1 check fails but unit tests pass, that's a real find —
file it.

In a fresh shell, start athena from the project root:

```
athena
```

Confirm the startup banner shows:

- `loaded ATHENA.md (NN bytes)` — `NN > 20000` after recent edits
- `loaded skills catalog (NN bytes)` — non-zero
- `model troofevades-q35:athena` or whatever you're testing with
- `cwd  C:\Users\mtt_j\projects\ocodev2`

---

## Tier 1 — Smoke pass

Each row is one paste at the athena prompt and one visual check.
Hit `Enter` between rows. Take a fresh session between major sections.

### 1.1 Path handling

| # | Action | Expected |
|---|---|---|
| 1.1.1 | Type `/cwd` | Prints `C:\Users\mtt_j\projects\ocodev2` |
| 1.1.2 | Ask: "what does workspace_info return?" | Model calls `workspace_info`; result JSON has `workspace`, `python_cwd`, `workspace_matches_cwd`, `profile_dir`, `memory_dir` |
| 1.1.3 | Ask: "read /c/Users/mtt_j/.athena/config.toml" | Read succeeds (MSYS path normalization on Windows) |
| 1.1.4 | Ask: "run `pwd` via Bash" | Returns the workspace as `/c/Users/mtt_j/projects/ocodev2` (Git Bash) |
| 1.1.5 | From workspace `C:\Users\mtt_j`, ask the model to Grep something | Succeeds; skips the Cyrillic-named `apiskadlo-repos` subdir silently |

**FAIL if:** any path-mangling error like `C:\c\Users\mtt_j\…` appears.

### 1.2 Thrash detection

| # | Action | Expected |
|---|---|---|
| 1.2.1 | Ask the model to `Read` the same file 3 times | 3rd call returns `THRASH WARNING` with prior result preview |
| 1.2.2 | Ask Read on `/c/Users/x.txt`, then `C:\Users\x.txt`, then `~/x.txt` (paths resolving to same file) | 3rd call trips thrash — path-aware hashing collapses spellings |
| 1.2.3 | After Q1.2.1 fires, ask a different question | Model receives normal tool results; buffer doesn't false-alarm |

### 1.3 Skill verify gate

| # | Action | Expected |
|---|---|---|
| 1.3.1 | Tell model: `skill_manage create name="test-bad" frontmatter={"description":"x"} body="```python\nsuccessful =\n```"` | Refused with `SyntaxError` message naming the broken block |
| 1.3.2 | Same but with valid Python body | Skill created |
| 1.3.3 | Create with no Python (prose only) | Created; verifier skips when no code fences |

Cleanup: `skill_manage delete test-bad` if created.

### 1.4 Goal quality gate

| # | Action | Expected |
|---|---|---|
| 1.4.1 | `/goal be the best CLI agent ever` | Refused with "ambition" message; no model turn |
| 1.4.2 | `/goal ship it` | Refused with "too short" message |
| 1.4.3 | `/goal Write a hello.py file printing Hello World` | Accepted; bootstrap fires a model turn immediately |
| 1.4.4 | `/goal status` | Shows active state with the goal text |
| 1.4.5 | `/goal clear` | State wiped |

### 1.5 Goal continuation prompt

After running 1.4.3:

```
ls -t ~/.athena/profiles/default/sessions/*.jsonl | head -1 | xargs tail -3
```

The most recent `"role": "user"` entry's `content` should contain:

- `Goal: Write a hello.py file...`
- `Progress: turn 0/10000`
- `No subgoals declared yet` OR `Next subgoal: ...`
- The sentinel reminder (`GOAL ACHIEVED`)

**FAIL if:** any field missing.

### 1.6 Goal verifier (rejection)

Add to `~/.athena/config.toml` (above any `[section]` header):

```toml
goal_verifier_command = "python -c \"import sys; sys.exit(1)\""
goal_verifier_timeout_s = 30.0
```

Restart athena, then:

```
/goal Print the word 'hello' to a file at hello.txt in the current directory
```

| # | Expected |
|---|---|
| 1.6.1 | Model writes the file |
| 1.6.2 | Model emits `GOAL ACHIEVED` |
| 1.6.3 | UI shows yellow `[goal] verifier rejected GOAL ACHIEVED (turn N/10000):` line |
| 1.6.4 | Next synthetic user message contains `GOAL ACHIEVED was rejected by the verifier` |
| 1.6.5 | Goal status stays `active` until cap reached |

Cleanup: remove or comment the two verifier lines. `/goal clear`. Delete `hello.txt`.

### 1.7 Local-provider cap bypass

| # | Action | Expected |
|---|---|---|
| 1.7.1 | `/goal write a one-line python file at test.py` | `status=active, max_turns=10000` (bumped from 25 for ollama) |
| 1.7.2 | Verify saved state: `cat ~/.athena/profiles/default/goal_state.json` | `"max_turns": 10000` |

### 1.8 Board

| # | Action | Expected |
|---|---|---|
| 1.8.1 | Ask model to `TaskCreate` 3 tasks | Tasks visible in `/board` |
| 1.8.2 | `/board` | Shows todo/doing/blocked/done columns |
| 1.8.3 | `/board clear` | All live tasks wiped; print confirms count |
| 1.8.4 | `/board` after clear | Empty board hint shown |

### 1.9 /video

| # | Action | Expected |
|---|---|---|
| 1.9.1 | `/video` | Lists `stub_video_local` and `xai_video`; xai shows `auth ok (via ATHENA_XAI_API_KEY)` |
| 1.9.2 | `/video set xai_video` | Confirmation line, no error |
| 1.9.3 | Ask "generate a 5-second video of an owl" | Model calls `video_generate`; result JSON shows `"backend": "xai_video"`, `request_id`, eventually `path` to `.mp4` |
| 1.9.4 | `/video clear` then ask again | Routes to broker's default (likely stub) |

### 1.10 Tool-call discipline (Modelfile)

| # | Action | Expected |
|---|---|---|
| 1.10.1 | Cold session, ask "generate me a video of X" | Model calls `video_generate` — does NOT refuse with "video is disabled" or similar pre-check |
| 1.10.2 | Cold session, ask "search X for posts from someone" | Model calls `search_x` — does NOT refuse asking for API setup first |

### 1.11 OS-aware prompt + achievement-message labels

| # | Action | Expected |
|---|---|---|
| 1.11.1 | `/dump` and search for "Tool preference" | Present, mentions Windows / Git Bash |
| 1.11.2 | Run a goal to completion with NO verifier configured | Stop line ends `(self-declared; no verifier configured ...)` |
| 1.11.3 | Run a goal to completion WITH verifier exit-0 | Stop line ends `(verifier passed)` |

---

## Tier 2 — Integration scenarios

### Scenario A — Verifier-gated video creation

**Setup**: write a verifier that checks an MP4 was created:

```toml
goal_verifier_command = "python -c \"import os,sys; sys.exit(0 if any(f.endswith('.mp4') for f in os.listdir(os.path.expanduser('~/.athena/profiles/default/videos'))) else 1)\""
goal_verifier_timeout_s = 60.0
```

Restart athena.

**Goal**:
```
/goal Generate a 5-second cyberpunk video and write a one-sentence caption to caption.txt
```

**Pass criteria**:
- Model decomposes into subgoals (calls `/subgoal` 2-3×) OR proceeds directly
- `video_generate` called against `xai_video` backend
- Real `.mp4` appears in `<profile>/videos/`
- `caption.txt` exists in workspace
- `GOAL ACHIEVED` emitted, verifier accepts, status flips to `achieved`
- Stop line shows `(verifier passed)`

**Fail modes to recognise**:
- Model refuses → Modelfile / tool-call-discipline regression
- Video gen fails with HTTP error → check xAI key validity, check tier supports video
- Verifier rejects despite file present → path mismatch in verifier command

### Scenario B — Pause/resume across restart

1. `/goal Implement a Python script that prints Fibonacci numbers up to 100`
2. Let it run 3-4 turns
3. `/goal pause`
4. `/exit`
5. Restart athena
6. `/goal status` — should show `paused`, turn count preserved
7. `/goal resume` — fires continuation turn immediately
8. Model picks up state (you'll see the goal text in the next user message)

**Pass criteria**: turns_taken preserved across restart; resume fires bootstrap; model has goal context.

### Scenario C — Backend hot-swap

1. `/video set stub_video_local`
2. Ask for a video → result has `"backend": "stub_video_local"`, placeholder `.mp4`
3. Without restart: `/video set xai_video`
4. Ask for a video → result has `"backend": "xai_video"`, real `.mp4`

**Pass criteria**: live cfg fix means no restart needed between switches.

### Scenario D — Vague→concrete via gate

1. `/goal be the best agent in the world` → refused
2. `/goal Add a CHANGELOG entry documenting the goal-loop improvements` → accepted
3. Model decomposes, writes the entry, emits `GOAL ACHIEVED`
4. Open CHANGELOG.md, verify the entry exists at top

**Pass criteria**: gate refuses the first; second runs end-to-end.

---

## Tier 3 — Failure-mode probes

Each probe deliberately breaks something and verifies graceful behaviour.

### 3.1 Missing xAI key

```
# Comment out in ~/.athena/.env:
# ATHENA_XAI_API_KEY=xai-...
```

Restart. `/video` shows `no credential found`. `/video set xai_video` succeeds but `video_generate` returns `status: error` with "no API key" — clear actionable message, no crash.

### 3.2 Bad xAI key

Set the key to `xai-WRONG`. `video_generate` returns `XAIAPIError` with HTTP 401/403 in result. Loop keeps going, doesn't crash.

### 3.3 xAI timeout

Set in config:
```toml
goal_verifier_timeout_s = 1
goal_verifier_command = "python -c \"import time; time.sleep(30)\""
```

Run a goal to completion. Verifier times out; rejection prompt mentions "timed out after 1.0s".

### 3.4 Network down

Mid-poll (during a video generation), disable WiFi or block `api.x.ai` in your hosts file. The poll's `last_poll_error` gets stashed in the JobHandle; loop continues polling; doesn't crash. Re-enable network — next poll resumes.

### 3.5 Stale TOML section (regression)

Move `video_generation_enabled = true` BELOW `[gateway.platforms.discord]`. Restart. `video_generate` returns `status: not_enabled`. Move it back above. Restart. Works again. (Documents the gotcha that bit us twice.)

### 3.6 Empty / whitespace goal

`/goal "   "` — refused. `/goal ""` — show path. Neither crashes.

### 3.7 Workspace not writable

```
chmod -w some_dir
/cwd some_dir
```

Tools that try to Write get `PathSecurityDenied`. No silent corruption. Restore: `chmod +w some_dir`.

### 3.8 Cyrillic / mangled filename in workspace

Make sure `C:\Users\mtt_j\apiskadlo-repos\NGU_Sex_Trafficking_Data\...` still exists (it has a Cyrillic dir we hit during testing). From workspace=`C:\Users\mtt_j`, `Grep` for anything → succeeds; the bad dir is silently skipped by `_safe_walk`.

---

## What this runbook does NOT cover

Things that need infra beyond interactive testing — flagged so we don't pretend they're covered:

- **Race conditions** — concurrent /steer + synthetic continuation, two agents writing the same file. Needs threading harness.
- **Memory leaks** — long-running sessions with thrash buffer, plugin reload cycles. Needs memory profiling.
- **Performance regressions** — tool dispatch latency, system prompt build time, fork startup. Needs benchmark suite.
- **Plugin compatibility** — third-party plugins with broken manifests. Needs plugin fixture set.
- **Gateway adapters end-to-end** — Discord/Slack/Telegram message delivery. Needs adapter test doubles.
- **MCP server interop** — stdio + HTTP/SSE flows under various server failures. Needs MCP fixture servers.

These are real gaps. Filing a `RUNBOOK-INFRA-TODO.md` for them is the next ratchet.

---

## After a test run

If a check fails:

1. **Capture the unexpected output** — paste/save the failure text.
2. **Confirm reproducibility** — fresh shell, fresh athena restart, retry.
3. **Bisect if regression** — `git log` the suspect subsystem, find the change.
4. **File or fix** — broken tests block release; broken docs are merge-blocking too.

If all checks pass:

1. Note the model + commit SHA you tested against.
2. Update the "Last tested" line at the top of this file (next section).

---

## Last tested

(Update on each pass.)

- Date: 2026-05-22
- Commit: HEAD (post-runbook-write fixes + rich markup escape fix)
- Model: troofevades-q35:athena (Ollama, local)
- Tier 1: **PASSED — ALL 20 CHECKS**, including §1.6 verifier
  rejection and §1.11.3 verifier-passed label. Real xAI video
  generation worked end-to-end at §1.9.3 (4-second clip generated
  in 42.6s, hashed, written to `<profile>/videos/`).

  Bugs surfaced and fixed during the pass:
  - Docstring `\U` SyntaxError in `test_path_security.py` (raw-string fix)
  - 13 unit-test regressions from scaffolding changes (all fixed)
  - `/board` and `/help` missing new commands (registration gap +
    regression test added at `tests/commands/test_registration.py`)
  - `rich.errors.MarkupError` killed the session when a tool result
    contained literal ``[/]`` or similar bracket markup. Fixed in
    `athena/ui.py:tool_result` by escaping tool output via
    `rich.markup.escape` before passing to ``Panel``.
- Tier 2:
  - Scenario A (verifier-gated video) — **PASSED** 2026-05-22 against
    troofevades-q35:athena + xAI Grok Imagine. 11 subsystems composed
    cleanly in 3m20s wall (58s of which was xAI render). Caption.txt
    written, MP4 fetched, verifier passed.
  - Scenario B (pause/resume across restart) — _not yet run_
  - Scenario C (backend hot-swap) — _not yet run_
  - Scenario D (vague → concrete via gate) — _not yet run_
- Tier 3: _not yet run_

---

## Maintenance

- New feature → add a Tier 1 row.
- New scaffolding fix → add a Tier 3 probe documenting how to break it.
- Removed feature → delete the row (don't leave dead checks).
- Real bug found during a run → file the bug, add a regression row that
  catches it next time.

A runbook that doesn't reflect current reality is worse than no runbook —
it lies about what's tested.
