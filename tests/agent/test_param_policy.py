"""Parseltongue param policy: rule firing, merging, clamping, config."""

from __future__ import annotations

import pytest

from athena.agent.param_policy import (
    HeuristicPolicy,
    LLMClassifierPolicy,
    PolicyInput,
    Rule,
    StaticPolicy,
    _clamp,
    _merge_params,
    builtin_rules,
    heuristic_policy,
    policy_from_config,
    user_rules_from_config,
)


def _user(content: str) -> dict:
    return {"role": "user", "content": content}


def _tool(content: str) -> dict:
    return {"role": "tool", "name": "Bash", "content": content}


# ---- StaticPolicy ------------------------------------------------------


def test_static_policy_always_returns_same():
    p = StaticPolicy(defaults={"temperature": 0.5, "top_p": 0.9})
    a = p.params_for(PolicyInput(messages=[_user("refactor")]))
    b = p.params_for(PolicyInput(messages=[_user("brainstorm 5 ideas")]))
    assert a == b == {"temperature": 0.5, "top_p": 0.9}


def test_static_policy_explain_is_compact():
    p = StaticPolicy(defaults={"temperature": 0.5})
    lines = p.explain(PolicyInput(messages=[]))
    assert len(lines) == 1
    assert "static policy" in lines[0]


def test_static_policy_returns_a_copy():
    """Mutating the returned dict must not mutate the policy's defaults."""
    p = StaticPolicy(defaults={"temperature": 0.7})
    out = p.params_for(PolicyInput(messages=[]))
    out["temperature"] = 99.0
    again = p.params_for(PolicyInput(messages=[]))
    assert again["temperature"] == 0.7


# ---- HeuristicPolicy: intent classification ---------------------------


def test_code_intent_drops_temperature():
    p = heuristic_policy()
    out = p.params_for(PolicyInput(messages=[_user("refactor the parser")]))
    assert out["temperature"] == 0.3


def test_explain_intent_moderate_temperature():
    p = heuristic_policy()
    out = p.params_for(PolicyInput(messages=[_user("explain how mutexes work")]))
    assert out["temperature"] == 0.4


def test_brainstorm_intent_high_temperature():
    p = heuristic_policy()
    out = p.params_for(PolicyInput(messages=[_user("brainstorm 3 ideas for the name")]))
    assert out["temperature"] >= 0.8


def test_creative_intent_highest_temperature():
    p = heuristic_policy()
    out = p.params_for(PolicyInput(messages=[_user("write me a short story")]))
    assert out["temperature"] >= 0.9


def test_baseline_returns_empty_when_no_intent_matches():
    """A neutral prompt that doesn't match any intent rule yields an
    empty delta — the model's Modelfile-tuned defaults are preserved.

    Previously the baseline forced temperature=0.7 + repeat_penalty=1.1
    on EVERY call. That regressed structured tool-call emission for
    Modelfile-tuned models (e.g. troofevades-q35 uses temperature=0.3).
    The current contract: parseltongue ADAPTS when it has a signal;
    silence means 'don't touch anything'."""
    p = heuristic_policy()
    out = p.params_for(PolicyInput(messages=[_user("ok cool")]))
    assert out == {}, (
        f"baseline should be a no-op for neutral prompts; got {out}. "
        "Intent rules are what supply params — baseline is just the "
        "always-fires anchor of the rule list."
    )


def test_intent_uses_last_user_message():
    """If there are multiple user messages, the most recent one drives."""
    p = heuristic_policy()
    msgs = [
        _user("brainstorm ideas"),
        {"role": "assistant", "content": "[suggestions]"},
        _user("ok now refactor the chosen one"),
    ]
    out = p.params_for(PolicyInput(messages=msgs))
    # Last user message said "refactor" — code intent should win.
    assert out["temperature"] == 0.3


# ---- HeuristicPolicy: state modifiers ---------------------------------


def test_deep_tool_chain_drops_temperature():
    p = heuristic_policy()
    out = p.params_for(
        PolicyInput(messages=[_user("brainstorm ideas")], tool_calls_so_far=5)
    )
    # Even on a brainstorm prompt, the deep-chain modifier wins because
    # it's later in the rule order.
    assert out["temperature"] <= 0.15


def test_tool_just_errored_bumps_top_k():
    p = heuristic_policy()
    msgs = [
        _user("read the config"),
        _tool("Error: file not found"),
    ]
    out = p.params_for(PolicyInput(messages=msgs))
    assert out["top_k"] >= 60


