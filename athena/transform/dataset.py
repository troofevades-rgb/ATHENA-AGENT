"""SFT and DPO dataset construction.

Two outputs share the same JSONL-on-disk format (one JSON object per line)
but different per-example shapes:

- **SFT** — ``{"messages": [...], "metadata": {...}}``. The OpenAI
  fine-tuning format; ``trl.SFTTrainer`` accepts this directly.
- **DPO** — ``{"prompt": str, "chosen": str, "rejected": str,
  "metadata": {...}}``. ``trl.DPOTrainer`` accepts this directly.

DPO has two builder entry points:

- :func:`build_dpo_dataset_from_trajectories` — the **correct, default
  path**. Each ``preference_pair`` trajectory is split at its ``[/steer]``
  marker into a (prompt, chosen, rejected) tuple where the prompt is the
  trajectory's opening user message, ``rejected`` is the pre-steer
  assistant work, and ``chosen`` is the post-steer recovery. The two
  branches share one prompt — what DPO actually requires.
- :func:`build_dpo_dataset` (legacy) — accepts pre-built
  ``(chosen, rejected)`` trajectory pairs. Useful only when callers have
  same-prompt re-runs across sessions. The pre-existing cross-trajectory
  pairing in ``cli/train.py`` was unsafe because it paired trajectories
  with *different* prompts; that path has been removed.

Chat-template handling is currently a no-op: the trainer applies the
template at tokenization time, so we just hand it the role-tagged
messages. ``chat_template`` is plumbed through and stored in the
metadata for traceability, and so future templates that need
preprocessing here have an obvious extension point.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .classifier import Trajectory

SUPPORTED_CHAT_TEMPLATES = ("qwen-coder", "chatml", "openai")


def build_sft_dataset(
    trajectories: list[Trajectory],
    *,
    chat_template: str = "qwen-coder",
    include_auto_labels: bool = False,
) -> list[dict[str, Any]]:
    """Convert user-labeled (or auto-labeled, opt-in) ``good`` trajectories
    into SFT examples.

    Each example: ``{"messages": [...], "metadata": {...}}``. ``messages``
    is the trajectory's full role-tagged sequence, lightly normalized:

    - The opening ``system`` message (if any) is included once at the
      head. (The session-level system message is upstream of the
      trajectory; the caller must include it explicitly via the
      trajectory's first turn if they want it. For now we synthesize a
      tiny placeholder so the example is well-formed.)
    - ``tool_calls`` are preserved on assistant messages as JSON-encoded
      strings inside the message content (qwen-coder native format) —
      kept compatible with the existing ``transform/scripts/train_lora.py``
      preprocessing.
    - ``tool`` role messages are passed through unchanged.

    Filters: only trajectories whose ``user_label == "good"`` are
    included by default. ``include_auto_labels=True`` also pulls in
    trajectories whose ``auto_label == "good"`` and have not been
    overridden by a user label.
    """
    if chat_template not in SUPPORTED_CHAT_TEMPLATES:
        raise ValueError(
            f"unsupported chat_template {chat_template!r}; "
            f"expected one of {SUPPORTED_CHAT_TEMPLATES}"
        )
    examples: list[dict[str, Any]] = []
    for t in trajectories:
        if not _is_good(t, include_auto_labels=include_auto_labels):
            continue
        messages = _trajectory_to_messages(t, chat_template)
        examples.append(
            {
                "messages": messages,
                "metadata": {
                    "session_id": t.session_id,
                    "turn_range": [t.turn_start, t.turn_end],
                    "chat_template": chat_template,
                    "label_source": ("user" if t.user_label == "good" else "auto"),
                },
            }
        )
    return examples


def build_dpo_dataset(
    pairs: list[tuple[Trajectory, Trajectory]],
    *,
    chat_template: str = "qwen-coder",
) -> list[dict[str, Any]]:
    """Convert (chosen, rejected) trajectory pairs into DPO examples.

    ``prompt`` is the concatenated user turns shared by the two
    trajectories' opening (assumed identical up to the rejection point —
    callers are responsible for passing pairs that actually share a
    prompt). ``chosen`` and ``rejected`` are each trajectory's final
    assistant content. Tool-call rounds are flattened into the response
    text so the DPO model sees them as part of the candidate output.

    Pairs whose chosen / rejected look identical are dropped (they
    contribute nothing to the preference signal).
    """
    if chat_template not in SUPPORTED_CHAT_TEMPLATES:
        raise ValueError(
            f"unsupported chat_template {chat_template!r}; "
            f"expected one of {SUPPORTED_CHAT_TEMPLATES}"
        )
    examples: list[dict[str, Any]] = []
    for chosen, rejected in pairs:
        prompt = _trajectory_prompt(chosen)
        chosen_resp = _trajectory_response(chosen)
        rejected_resp = _trajectory_response(rejected)
        if chosen_resp.strip() == rejected_resp.strip():
            continue
        examples.append(
            {
                "prompt": prompt,
                "chosen": chosen_resp,
                "rejected": rejected_resp,
                "metadata": {
                    "chosen_session_id": chosen.session_id,
                    "rejected_session_id": rejected.session_id,
                    "chat_template": chat_template,
                },
            }
        )
    return examples


# ---- In-trajectory DPO extraction (the correct, default path) -----------


# Failure-mode tags emitted by :func:`_classify_failure_mode`. Stored in
# the DPO example's metadata so the dataset can be sliced by failure kind
# at training time (e.g. balance ``wrong_tool`` vs ``bad_args`` pairs)
# and so post-hoc evaluation can ask whether DPO moved the needle on
# each category specifically.
FAILURE_MODES = (
    "wrong_tool",      # rejected called a different tool than chosen at the same step
    "bad_args",        # same tool name, different arguments
    "missing_tool",    # rejected made no tool calls; chosen used at least one
    "extra_tool",      # rejected made tool calls; chosen made none (model over-acted)
    "tool_error",      # rejected's tool output contained an error indicator
    "truncated",       # rejected is substantially shorter than chosen (>4x diff)
    "format_error",    # rejected has malformed tool_call json or stray markers
    "other",           # signal exists but didn't match a specific bucket
)


def extract_steer_dpo_example(
    trajectory: Trajectory,
    *,
    chat_template: str = "qwen-coder",
) -> dict[str, Any] | None:
    """Split a single ``preference_pair`` trajectory at its ``[/steer]``
    marker into a valid DPO example.

    Returns ``None`` (rather than raising) when the trajectory:

    - has no ``[/steer]`` user message,
    - the steer arrives before any assistant work (no rejected branch),
    - the steer arrives at the end with no following assistant work
      (no chosen branch),
    - the two branches stringify identically (zero preference signal).

    The trajectory's ``user_label`` is **not** checked here; callers
    decide which trajectories to feed in. :func:`build_dpo_dataset_from_trajectories`
    applies the standard ``user_label == "preference_pair"`` filter.

    Both branches share the trajectory's opening user message as their
    prompt — which is the DPO invariant the previous cross-trajectory
    pairing violated.
    """
    if chat_template not in SUPPORTED_CHAT_TEMPLATES:
        raise ValueError(
            f"unsupported chat_template {chat_template!r}; "
            f"expected one of {SUPPORTED_CHAT_TEMPLATES}"
        )

    turns = trajectory.turns
    steer_idx = _find_first_steer_index(turns)
    if steer_idx is None:
        return None

    prompt = _opening_user_prompt(turns)
    if not prompt:
        return None

    # Pre-steer span: everything between the opening user message (turn 0)
    # and the steer marker (exclusive). Post-steer span: everything after
    # the steer marker (exclusive) to the end of the trajectory.
    rejected_span = turns[1:steer_idx]
    chosen_span = turns[steer_idx + 1 :]

    rejected = _span_response(rejected_span)
    chosen = _span_response(chosen_span)

    if not rejected.strip() or not chosen.strip():
        return None
    if rejected.strip() == chosen.strip():
        return None

    return {
        "prompt": prompt,
        "chosen": chosen,
        "rejected": rejected,
        "metadata": {
            "session_id": trajectory.session_id,
            "turn_range": [trajectory.turn_start, trajectory.turn_end],
            "chat_template": chat_template,
            "source": "steer_recovery",
            "failure_mode": _classify_failure_mode(rejected_span, chosen_span),
        },
    }


def build_dpo_dataset_from_trajectories(
    trajectories: list[Trajectory],
    *,
    chat_template: str = "qwen-coder",
    include_auto_labels: bool = False,
) -> list[dict[str, Any]]:
    """Build DPO examples from ``preference_pair`` trajectories.

    For each qualifying trajectory, calls :func:`extract_steer_dpo_example`
    and collects the non-``None`` results. Trajectories that don't qualify
    (no steer, no chosen, no rejected, or identical branches) are silently
    dropped — the caller can check ``len(out)`` against the input count if
    a yield rate matters.

    Filter: by default, only ``user_label == "preference_pair"``.
    ``include_auto_labels=True`` also pulls trajectories whose
    ``auto_label == "preference_pair"`` and have no human override.
    """
    examples: list[dict[str, Any]] = []
    for t in trajectories:
        if not _is_preference_pair(t, include_auto_labels=include_auto_labels):
            continue
        example = extract_steer_dpo_example(t, chat_template=chat_template)
        if example is not None:
            examples.append(example)
    return examples


def write_jsonl(path: Path, examples: list[dict[str, Any]]) -> None:
    """Write ``examples`` to ``path``, one JSON object per line. Creates
    parent directories. Overwrites any existing file atomically — a
    mid-write crash leaves the previous file (if any) intact, never
    a half-written one.

    Strategy: write to ``<path>.tmp``, fsync, then rename onto
    ``path``. On POSIX rename is atomic. On Windows ``Path.replace``
    is also atomic when both paths are on the same volume (which
    they are by construction here)."""
    import os
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            for ex in examples:
                f.write(json.dumps(ex, sort_keys=True) + "\n")
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                # fsync can fail on some filesystems / mounts (e.g.
                # /tmp on tmpfs). The atomic rename below is still
                # the durability guarantee the test pins; fsync is
                # belt-and-suspenders.
                pass
        tmp.replace(path)
    except BaseException:
        # Clean up the tmp file on failure so a crashed train run
        # doesn't leave .tmp turds behind. Use Path.unlink with
        # missing_ok so we don't mask the real exception.
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


# ---- Internals ----------------------------------------------------------


# Markers we treat as "this tool call landed on an error". Matches the
# heuristic in :mod:`athena.transform.classifier` but kept local so the
# two modules don't grow a circular dependency over a regex.
_ERROR_HINTS = ("Error:", "Traceback", "BLOCKED", "DENIED")


def _is_good(t: Trajectory, *, include_auto_labels: bool) -> bool:
    if t.user_label == "good":
        return True
    if include_auto_labels and t.user_label == "unreviewed" and t.auto_label == "good":
        return True
    return False


def _is_preference_pair(t: Trajectory, *, include_auto_labels: bool) -> bool:
    if t.user_label == "preference_pair":
        return True
    if (
        include_auto_labels
        and t.user_label == "unreviewed"
        and t.auto_label == "preference_pair"
    ):
        return True
    return False


def _find_first_steer_index(turns: list[dict[str, Any]]) -> int | None:
    """Return the index of the first ``[/steer]`` user message inside the
    trajectory, or ``None`` if there is none. We split on the **first**
    steer so the rejected branch is the model's unaided attempt; later
    steers (if any) are folded into the chosen branch as part of the
    user-guided recovery.
    """
    for i, m in enumerate(turns):
        if m.get("role") != "user":
            continue
        content = m.get("content") or ""
        if isinstance(content, str) and content.startswith("[/steer]"):
            return i
    return None


def _opening_user_prompt(turns: list[dict[str, Any]]) -> str:
    """The trajectory's first user message, stripped of any synthetic
    framing. By construction (see :func:`classifier.extract_trajectories`)
    this is always a non-``[/steer]`` user message, but we double-check.
    """
    if not turns:
        return ""
    head = turns[0]
    if head.get("role") != "user":
        return ""
    content = head.get("content") or ""
    if not isinstance(content, str):
        return ""
    if content.startswith("[/steer]"):
        # Defensive: trajectory shouldn't open on a steer per the
        # classifier contract. If somehow it does, treat as no prompt.
        return ""
    return content


def _span_response(span: list[dict[str, Any]]) -> str:
    """Stringify the assistant work inside a slice of trajectory turns,
    including ``<tool_call>`` blobs and (for context) the tool results
    that came back. Mirrors :func:`_trajectory_response` so the chosen
    and rejected branches have the same encoding as legacy DPO examples.
    """
    parts: list[str] = []
    for m in span:
        role = m.get("role")
        if role == "assistant":
            content = m.get("content") or ""
            if content:
                parts.append(content)
            for tc in m.get("tool_calls") or []:
                parts.append(
                    "<tool_call>"
                    + json.dumps(_normalize_tool_call(tc), sort_keys=True)
                    + "</tool_call>"
                )
        elif role == "tool":
            # Include tool outputs in the response so the preference signal
            # captures "model called tool X and got error Y" vs "model
            # called tool Z and got useful output". The trainer sees these
            # as part of the candidate branch.
            content = m.get("content") or ""
            if isinstance(content, str) and content:
                name = m.get("name") or "tool"
                parts.append(f"<tool_result name={name!r}>{content}</tool_result>")
    return "\n".join(parts)


def _extract_tool_calls(span: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Return ``(tool_name, normalized_arguments_json)`` per assistant
    tool call in the span, in call order. Used to compare branches for
    failure-mode classification.
    """
    out: list[tuple[str, str]] = []
    for m in span:
        if m.get("role") != "assistant":
            continue
        for tc in m.get("tool_calls") or []:
            normalized = _normalize_tool_call(tc)
            fn = normalized.get("function") or {}
            name = fn.get("name") or ""
            args = fn.get("arguments") or "{}"
            out.append((name, args))
    return out


