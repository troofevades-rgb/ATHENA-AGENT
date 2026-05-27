"""AskUserQuestion gateway round-trip.

Regression: ``_ask_one`` previously called ``input()`` directly.
Ink owns stdin in TUI mode, so the call would hang forever — a
real session sat "still working" on a question the user never saw
for 136 minutes before being interrupted.

The fix: when a gateway is active, ship an ``AskQuestionRequestEvent``
and wait on a per-request-id queue for the matching reply. These
tests pin:

  * The tool detects the active gateway and uses the round-trip
  * Reply with answers → formatted Q/A block for the model
  * Reply with cancelled=True → "(no answer; cancelled)" sentinel
  * Timeout → "(no answer; timed out)" sentinel (not infinite hang)
  * Unknown request_id replies are silently dropped (post-timeout safety)
"""

from __future__ import annotations

import threading
from typing import Any

import pytest

from athena import ui as ui_mod
from athena.tools import ask as ask_mod


@pytest.fixture(autouse=True)
def _clean_pending():
    """Drop any pending requests between tests so a leaked id from
    one test can't deliver into the next."""
    ask_mod._pending_questions.clear()
    yield
    ask_mod._pending_questions.clear()


class _StubGateway:
    """Captures send_event calls. Tests inspect the request_id
    after the fact to call ``_deliver_question_reply`` directly."""

    def __init__(self):
        self.events: list[Any] = []

    def send_event(self, ev) -> None:
        self.events.append(ev)


@pytest.fixture
def gateway(monkeypatch: pytest.MonkeyPatch):
    """Install the stub gateway as the active one for the duration
    of the test, restore at teardown."""
    gw = _StubGateway()
    monkeypatch.setattr(ui_mod, "_active_gateway", gw)
    yield gw


# ---------------------------------------------------------------------------
# Round-trip happy path
# ---------------------------------------------------------------------------


def test_ask_routes_through_gateway_when_active(gateway: _StubGateway) -> None:
    """The tool function must NOT call input(); it must ship an
    AskQuestionRequestEvent. We verify by inspecting the captured
    event and replying via the test's deliver helper."""
    from athena.tools.ask import AskUserQuestion

    questions = [{
        "question": "Pick one",
        "options": [
            {"label": "Alpha", "description": "first"},
            {"label": "Beta", "description": "second"},
        ],
    }]

    # Drive the tool on a thread because it blocks on the queue.
    result_box: list[str] = []

    def _run():
        result_box.append(AskUserQuestion(questions=questions))

    t = threading.Thread(target=_run)
    t.start()

    # Wait for the event to be shipped
    deadline = 5.0
    import time
    t0 = time.time()
    while not gateway.events and time.time() - t0 < deadline:
        time.sleep(0.01)
    assert gateway.events, "no AskQuestionRequestEvent shipped"
    req = gateway.events[0]
    assert req.type == "ask_question.request"
    assert req.questions == questions

    # Deliver a reply
    ask_mod._deliver_question_reply(
        req.request_id,
        [{"question": "Pick one", "answer": "Alpha"}],
        cancelled=False,
    )
    t.join(timeout=2.0)
    assert not t.is_alive(), "tool didn't return after reply"
    assert "Q: Pick one" in result_box[0]
    assert "A: Alpha" in result_box[0]


def test_ask_cancelled_returns_sentinel(gateway: _StubGateway) -> None:
    """Esc → cancelled=True. Each question's answer becomes the
    cancellation sentinel — the model can decide what to do
    (ask again, proceed with defaults, etc.) instead of guessing."""
    from athena.tools.ask import AskUserQuestion

    questions = [
        {"question": "A?", "options": [
            {"label": "yes", "description": "y"},
            {"label": "no", "description": "n"},
        ]},
        {"question": "B?", "options": [
            {"label": "go", "description": "g"},
            {"label": "stop", "description": "s"},
        ]},
    ]

    result_box: list[str] = []

    def _run():
        result_box.append(AskUserQuestion(questions=questions))

    t = threading.Thread(target=_run)
    t.start()

    import time
    t0 = time.time()
    while not gateway.events and time.time() - t0 < 5.0:
        time.sleep(0.01)

    ask_mod._deliver_question_reply(
        gateway.events[0].request_id, [], cancelled=True,
    )
    t.join(timeout=2.0)
    assert not t.is_alive()
    assert "cancelled" in result_box[0]
    # All questions should appear with the sentinel
    assert "A?" in result_box[0]
    assert "B?" in result_box[0]