def test_code_blocks_in_context_lowers_temp():
    """A conversation with fenced code blocks signals coding work even
    if the verbs in the latest user message don't match."""
    p = heuristic_policy()
    msgs = [
        {"role": "assistant", "content": "Here's the function:\n```python\ndef f(): pass\n```"},
        _user("looks good"),
    ]
    out = p.params_for(PolicyInput(messages=msgs))
    # The code-blocks-present rule fires (last 10 messages window).
    assert out["temperature"] <= 0.4


# ---- HeuristicPolicy: rule ordering / overrides -----------------------


def test_later_rules_override_earlier_keys():
    """A rule near the end of the list overrides earlier rules for the
    same param key — last-write-wins on merge."""
    rules = [
        Rule(name="first", predicate=lambda _: True, params={"temperature": 0.1}),
        Rule(name="second", predicate=lambda _: True, params={"temperature": 0.9}),
    ]
    p = HeuristicPolicy(rules=rules)
    out = p.params_for(PolicyInput(messages=[]))
    assert out["temperature"] == 0.9


def test_rules_can_specialize_without_clobbering():
    """A rule that only sets ``temperature`` should leave ``top_p``
    from an earlier rule intact."""
    rules = [
        Rule(name="base", predicate=lambda _: True, params={"temperature": 0.5, "top_p": 0.9}),
        Rule(name="adjust_temp_only", predicate=lambda _: True, params={"temperature": 0.2}),
    ]
    p = HeuristicPolicy(rules=rules)
    out = p.params_for(PolicyInput(messages=[]))
    assert out["temperature"] == 0.2
    assert out["top_p"] == 0.9


def test_failed_predicate_does_not_crash():
    """A buggy predicate must silently fail-closed (rule doesn't fire)
    rather than crashing the agent loop."""
    def broken(_inp):
        raise RuntimeError("oops")
    rules = [
        Rule(name="base", predicate=lambda _: True, params={"temperature": 0.5}),
        Rule(name="broken", predicate=broken, params={"temperature": 0.0}),
    ]
    p = HeuristicPolicy(rules=rules)
    out = p.params_for(PolicyInput(messages=[]))
    assert out["temperature"] == 0.5  # broken rule didn't fire


# ---- explain() ---------------------------------------------------------


def test_explain_lists_all_rules_with_fire_state():
    p = heuristic_policy()
    lines = p.explain(PolicyInput(messages=[_user("refactor")]))
    text = "\n".join(lines)
    # Every built-in rule shows up with either a checkmark or "did not fire".
    for rule in builtin_rules():
        assert rule.name in text
    # The final merged params line is present.
    assert "final:" in text


def test_explain_marks_fired_rules_distinctly():
    p = heuristic_policy()
    lines = p.explain(PolicyInput(messages=[_user("refactor")]))
    fired_lines = [ln for ln in lines if "✓" in ln]
    skipped_lines = [ln for ln in lines if "did not fire" in ln]
    assert len(fired_lines) >= 2  # baseline + code intent at minimum
    assert len(skipped_lines) >= 4  # the other intents + state modifiers


# ---- Clamping ---------------------------------------------------------


def test_clamp_keeps_temperature_in_range():
    params = {"temperature": 5.0}
    _clamp(params)
    assert params["temperature"] == 2.0


def test_clamp_keeps_top_p_in_range():
    params = {"top_p": -0.3}
    _clamp(params)
    assert params["top_p"] == 0.0


def test_clamp_preserves_int_top_k():
    """top_k should stay an int after clamping."""
    params = {"top_k": 9999}
    _clamp(params)
    assert isinstance(params["top_k"], int)
    assert params["top_k"] == 200


def test_clamp_ignores_unknown_params():
    """Provider-specific options not in the bounds table pass through."""
    params = {"some_ollama_specific_thing": "yes"}
    _clamp(params)
    assert params == {"some_ollama_specific_thing": "yes"}


def test_clamp_skips_non_numeric_values():
    """A buggy rule that put a string into ``temperature`` shouldn't crash."""
    params = {"temperature": "hot"}
    _clamp(params)
    assert params["temperature"] == "hot"  # unchanged, no crash


def test_buggy_rule_outputs_get_clamped():
    """End-to-end: a rule that emits an out-of-bounds value is clipped
    by the time params_for returns."""
    rules = [
        Rule(name="too_hot", predicate=lambda _: True, params={"temperature": 10.0}),
    ]
    p = HeuristicPolicy(rules=rules)
    out = p.params_for(PolicyInput(messages=[]))
    assert out["temperature"] == 2.0


# ---- User rules from config -------------------------------------------


