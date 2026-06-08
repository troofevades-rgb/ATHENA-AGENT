---
description: Write tests that catch real bugs, not tests that exercise mocks
name: test-writing-discipline
created_at: '2026-05-26T00:00:00Z'
last_activity_at: '2026-05-26T00:00:00Z'
pinned: false
state: active
use_count: 0
write_origin: foreground
---
# Test-Writing Discipline

Disciplined approach to writing tests so the suite catches real bugs.
The premise: a 100% green suite is worth nothing if the tests just
exercise mocks and reaffirm what the developer thought yesterday.

## When to use this skill

Use when writing or reviewing tests for new code, especially:
- A new feature surface
- A regression fix (test must fail without the fix)
- A bug-prone module (persistence, concurrency, state machines)

Skip for trivial getters / pure-data classes.

## The three-question gate

Before each test, answer:

### 1. What's the failure mode this catches?

If you can't name a specific concrete failure — "this test catches the
bug where two concurrent writes interleave and the second overwrites
the first" — the test is decoration, not coverage. Either rewrite or
delete.

### 2. Would this test still pass if I broke the production code?

For a regression test, the most important property is that it FAILS
before the fix and PASSES after. Run the test against the broken
version first to verify.

For new-feature tests: do one negative case — try the obvious wrong
implementation and confirm the test catches it. If the test doesn't
catch the obvious wrong implementation, it won't catch the subtle
one either.

### 3. Am I testing behavior or implementation?

Behavior tests survive refactors. Implementation tests break.

```python
# behavior — survives refactor
def test_user_can_log_in():
    assert login("alice", "correct-pw").is_authenticated

# implementation — breaks when we change the hash algo
def test_login_calls_bcrypt_hashpw():
    with patch("bcrypt.hashpw") as h:
        login("alice", "pw")
        h.assert_called_once()
```

Default to behavior. Implementation tests are appropriate ONLY when
the implementation detail IS the contract (e.g., "the cache must use
LRU eviction" is a contract; assert the eviction order).

## Mocks: when, and where

Mock at the BOUNDARY of your code, not inside it.

- Mock external services (HTTP, DB drivers, filesystem when it's
  another machine's filesystem).
- Mock time when the test depends on it (``freeze_time``).
- Do NOT mock your own functions — that just tests the mock.

If you find yourself mocking 5+ things to set up one test, the code
under test has too many dependencies. Refactor before testing.

## The integration:unit ratio

For most codebases the right ratio is ~30% integration, ~70% unit.
If your tests are 95%+ unit:
- You probably mock too aggressively
- You probably have low confidence after a green run that the system
  actually works end-to-end

A single integration test that exercises the real database, real HTTP
client, and real disk catches a class of bugs that 100 unit tests with
mocks never will.

## Patterns to refuse

- **Tests that test the mock**: setting up a mock to return X, calling
  the function, asserting the function returned X. Verifies nothing.
- **Sleep-based timing**: ``time.sleep(0.5); assert condition``.
  Flaky and slow. Use proper synchronization primitives or event hooks.
- **Test interdependence**: test B only passes when test A ran first.
  Each test must work in isolation.
- **Multi-assertion ambiguity**: one test asserting 10 unrelated
  things. Split them — when one fails, you want to know exactly which.
