---
description: What to instrument so production failures are debuggable in minutes, not hours
name: observability-baseline
created_at: '2026-05-26T00:00:00Z'
last_activity_at: '2026-05-26T00:00:00Z'
pinned: false
state: active
use_count: 0
write_origin: foreground
---
# Observability Baseline

Disciplined approach to instrumenting a service so production
failures are diagnosable quickly. The premise: when production
breaks at 3 AM, you're not adding observability — you're using the
observability you already shipped. The instrumentation you didn't
ship is the bug you can't find.

## When to use this skill

Use when designing or shipping a new service, endpoint, or
background job. Use during [[incident-response]] postmortems when an
action item is "we couldn't debug this fast enough." Skip for
throwaway scripts that don't run in production.

## The three pillars

Modern observability rests on three signal types — all needed,
none sufficient alone.

### 1. Metrics: aggregate health

Numerical time series, usually in Prometheus / DataDog / CloudWatch
format. They tell you WHAT is happening.

Minimum baseline for any service:

- **RED**: Rate (requests/sec), Errors (errors/sec or error rate),
  Duration (latency p50/p95/p99) — for request-driven services
- **USE**: Utilization, Saturation, Errors — for resource-driven
  services (DBs, queues, caches)
- **Business metrics**: signups/min, orders/min, whatever the system
  actually exists to produce

For each metric, set BOTH:

- An alert threshold (when to wake someone up)
- A dashboard panel (so you can see trends without an alert)

### 2. Logs: detailed records

Structured text per event. They tell you WHY something happened.

Logging discipline:

- **Structured (JSON or key=value), not free text** — so logs are
  greppable AND machine-parseable
- **One log line per important event** — start, end, branch
  decisions, errors. Not every line of code.
- **Include the request/trace ID** so logs from one request can be
  joined across services
- **Levels used correctly**:
  - ERROR: something failed that needs attention
  - WARN: something unexpected but recoverable
  - INFO: normal operational events (start/end of significant work)
  - DEBUG: detail for debugging, off by default
- **No sensitive data**: passwords, tokens, PII. Use placeholders
  or hashes.

### 3. Traces: causal paths

A trace is a request's journey through the system, with timing per
hop. They tell you WHERE the latency is.

Tracing discipline:

- Propagate the trace ID across service boundaries (in HTTP headers,
  in message attributes for queues, in DB query comments)
- Sample meaningfully: 100% for errors, 10% for normal traffic, more
  for endpoints under investigation
- Annotate spans with the values that matter (user ID, action
  type, downstream service name)

For most apps in 2026: OpenTelemetry is the right standard. The
collector is vendor-neutral; switch backends without changing
instrumentation.

## The "first 5 minutes" test

Once your service is instrumented, run this drill: someone reports
"users are seeing errors on the checkout page." Without writing any
new code or SSH'ing to a box, can you answer these in 5 minutes?

1. Is the error rate ACTUALLY elevated, or is the report noise?
   (metric)
2. WHEN did it start? (metric with timestamp)
3. WHAT'S the error? Stack trace, status code, message? (log)
4. WHO is affected? Specific users? A region? A device type?
   (log + trace)
5. WHERE in the request flow is it failing? Auth? Inventory?
   Payment? (trace)

If any of these requires "let me add a log line and redeploy" — your
observability isn't sufficient. Add what's missing now, before the
next incident.

## Practical baseline by service type

### HTTP API service

- Metrics: request rate, error rate (4xx, 5xx separately), latency
  histogram, by endpoint and method
- Logs: one log line per request with method, path, status, latency,
  request ID, user ID (if authenticated)
- Traces: every request gets a trace; sample 100% of errors

### Background worker / queue consumer

- Metrics: jobs/sec processed, jobs/sec failed, queue depth,
  processing latency, retry counts
- Logs: job start, job end, job failure with reason. Include job ID
  and any user/correlation IDs
- Traces: each job is a trace; if it triggers external calls, those
  are spans

### Database / data store

- Metrics: query rate, error rate, latency histogram, connection
  pool usage, replication lag (if applicable), cache hit rate
- Logs: slow queries above a threshold, connection errors, failed
  transactions
- Traces: trace spans for important queries (auto-instrumented by
  most ORMs)

### Frontend / client

- Metrics: page load time (LCP, FID, CLS — Core Web Vitals),
  JS error rate, API error rate per endpoint
- Logs: client-side errors (Sentry / Bugsnag / similar) with
  stack traces and user agent
- Traces: link client traces to server traces via trace propagation

## What NOT to instrument

- **Every variable assignment** — your logs become unreadable
- **PII or secrets** — compliance + security problem
- **High-cardinality labels in metrics** — a label per user ID will
  blow up your metrics backend. Use traces and logs for per-user
  detail; reserve metrics for aggregate cardinality.
- **Logs you never read** — if a log line has never helped debug a
  problem in 6 months, delete it (or downgrade to DEBUG)

## Cost discipline

Observability isn't free. At scale, log volume + metrics cardinality
+ trace storage can rival compute costs.

- Sample traces (10% normal, 100% errors)
- Drop INFO logs in production for high-volume code paths (use
  metrics for those)
- Set log retention per environment (prod 30d, staging 7d, dev 1d)
- Review metrics cardinality monthly — high-cardinality labels are
  the #1 cost driver

The goal isn't infinite data. The goal is the RIGHT data — enough to
answer the first-5-minutes questions, no more.

## Incident-feedback loop

After every [[incident-response]] postmortem, the action items
should include observability gaps:

- "We couldn't tell which request triggered it" → add request ID
  propagation
- "We thought it was the cache but couldn't confirm" → add cache
  hit/miss metric
- "We didn't know it had started 30 min before alert fired" → tune
  alert threshold

Each incident strengthens the observability baseline for next time.
A team that doesn't close this loop fights the same fire repeatedly.