def test_user_rule_matches_pattern():
    rules = user_rules_from_config([
        {"name": "yolo", "when": "user_message_matches", "pattern": r"(?i)\byolo\b",
         "params": {"temperature": 0.95}},
    ])
    assert len(rules) == 1
    inp_match = PolicyInput(messages=[_user("yolo mode engaged")])
    inp_miss = PolicyInput(messages=[_user("normal request")])
    assert rules[0].applies_to(inp_match) is True
    assert rules[0].applies_to(inp_miss) is False


def test_user_rule_always_fires():
    rules = user_rules_from_config([
        {"name": "always_low", "when": "always", "params": {"temperature": 0.1}},
    ])
    assert len(rules) == 1
    assert rules[0].applies_to(PolicyInput(messages=[])) is True


def test_user_rule_tool_chain_threshold():
    rules = user_rules_from_config([
        {"name": "deep", "when": "tool_calls_at_least", "count": 3,
         "params": {"temperature": 0.1}},
    ])
    assert rules[0].applies_to(PolicyInput(messages=[], tool_calls_so_far=2)) is False
    assert rules[0].applies_to(PolicyInput(messages=[], tool_calls_so_far=3)) is True


def test_user_rule_bad_regex_is_dropped():
    """A regex that fails to compile drops the rule, doesn't crash."""
    rules = user_rules_from_config([
        {"name": "bad", "when": "user_message_matches", "pattern": "([unclosed",
         "params": {}},
    ])
    assert rules == []


def test_user_rule_unknown_when_is_dropped():
    rules = user_rules_from_config([
        {"name": "huh", "when": "telepathy", "params": {}},
    ])
    assert rules == []


def test_user_rule_layers_after_builtins():
    """User rules in the config should fire after the built-in rules,
    so they can override defaults."""
    user = user_rules_from_config([
        {"name": "global_low", "when": "always", "params": {"temperature": 0.05}},
    ])
    p = heuristic_policy(extra_rules=user)
    out = p.params_for(PolicyInput(messages=[_user("brainstorm ideas")]))
    # Brainstorm wanted 0.85; the user rule fires last and overrides.
    assert out["temperature"] == 0.05


# ---- policy_from_config ------------------------------------------------


def test_policy_from_config_static():
    p = policy_from_config({"policy": "static", "defaults": {"temperature": 0.42}})
    assert isinstance(p, StaticPolicy)
    assert p.params_for(PolicyInput(messages=[])) == {"temperature": 0.42}


def test_policy_from_config_heuristic():
    p = policy_from_config({"policy": "heuristic"})
    assert isinstance(p, HeuristicPolicy)


def test_policy_from_config_default_is_heuristic():
    """An empty or missing config picks heuristic (the new default)."""
    assert isinstance(policy_from_config(None), HeuristicPolicy)
    assert isinstance(policy_from_config({}), HeuristicPolicy)


def test_policy_from_config_unknown_falls_back():
    """A config typo shouldn't prevent the agent from booting."""
    p = policy_from_config({"policy": "nonsense"})
    assert isinstance(p, HeuristicPolicy)


def test_policy_from_config_llm_classifier_is_rejected():
    """Until the LLM classifier actually does something, refuse the
    selection so the operator gets an explicit error rather than a
    phantom 'upgrade' that silently runs the heuristic. The class
    still exists for future development."""
    with pytest.raises(ValueError, match="not yet implemented"):
        policy_from_config({"policy": "llm_classifier", "classifier_model": "qwen2.5:1.5b"})


def test_llm_classifier_policy_class_still_present():
    """LLMClassifierPolicy isn't selectable from config, but the class
    is preserved so in-progress work can target it directly without
    a rebase."""
    p = LLMClassifierPolicy(
        classifier_model="qwen2.5:1.5b",
        fallback=policy_from_config({"policy": "heuristic"}),
    )
    out = p.params_for(PolicyInput(messages=[_user("refactor")]))
    assert out["temperature"] == 0.3


def test_policy_from_config_with_user_rules():
    p = policy_from_config({
        "policy": "heuristic",
        "user_rules": [
            {"name": "yolo", "when": "user_message_matches", "pattern": "yolo",
             "params": {"temperature": 0.99}},
        ],
    })
    out = p.params_for(PolicyInput(messages=[_user("yolo")]))
    # After clamping (max 2.0), 0.99 passes through unchanged.
    assert out["temperature"] == 0.99


# ---- _merge_params -----------------------------------------------------


def test_merge_overwrites_keys():
    running = {"temperature": 0.5, "top_p": 0.9}
    _merge_params(running, {"temperature": 0.1})
    assert running == {"temperature": 0.1, "top_p": 0.9}


def test_merge_adds_new_keys():
    running = {"temperature": 0.5}
    _merge_params(running, {"top_k": 60})
    assert running == {"temperature": 0.5, "top_k": 60}
