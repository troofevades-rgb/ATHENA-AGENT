---
description: Disciplined response when production is on fire
name: incident-response
created_at: '2026-05-26T00:00:00Z'
last_activity_at: '2026-05-26T00:00:00Z'
pinned: false
state: active
use_count: 0
write_origin: foreground
---
# Incident Response

Disciplined approach to handling a production incident. The premise:
during an incident, the urge to "just fix it fast" is the urge that
prolongs incidents. Discipline shortens them.

## When to use this skill

Use when production is broken, degraded, or about to be: error
rates spiking, users reporting an outage, an alert firing, the team
chat saying "is anyone seeing X?" Skip for non-production issues
that have time for proper triage.

## The first 5 minutes

In order, no skipping:

### 1. Stop the bleeding

Before debugging anything: can you reduce the blast radius?

- **Roll back** the most recent deploy if the timing matches
- **Feature flag off** the suspected feature
- **Failover** to the secondary region/replica
- **Rate limit** the affected endpoint
- **Take the affected service out of rotation** if it's degraded
  but the rest of the system can survive without it

Stopping the bleeding doesn't mean fixing the bug. It means buying
time for everything that follows. Do this FIRST.

### 2. Declare the incident

Open the incident channel / page the on-call / start the war room.
Now the rest of the team knows it's happening, they can stop other
work, and they can help.

State (one sentence):
- What's broken (user-facing impact)
- When it started
- What's been tried so far

### 3. Designate an Incident Commander (IC)

ONE person owns the incident. Their job is NOT to debug — it's to:

- Coordinate (who's looking at what)
- Communicate (status to stakeholders)
- Decide (when to escalate, when to declare resolved)

The IC is the ROUTER, not the EXPERT. The expert(s) debug; the IC
makes sure they have what they need and aren't stepping on each
other.

### 4. Start a timeline

In the incident channel or doc, append every action with a
timestamp:

```
14:32 alert fired: error rate on /checkout > 5%
14:34 IC: @alice, can you check the recent deploys?
14:35 alice: deploy at 14:28 included PR #4521 (cache change)
14:37 IC: rolling back to previous revision
14:39 alice: rollback complete, watching metrics
14:42 alice: error rate back to baseline
14:45 IC: declaring resolved pending postmortem
```

This timeline becomes the postmortem source. Writing it during the
incident is 10x cheaper than reconstructing it later.

## During the incident

### Communication rhythm

- Status update to stakeholders every 15 minutes, even if "no
  change"
- Be explicit about confidence: "We've rolled back; we BELIEVE
  this resolves it; we're WATCHING for 10 minutes before declaring."
- Don't say "should be fixed" — say "fixed" or "still investigating"

### Hypotheses are cheap, action is cheap, debate is expensive

When multiple people propose theories, the IC's job is:

1. Acknowledge each theory
2. Assign someone to validate the cheapest one first
3. Move on — don't host a debate

Validation comes from data, not argument. Burn down hypotheses by
checking data, not by who's more senior.

### When to escalate

Escalate when:

- 30 minutes in with no clear path forward
- Customer-visible impact is growing despite mitigation
- The incident involves a system or team you don't have expertise on
- Legal / regulatory / PR implications (data breach, financial harm,
  public-facing outage)

Escalating is not failing. NOT escalating when you should is.

## Declaring resolved

The IC declares resolved when:

- The user-facing symptom is gone (metrics confirm, not just
  silence from users)
- The system has been stable for at least 2x the typical
  observation window (e.g., 15 min for a service with 5-min
  alerting)
- The team is confident the fix WON'T regress (rolled-back change,
  flag off, etc.)

Premature "resolved" declarations are the #1 cause of incidents that
flap. When in doubt: watch longer.

## After resolution

### Within 24 hours: blameless postmortem

NOT optional. NOT a punishment. The postmortem captures:

- **Timeline**: what happened, when (from the incident timeline)
- **Impact**: who was affected, for how long, what was the cost
- **Root cause**: the technical cause + the systemic cause
  ("the validator didn't catch X" + "the validator wasn't tested for
  Y because Z")
- **What went well**: yes — recognize the discipline that worked
- **What went poorly**: where the response could have been faster
  or cleaner
- **Action items**: specific, owned, time-boxed

"Blameless" means: assume everyone made reasonable decisions with
the information they had. The goal is system improvement, not
person blame.

### Action items: prioritize ruthlessly

Most postmortems generate 20+ action items. Most teams ship 2 of
them. To improve odds:

- Tag each item P0 (must-fix) / P1 (should-fix) / P2 (nice-to-fix)
- P0 items go on the next sprint, owned by a specific person
- P1 items go in the backlog with a follow-up review date
- P2 items go in a backlog with no commitment

A small number of P0s actually shipped beats a long list of P0s
that don't get done.

## Anti-patterns to refuse

- **"Let me just try one thing"** — without coordinating with the
  IC. You can stomp on someone else's investigation or rollback.
- **The hero fix at 3 AM** — quick fix in production without code
  review. Sometimes necessary, but log it as tech debt and follow
  up THAT WEEK.
- **Skipping the postmortem** — "we know what happened, let's
  move on." The postmortem isn't for what happened; it's for what
  prevents it next time.
- **Blame in postmortem** — "Alice broke it." Reframe as "the
  process didn't catch X before merge."
- **Postmortem perfectionism** — taking 3 weeks to write a 20-page
  doc. A 2-page doc shipped within 48 hours beats a 20-page doc
  shipped never.
