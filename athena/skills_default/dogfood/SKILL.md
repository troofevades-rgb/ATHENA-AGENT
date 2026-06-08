---
description: Exploratory QA of your own product — find bugs your tests don't
name: dogfood
created_at: '2026-05-27T00:00:00Z'
last_activity_at: '2026-05-27T00:00:00Z'
pinned: false
state: active
use_count: 0
write_origin: foreground
---
# Dogfood

Disciplined exploratory QA of your own product. The premise:
automated tests verify what you THOUGHT to test. Dogfooding finds
the bugs you didn't know to test for because you weren't using the
product like a user would.

## When to use this skill

Use:
- Before a major release / version bump
- After significant UX changes
- Periodically as a heartbeat check (weekly / sprintly)
- When a user reports something weird and you want to verify the
  surrounding area

Skip for: pure backend changes with no user-visible surface,
infra-only changes.

## The dogfood session

Block 30-60 minutes. No background distractions. Approach the
product as if you were a user, NOT as if you were the developer
who knows where the bodies are buried.

### 1. Pick a goal

A real, end-to-end task a user might do. Examples for athena:

- "Set up athena from scratch on a new machine and run my first
  task"
- "Find and fix a specific bug in this codebase using athena"
- "Configure a custom skill and use it across two sessions"

The goal must be:
- Realistic — something a user would actually do
- End-to-end — not "test the login screen"; do the whole flow
- Time-bounded — should fit in 30-60 minutes

### 2. Execute the goal

Use the product like the user would. NOT like the developer would.

- Use the documented setup steps, not the dev shortcuts you know
- Click around, don't shortcut-key
- Read the UI text as if you didn't know what it meant
- When something confuses you, NOTE IT — that confusion is data

Keep a running log:

```
14:00 started fresh install
14:03 ran ``athena init`` — banner showed but the wordmark
       was clipped on the right at 100-col width
14:07 ``/skills`` shows 20 skills but no description column —
       have to /skill view <name> to know what each does
14:11 wanted to share a skill with a teammate — no docs on
       skill sharing; figured out manually
14:18 ran my first task — works but the tool-call output for
       file_ops scrolled past faster than I could read
```

Every line in the log is potential signal. Don't filter during
the session.

### 3. After the session: triage

For each note, decide:

- **Bug** — file an issue with repro steps
- **Friction** — file an issue tagged "UX/friction"; might not
  be a "bug" but is real
- **Doc gap** — note the missing doc; either fix or file
- **Design rethink** — note as an item to discuss with the team
- **Wonder** — questions you had ("does this work on Windows?")
  → file as a "verify" task
- **Won't fix** — note WHY, so future-you doesn't re-raise it

Don't try to FIX during the session — that breaks the user
mindset. Triage AFTER.

## Bug-finding tactics

While dogfooding, deliberately try:

### The wrong-input pass

- Submit empty fields
- Submit fields with leading/trailing whitespace
- Submit unicode (emoji, RTL text, zero-width)
- Submit very long inputs (10x what you expected)
- Submit values that look like SQL / shell / JSON injection (only
  in your own dev environment, of course)
- Click submit twice quickly

### The wrong-flow pass

- Use the back button mid-flow
- Refresh the page during async ops
- Navigate away and come back
- Open the same flow in two tabs

### The wrong-state pass

- Try the feature when nothing exists yet (empty state)
- Try with maximum stuff (large list state)
- Try when offline / slow network
- Try after sleeping the laptop for an hour

### The accessibility pass

Run the [[accessibility-baseline]] checklist on the surface
you're dogfooding. Often catches issues no functional test would
find.

### The new-user pass

Pretend you've never seen the product. Read every UI string. If
something is unclear (jargon, missing context), note it.

## Evidence discipline

For every bug or friction note, capture:

- Screenshot or video (most issue trackers accept these)
- Exact reproduction steps
- Browser / OS / version
- Time of occurrence (helps correlate with logs)

The cheapest moment to capture evidence is the moment the bug
happens. Don't promise yourself you'll reproduce it later — you
probably won't.

## When dogfooding fails

Sometimes the session goes great. No bugs, no friction. You
finished the goal smoothly. Is that good?

Maybe — OR — you were on autopilot using developer knowledge to
sidestep issues a real user would hit. Try again with:

- A different goal
- A different starting state (fresh install vs your usual)
- A different user persona (new user, power user, accessibility
  user)

If three sessions in a row find nothing, that's real signal that
this product surface is solid. But if you suspect autopilot:
recruit someone else to do the session. Fresh eyes find what
yours miss.

## After enough dogfood sessions

Patterns emerge:

- A specific feature shows up in your notes session after session
  → that's a systemic UX problem, prioritize accordingly
- A specific FAILURE MODE appears across features → suggests a
  cross-cutting issue (state management, error handling)
- The same friction never gets fixed despite being noted →
  signal to dig into WHY (no owner? unclear scope? low ROI?)

Dogfooding only pays back if you ACT on what you find. A growing
log with no follow-through is a stagnant ritual.

## Anti-patterns

- **The developer-pass**: clicking around with full developer
  knowledge; no friction found because you knew the workarounds.
- **The cheerleader pass**: noting only the good. Useful for
  morale, not for QA.
- **The 200-bug session**: noting EVERYTHING including
  microscopic style issues. Drowns the real signals.
- **Session without follow-through**: notes filed, nothing done.
  Every other session, schedule a "fix what dogfood found" hour.
- **Not actually using the product**: doing a code review while
  CALLING it dogfooding. Different activity.
