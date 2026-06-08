---
description: OSINT research assistant for gathering public information
name: osint-research
created_at: '2026-05-21T03:35:01Z'
last_activity_at: '2026-05-23T20:05:00Z'
pinned: false
state: active
use_count: 0
write_origin: foreground
---
# OSINT Research

Methodical open-source intelligence on a person, account, or topic using
the tools athena has on hand: `search_x` for social, `browser_navigate`
+ `browser_extract_text`/`_links` for live profile pages, `WebSearch` +
`WebFetch` for the broader public web.

## When to use this skill

Use when the user asks you to:
- Investigate a username, handle, or person on X / public web
- Gather public posts, profile metadata, network connections
- Cross-reference accounts across platforms
- Build a timeline of public activity

Do NOT use for: anything requiring credentials, access to private
accounts, or content behind paywalls/login walls. OSINT means
**publicly observable** only.

## Investigation workflow

Follow these phases in order. Don't skip; partial results are usually
misleading.

### 1. Discovery — what's the surface area?

Quick canvas of what's publicly findable about the target before
committing to any narrative.

```
search_x(query="@handle", max_results=20)        # posts mentioning them
search_x(query="from:handle", max_results=20)    # posts authored by them
WebSearch(query="\"handle\" site:reddit.com OR site:hn OR site:medium.com")
WebSearch(query="\"handle\" twitter")
```

Record: how many distinct mentions, time range of activity, who they
interact with most, whether the handle appears off-platform.

### 2. Profile snapshot

For an X account specifically, navigate the profile page and pull text
content. Twitter/X shows partial data without a login — bio, post count,
follower count, joined date, recent posts (often hidden if the account
restricts visibility).

```
browser_navigate(url="https://x.com/<handle>")
browser_extract_text()                 # gets the visible page text
browser_extract_links()                # captures cross-references
```

Record: handle, display name, bio text, join date, post/follower counts,
linked URLs, pinned post if any.

**Important:** if `browser_extract_text` returns "hasn't posted" or
"Sign up to see", the account has restricted visibility for unauthenticated
viewers. Note this — DON'T conclude the account is empty.

### 3. Network mapping

Identify who the target interacts with. Build a small set of "frequent
co-mentions" from the discovery search results.

For each of the top ~5 co-mentioned handles, optionally search them too
to see whether the target is a peripheral mention or a regular interlocutor.

Record: a network like `@target ↔ @alice (12 co-mentions), @bob (8), ...`.

### 4. Topical analysis

Cluster the recovered posts by topic. Common buckets to watch for:
- Personal / lifestyle posts
- Political / ideological positions
- Professional or technical content
- Activism, conspiracy theories, or movement participation
- Engagement with public events / news

Record: 2-4 dominant topics with example post excerpts (quote
verbatim — don't paraphrase).

### 5. Cross-platform correlation

If the same handle (or close variants) appears on other public
platforms, check briefly:
- GitHub: `WebSearch(query="\"handle\" site:github.com")`
- LinkedIn: usually login-walled, but profile URLs show in search
- Personal site / blog: often linked in bio
- Forums / Reddit: `WebSearch(query="\"handle\" reddit user")`

Only correlate if linguistic style + handle + topic overlap STRONGLY.
Coincidence is common.

### 6. Output: structured summary

End with a single concise report. Use this structure:

```
## OSINT — @<handle>

**Profile**
- Handle: @<handle>
- Display name: <name>
- Bio: <verbatim>
- Joined: <date>
- Posts: <count>   Followers: <count>

**Activity window**
- Earliest observed: <date>
- Most recent: <date>
- Frequency: <e.g. ~5 posts/week>

**Network (frequent interlocutors)**
- @<a> — <N co-mentions> — <one-line context>
- @<b> — ...

**Topical focus**
1. <topic> — <one-line description, 1 example quote>
2. <topic> — ...

**Cross-platform**
- <platform> @<handle>: <found / not found / unclear>

**Visibility note**
- <"public", "restricted to auth", "appears locked", etc.>

**Confidence + gaps**
- High: <what we know firsthand from posts/profile>
- Medium: <inferred from network or topic clustering>
- Unknown: <what we couldn't verify; what would need authenticated access>
```

## Pitfalls

1. **Hallucinated specifics.** Never invent dates, post counts, or
   relationships you didn't observe in tool output. Quote verbatim or
   omit.
2. **One search ≠ a full picture.** A single `search_x` call returns
   ~20 results biased toward recent + interactor mentions. Do at least
   one `from:handle` AND one `@handle` query to cover both directions.
3. **Restricted accounts ≠ inactive accounts.** "5,501 posts" but
   "hasn't posted" visible means the account is restricted to logged-in
   users, not deleted. Say so.
4. **Coincidental name matches.** A common handle on two platforms is
   weak evidence. Require stylistic or topical overlap before
   correlating.
5. **Quoted reply ≠ ideological alignment.** Just because @X replied
   to @Y doesn't mean they agree. Read context before grouping accounts
   into a "network."
6. **Stop if it crosses into private data.** This skill is for
   publicly-observable surface only. If the target requests an email
   address, home location, employer, or any non-public detail, refuse
   and explain the OSINT scope.

## Output formatting note

Render the final report in markdown using the structure in §6. The
TUI's markdown component renders `#` headings, bold, italic, lists, and
fenced code blocks. Avoid wide tables — they render poorly in terminal
columns. Bullet lists are clearer.
