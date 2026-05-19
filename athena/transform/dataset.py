"""SFT and DPO dataset construction.

Two outputs share the same JSONL-on-disk format (one JSON object per line)
but different per-example shapes:

- **SFT** — ``{"messages": [...], "metadata": {...}}``. The OpenAI
  fine-tuning format; ``trl.SFTTrainer`` accepts this directly.
- **DPO** — ``{"prompt": str, "chosen": str, "rejected": str,
  "metadata": {...}}``. ``trl.DPOTrainer`` accepts this directly.

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


def write_jsonl(path: Path, examples: list[dict[str, Any]]) -> None:
    """Write ``examples`` to ``path``, one JSON object per line. Creates
    parent directories. Overwrites any existing file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for ex in examples:
            f.write(json.dumps(ex, sort_keys=True) + "\n")


# ---- Internals ----------------------------------------------------------


def _is_good(t: Trajectory, *, include_auto_labels: bool) -> bool:
    if t.user_label == "good":
        return True
    if include_auto_labels and t.user_label == "unreviewed" and t.auto_label == "good":
        return True
    return False


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
