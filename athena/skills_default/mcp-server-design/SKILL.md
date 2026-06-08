---
description: Design and build MCP servers that LLMs actually use well
name: mcp-server-design
created_at: '2026-05-26T00:00:00Z'
last_activity_at: '2026-05-26T00:00:00Z'
pinned: false
state: active
use_count: 0
write_origin: foreground
---
# MCP Server Design

Disciplined approach to designing and building MCP servers. The
premise: most MCP servers are wrappers around an existing CLI or
library that LLMs can technically call but won't call well. A
well-designed MCP server makes the LLM's job EASIER, not just
possible.

## When to use this skill

Use when designing or building a new MCP server, or rewriting an
existing wrapper to be more LLM-friendly. Skip for one-off tools
that aren't meant to be reused.

## Design principles

### 1. Tool granularity: one verb, one tool

Don't bundle: ``manage_users(action="create"|"delete"|"update")``.
Split: ``create_user``, ``delete_user``, ``update_user``.

Why: the LLM picks the right tool by name. A bundled tool requires
the LLM to know the right action string, which it has to guess from
the description. Split tools self-document.

### 2. Tool naming: imperative verbs

- Good: ``read_file``, ``list_users``, ``send_email``
- Bad: ``file_handler``, ``user_management``, ``email_service``

Verb-first names tell the LLM what the tool DOES. Noun-first names
just label a domain.

### 3. Parameter design

For each parameter:

- **Required parameters** are truly required (the tool can't work
  without them)
- **Optional parameters** have sensible defaults (no "please pass
  ``null`` for use the default")
- **Enums** for any string with a fixed set of valid values
- **No "options" dicts** that take an unstructured blob

The LLM passes arguments based on the schema. If the schema is loose,
the calls will be loose. Tight schemas → tight calls.

### 4. Output design

LLMs read tool output character-by-character. Optimize for that:

- **Structured AND human-readable**: return both a structured field
  and a brief natural-language summary at the top
- **Pre-truncated**: don't return 50KB of output when 500 chars
  would suffice. Default to truncation with a follow-up call
  available for more
- **Errors as data**: don't raise — return ``{ok: false, error:
  "...", remediation: "..."}`` so the LLM knows what went wrong
  and what to do about it

Example output for a ``search_users`` tool:

```json
{
  "ok": true,
  "summary": "Found 3 users matching 'alice' (showing top 3 of 12).",
  "results": [
    {"id": 42, "name": "Alice Smith", "email": "alice@..."},
    ...
  ],
  "has_more": true,
  "next_page_token": "abc123"
}
```

The ``summary`` field lets the LLM act on the result without parsing
the JSON. The structured fields let it pass values to downstream
tools.

### 5. Descriptions that teach the LLM how to use the tool

The tool description is the only thing the LLM has to decide WHEN to
call your tool. Don't waste it.

Bad description:
> "Retrieve user data from the database."

Good description:
> "Search for users by name, email, or signup date. Returns up to
> 50 matches per call; use the pagination token for more.
>
> Example: search_users(query='alice') finds users with 'alice' in
> their name or email.
>
> Use this BEFORE create_user — checking for existing users prevents
> duplicates."

The good description (a) tells the LLM what the tool does, (b) gives
an example, (c) tells the LLM how this tool relates to OTHER tools.

### 6. Idempotency where possible

If a tool is safely re-runnable (e.g., ``send_email`` with an
idempotency key, ``create_user`` that returns the existing user on
duplicate), say so in the description. LLMs sometimes retry tool
calls; idempotent tools survive that gracefully.

### 7. Confirmation guards for destructive operations

For ``delete_*``, ``drop_*``, ``revoke_*``: require a confirmation
parameter that the LLM must pass explicitly:

```json
{
  "name": "delete_user",
  "parameters": {
    "user_id": "...",
    "i_understand_this_is_permanent": true
  }
}
```

The flag isn't bypass-proof, but it forces the LLM to consciously
acknowledge what it's doing — which raises the bar against
hallucinated destructive calls.

## Implementation patterns

### Transport

For most MCP servers, stdio is the right transport (Claude Desktop /
Cursor / VS Code / athena all support it). SSE / HTTP only if you
genuinely need network access from outside the same machine.

### Framework choice

If Python: ``fastmcp`` (the canonical SDK). Stable, well-documented,
handles the JSON-RPC plumbing.

If TypeScript: the official ``@modelcontextprotocol/sdk``.

Don't write your own JSON-RPC handler unless you have a strong reason
— the framework handles edge cases (request ordering, cancellation,
error propagation) that you'll re-discover painfully.

### Schema in code

Define schemas as code (Pydantic / Zod / dataclasses), not as raw
JSON Schema. The framework will derive the JSON Schema from them.
Code-first schemas mean you can't accidentally drift between
implementation and contract.

### Resource discovery

Many MCP clients support a "resources" concept distinct from
"tools" — read-only handles to data the LLM can fetch. For
read-heavy use cases, expose data AS resources rather than as
``get_*`` tools. Resources don't count against tool budgets and
are designed for browsing.

## Anti-patterns to refuse

- **The wrapper tool**: ``run_command(cmd: str)`` that just shells
  out. Useless — the LLM doesn't know what commands are valid.
- **The kitchen-sink tool**: ``do_everything(action, args)`` with 30
  branches. Split it.
- **The silent failure**: raising an exception that becomes an
  opaque "tool failed" message. Return ``{ok: false, ...}``.
- **The undocumented enum**: ``mode: str`` where only "fast" /
  "slow" work but the schema says any string. Use an enum.
- **Untyped passthrough**: accepting ``kwargs: dict`` and routing it
  to the underlying library. Define the supported fields explicitly.

## When NOT to build an MCP server

- The tool you'd wrap is already accessible (existing MCP, CLI the
  agent can shell out to, library the agent imports)
- The capability needs human-in-the-loop confirmation for EVERY call
  (a slash command or chat affordance is better)
- The tool is one-shot and small enough to inline as a Python
  function

MCP is for capabilities used across many sessions, by many agents.
For one-off code, just write the function.