def _span_has_tool_error(span: list[dict[str, Any]]) -> bool:
    """True if any ``tool`` message in the span looks like an error.
    Heuristic only — same shape as the classifier uses to label a
    trajectory ``bad``.
    """
    for m in span:
        if m.get("role") != "tool":
            continue
        content = m.get("content") or ""
        if not isinstance(content, str):
            content = str(content)
        if any(hint in content for hint in _ERROR_HINTS):
            return True
    return False


def _span_has_malformed_tool_call(span: list[dict[str, Any]]) -> bool:
    """True if any assistant tool call has arguments that don't parse as
    JSON. The model emitting non-JSON args is a real failure mode for
    smaller local models and worth distinguishing from semantic mistakes.
    """
    for m in span:
        if m.get("role") != "assistant":
            continue
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function") or {}
            args = fn.get("arguments")
            if isinstance(args, dict):
                continue  # already structured — caller will JSON-serialize
            if not isinstance(args, str):
                return True
            try:
                json.loads(args)
            except (json.JSONDecodeError, ValueError):
                return True
    return False


def _classify_failure_mode(
    rejected_span: list[dict[str, Any]],
    chosen_span: list[dict[str, Any]],
) -> str:
    """Tag the rejected branch with a coarse failure-mode label by
    comparing it to the chosen branch.

    Priority order (first match wins): ``format_error`` > ``tool_error``
    > ``wrong_tool`` > ``bad_args`` > ``missing_tool`` > ``extra_tool``
    > ``truncated`` > ``other``. The ordering reflects how diagnostic
    each signal is — a malformed tool call is unambiguous; a length
    difference alone is weak.

    The tag is metadata only — it does not affect training, just lets
    you slice the dataset and ask "did DPO actually help on wrong_tool
    pairs?" after the fact.
    """
    if _span_has_malformed_tool_call(rejected_span):
        return "format_error"
    if _span_has_tool_error(rejected_span):
        return "tool_error"

    rej_calls = _extract_tool_calls(rejected_span)
    cho_calls = _extract_tool_calls(chosen_span)

    if rej_calls and cho_calls:
        # Compare the first divergent call. Walking in order rather than
        # by set semantics so a reordering doesn't get mis-tagged as
        # "wrong tool" — it'd show up as a position-1 mismatch which is
        # genuinely a wrong tool from the model's perspective.
        for (r_name, r_args), (c_name, c_args) in zip(rej_calls, cho_calls):
            if r_name != c_name:
                return "wrong_tool"
            if r_args != c_args:
                return "bad_args"
        # All compared calls match; one branch made more calls. The
        # branch with more is the more thorough one — usually chosen.
        if len(cho_calls) > len(rej_calls):
            return "missing_tool"
        if len(rej_calls) > len(cho_calls):
            return "extra_tool"
    elif not rej_calls and cho_calls:
        return "missing_tool"
    elif rej_calls and not cho_calls:
        return "extra_tool"

    # No tool-call disagreement. Fall back to a length heuristic — a
    # branch that's substantially shorter than the other usually means
    # the model gave up or got truncated. 4x is conservative; tune later
    # if real data shows a different threshold.
    rej_len = sum(len(m.get("content") or "") for m in rejected_span)
    cho_len = sum(len(m.get("content") or "") for m in chosen_span)
    if rej_len > 0 and cho_len >= 4 * max(rej_len, 1):
        return "truncated"

    return "other"