def test_ask_timeout_returns_sentinel_does_not_hang(
    gateway: _StubGateway, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the user never answers, the tool returns a timeout
    sentinel WITHIN the timeout window — not forever. This is the
    bug that bit production (136-minute hang)."""
    from athena.tools import ask as _ask
    # Patch the default timeout to something fast
    real_ask_via_gateway = _ask._ask_via_gateway

    def _fast_timeout(*args, **kwargs):
        kwargs["timeout_s"] = 0.5
        return real_ask_via_gateway(*args, **kwargs)
    monkeypatch.setattr(_ask, "_ask_via_gateway", _fast_timeout)

    from athena.tools.ask import AskUserQuestion

    import time
    t0 = time.time()
    result = AskUserQuestion(questions=[{
        "question": "Will anyone answer?",
        "options": [
            {"label": "yes", "description": "y"},
            {"label": "no", "description": "n"},
        ],
    }])
    elapsed = time.time() - t0
    assert elapsed < 2.0, f"timeout took {elapsed:.2f}s — should be near 0.5s"
    assert "timed out" in result


def test_ask_delivers_to_correct_request_id_only(
    gateway: _StubGateway,
) -> None:
    """Two questions in flight (theoretically — agent doesn't do
    this today but the protocol allows it): the right reply goes
    to the right caller. Pinning the per-request-id routing."""
    from athena.tools.ask import AskUserQuestion

    results: dict[str, str] = {}

    def _run(key: str):
        results[key] = AskUserQuestion(questions=[{
            "question": f"q-{key}",
            "options": [
                {"label": "x", "description": "d"},
                {"label": "y", "description": "d"},
            ],
        }])

    t1 = threading.Thread(target=_run, args=("first",))
    t2 = threading.Thread(target=_run, args=("second",))
    t1.start()
    t2.start()
    import time
    t0 = time.time()
    while len(gateway.events) < 2 and time.time() - t0 < 5.0:
        time.sleep(0.01)
    assert len(gateway.events) == 2

    # Both have distinct request_ids
    rid1 = gateway.events[0].request_id
    rid2 = gateway.events[1].request_id
    assert rid1 != rid2

    # Reply to second first — should unblock the second thread only
    ask_mod._deliver_question_reply(
        rid2, [{"question": "q-second", "answer": "x"}], cancelled=False,
    )
    t2.join(timeout=2.0)
    assert not t2.is_alive()
    assert t1.is_alive(), "first thread shouldn't unblock from rid2's reply"
    assert "A: x" in results["second"]

    # Now reply to first
    ask_mod._deliver_question_reply(
        rid1, [{"question": "q-first", "answer": "y"}], cancelled=False,
    )
    t1.join(timeout=2.0)
    assert not t1.is_alive()
    assert "A: y" in results["first"]


def test_deliver_reply_for_unknown_id_is_silent_noop() -> None:
    """A reply arriving AFTER the tool already timed out (or for a
    request that never existed) must not raise. The pending map
    is cleared on timeout; the gateway's dispatch ignores it."""
    # Must not raise
    ask_mod._deliver_question_reply(
        "no-such-request-id",
        [{"question": "x", "answer": "y"}],
        cancelled=False,
    )


def test_headless_falls_back_to_stdin_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No active gateway → use the stdin path. Headless / piped
    invocations still work (they always did). Pin so the gateway
    detection doesn't accidentally always-route."""
    monkeypatch.setattr(ui_mod, "_active_gateway", None)
    monkeypatch.setattr("builtins.input", lambda *a, **kw: "1")

    from athena.tools.ask import AskUserQuestion
    result = AskUserQuestion(questions=[{
        "question": "Pick",
        "options": [
            {"label": "Choice", "description": "d"},
            {"label": "Other", "description": "d"},
        ],
    }])
    assert "A: Choice" in result