def _trajectory_to_messages(
    t: Trajectory,
    chat_template: str,  # noqa: ARG001 — reserved for future templates
) -> list[dict[str, Any]]:
    """Normalize a trajectory's turns into a clean role-tagged message list."""
    out: list[dict[str, Any]] = []
    for m in t.turns:
        role = m.get("role")
        if role == "user":
            content = m.get("content") or ""
            if isinstance(content, str) and content.startswith("[/steer]"):
                # Promote /steer into a regular user instruction so the
                # trained model sees the redirect as a normal prompt.
                content = content.replace("[/steer]", "", 1).strip()
            out.append({"role": "user", "content": content})
        elif role == "assistant":
            content = m.get("content") or ""
            tool_calls = m.get("tool_calls") or []
            normalized: dict[str, Any] = {"role": "assistant", "content": content}
            if tool_calls:
                normalized["tool_calls"] = [_normalize_tool_call(tc) for tc in tool_calls]
            out.append(normalized)
        elif role == "tool":
            entry: dict[str, Any] = {
                "role": "tool",
                "content": m.get("content") or "",
            }
            if "name" in m:
                entry["name"] = m["name"]
            if "tool_call_id" in m:
                entry["tool_call_id"] = m["tool_call_id"]
            out.append(entry)
        # Other roles (system, etc.) inside a trajectory are unexpected;
        # drop them rather than leak partial metadata.
    return out


def _normalize_tool_call(tc: dict[str, Any]) -> dict[str, Any]:
    """Coerce a tool_call entry into the canonical ``{function: {name, arguments}}``
    shape with arguments as a JSON string (qwen-coder convention)."""
    fn = tc.get("function") or {}
    args = fn.get("arguments")
    if isinstance(args, dict):
        args = json.dumps(args, sort_keys=True)
    elif args is None:
        args = "{}"
    return {"function": {"name": fn.get("name", ""), "arguments": args}}


def _trajectory_prompt(t: Trajectory) -> str:
    """Concatenate user turns in the trajectory into a single prompt string."""
    parts: list[str] = []
    for m in t.turns:
        if m.get("role") != "user":
            continue
        content = m.get("content") or ""
        if isinstance(content, str) and content.startswith("[/steer]"):
            content = content.replace("[/steer]", "", 1).strip()
        if content:
            parts.append(content)
    return "\n\n".join(parts)


def _trajectory_response(t: Trajectory) -> str:
    """Concatenate every assistant turn (and its tool calls) into one
    candidate response string. Used by the DPO formatter so the model
    sees the whole branch as one alternative."""
    parts: list[str] = []
    for m in t.turns:
        if m.get("role") != "assistant":
            continue
        content = m.get("content") or ""
        if content:
            parts.append(content)
        for tc in m.get("tool_calls") or []:
            parts.append(
                "<tool_call>"
                + json.dumps(_normalize_tool_call(tc), sort_keys=True)
                + "</tool_call>"
            )
    return "\n".join(parts)
