"""Structured-output capability bucket.

The model must emit valid JSON / a parseable markdown table / a
specific structured shape. Verification parses the output (either
from the assistant's final message or from a file the agent was
asked to write) and checks structure + key values.

These tasks DO inspect ``assistant_text`` — different from the
file_ops/shell buckets which only check disk state — because the
output shape IS the deliverable.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..task import EvalTask, VerifyContext

_BUCKET = "structured"


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _try_parse_json_in_text(text: str) -> Any:
    """Find the first JSON object/array embedded in free-form text
    and parse it. Returns None on failure. The model often wraps
    JSON in a code fence — strip those."""
    # Strip code-fence wrappers.
    fence_match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence_match:
        candidate = fence_match.group(1).strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    # Fall back: find the first { or [ and try to parse from there
    # by counting braces.
    for start_ch, end_ch in (("{", "}"), ("[", "]")):
        i = text.find(start_ch)
        if i == -1:
            continue
        depth = 0
        for j in range(i, len(text)):
            if text[j] == start_ch:
                depth += 1
            elif text[j] == end_ch:
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[i : j + 1])
                    except json.JSONDecodeError:
                        break
    return None


# ---------------------------------------------------------------------------
# 1. Emit JSON matching a schema (single object, three required keys)
# ---------------------------------------------------------------------------


def _verify_user_json(ctx: VerifyContext) -> bool:
    # Prefer a file the agent may have written; fall back to assistant
    # text. Either is acceptable.
    text = _read(ctx.workspace / "user.json") or ""
    if not text:
        # Find last assistant message in agent_messages.
        for m in reversed(ctx.agent_messages):
            if m.get("role") == "assistant":
                c = m.get("content")
                if isinstance(c, str):
                    text = c
                    break
    data = _try_parse_json_in_text(text)
    if not isinstance(data, dict):
        return False
    return (
        data.get("name") == "Ada"
        and data.get("age") == 35
        and data.get("role") == "engineer"
    )


_emit_user_json = EvalTask(
    id="structured.emit_user_json",
    prompt=(
        "Emit a JSON object describing a user with the following "
        "fields: name=Ada, age=35, role=engineer. You may write the "
        "JSON to a file called user.json OR include the JSON in your "
        "reply. The JSON must be valid (parseable)."
    ),
    setup_fn=lambda ws: None,
    verify_fn=_verify_user_json,
    bucket=_BUCKET,
    description="Emit a JSON object with three required fields.",
)


# ---------------------------------------------------------------------------
# 2. Convert CSV to a JSON array
# ---------------------------------------------------------------------------


def _setup_for_csv_to_json(ws: Path) -> None:
    (ws / "rows.csv").write_text(
        "name,score\n" "alice,90\n" "bob,85\n" "carol,77\n",
        encoding="utf-8",
    )


def _verify_csv_to_json(ctx: VerifyContext) -> bool:
    text = _read(ctx.workspace / "rows.json")
    if not text:
        return False
    data = _try_parse_json_in_text(text)
    if not isinstance(data, list) or len(data) != 3:
        return False
    by_name = {row.get("name"): row for row in data if isinstance(row, dict)}
    if set(by_name) != {"alice", "bob", "carol"}:
        return False
    # Scores may land as int or str — accept both.
    return all(
        str(by_name[name].get("score")) == score
        for name, score in (("alice", "90"), ("bob", "85"), ("carol", "77"))
    )


_csv_to_json = EvalTask(
    id="structured.csv_to_json",
    prompt=(
        "rows.csv in the current workspace has a header row (name,score) "
        "followed by three data rows. Convert it to a JSON array of "
        "objects (one object per row, with 'name' and 'score' keys) "
        "and write the JSON to rows.json. The file must be valid JSON."
    ),
    setup_fn=_setup_for_csv_to_json,
    verify_fn=_verify_csv_to_json,
    bucket=_BUCKET,
    description="CSV → JSON array conversion.",
)


# ---------------------------------------------------------------------------
# 3. Produce a markdown table from a list
# ---------------------------------------------------------------------------


def _verify_markdown_table(ctx: VerifyContext) -> bool:
    text = _read(ctx.workspace / "table.md")
    if not text:
        return False
    lines = [l for l in text.splitlines() if l.strip()]
    # Need at least header, separator, 3 data rows = 5 lines minimum.
    if len(lines) < 5:
        return False
    has_separator = any(
        re.fullmatch(r"\s*\|[\s\-:|]+\|\s*", l) for l in lines
    )
    has_data = all(name in text for name in ("apple", "banana", "cherry"))
    has_columns = "|" in lines[0] and ("Fruit" in lines[0] or "fruit" in lines[0])
    return has_separator and has_data and has_columns


_markdown_table = EvalTask(
    id="structured.markdown_table",
    prompt=(
        "Create a markdown file called table.md in the current "
        "workspace containing a markdown table with two columns "
        "(Fruit | Count) and three rows: apple 5, banana 3, cherry 7. "
        "It must be a valid markdown table with a header separator "
        "row."
    ),
    setup_fn=lambda ws: None,
    verify_fn=_verify_markdown_table,
    bucket=_BUCKET,
    description="Markdown table with header + 3 data rows.",
)


# ---------------------------------------------------------------------------
# 4. Emit YAML (key-value list)
# ---------------------------------------------------------------------------


def _verify_yaml(ctx: VerifyContext) -> bool:
    text = _read(ctx.workspace / "config.yml")
    if not text:
        return False
    # Tolerant parse — don't require yaml package. Just check the
    # lines look right.
    has_host = re.search(r"^host:\s*localhost\s*$", text, re.MULTILINE)
    has_port = re.search(r"^port:\s*8080\s*$", text, re.MULTILINE)
    return bool(has_host and has_port)


_emit_yaml = EvalTask(
    id="structured.emit_yaml",
    prompt=(
        "Write a YAML file called config.yml in the current workspace "
        "containing exactly two top-level keys: host (value: localhost) "
        "and port (value: 8080)."
    ),
    setup_fn=lambda ws: None,
    verify_fn=_verify_yaml,
    bucket=_BUCKET,
    description="Emit YAML with two specific keys.",
)


# ---------------------------------------------------------------------------
# 5. Pretty-print existing minified JSON
# ---------------------------------------------------------------------------


def _setup_for_pretty(ws: Path) -> None:
    (ws / "min.json").write_text(
        '{"name":"Ada","items":[1,2,3]}', encoding="utf-8"
    )


def _verify_pretty(ctx: VerifyContext) -> bool:
    text = _read(ctx.workspace / "pretty.json")
    if not text:
        return False
    # Must still parse to the same value.
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return False
    if data != {"name": "Ada", "items": [1, 2, 3]}:
        return False
    # Pretty means at least one newline + an indented line.
    return "\n" in text and re.search(r"\n\s+\"", text) is not None


_pretty_print_json = EvalTask(
    id="structured.pretty_print_json",
    prompt=(
        "min.json in the current workspace is minified JSON. Write a "
        "pretty-printed version (with newlines and indentation) to "
        "pretty.json. The parsed value must remain identical."
    ),
    setup_fn=_setup_for_pretty,
    verify_fn=_verify_pretty,
    bucket=_BUCKET,
    description="Pretty-print minified JSON, preserving value.",
)


# ---------------------------------------------------------------------------
# 6. Build a nested JSON structure
# ---------------------------------------------------------------------------


def _verify_nested_json(ctx: VerifyContext) -> bool:
    text = _read(ctx.workspace / "nested.json")
    if not text:
        return False
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return False
    return (
        isinstance(data, dict)
        and isinstance(data.get("user"), dict)
        and data["user"].get("name") == "Ada"
        and isinstance(data["user"].get("preferences"), dict)
        and data["user"]["preferences"].get("theme") == "dark"
    )


_nested_json = EvalTask(
    id="structured.nested_json",
    prompt=(
        "Write a nested JSON object to nested.json in the current "
        "workspace with this shape: user.name = 'Ada', and "
        "user.preferences.theme = 'dark'. The file must be valid "
        "JSON."
    ),
    setup_fn=lambda ws: None,
    verify_fn=_verify_nested_json,
    bucket=_BUCKET,
    description="Two-level-nested JSON object.",
)


# ---------------------------------------------------------------------------
# 7. Convert a JSON array to CSV
# ---------------------------------------------------------------------------


def _setup_for_json_to_csv(ws: Path) -> None:
    data = [
        {"city": "NYC", "pop": 8},
        {"city": "LA", "pop": 4},
        {"city": "SF", "pop": 1},
    ]
    (ws / "cities.json").write_text(json.dumps(data), encoding="utf-8")


def _verify_json_to_csv(ctx: VerifyContext) -> bool:
    text = _read(ctx.workspace / "cities.csv")
    if not text:
        return False
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if len(lines) != 4:  # header + 3 rows
        return False
    header = lines[0].lower()
    return (
        "city" in header
        and "pop" in header
        and any("NYC" in l for l in lines[1:])
        and any("LA" in l for l in lines[1:])
        and any("SF" in l for l in lines[1:])
    )


_json_to_csv = EvalTask(
    id="structured.json_to_csv",
    prompt=(
        "cities.json contains a JSON array of objects with 'city' and "
        "'pop' fields. Convert it to a CSV file called cities.csv "
        "with a header row followed by one row per object."
    ),
    setup_fn=_setup_for_json_to_csv,
    verify_fn=_verify_json_to_csv,
    bucket=_BUCKET,
    description="JSON array → CSV with header.",
)


# ---------------------------------------------------------------------------
# 8. Extract a specific value from JSON
# ---------------------------------------------------------------------------


def _setup_for_extract(ws: Path) -> None:
    (ws / "input.json").write_text(
        '{"meta":{"id":"u-123","when":"2026-05-27"}, "items":[1,2,3]}',
        encoding="utf-8",
    )


def _verify_extract(ctx: VerifyContext) -> bool:
    text = _read(ctx.workspace / "id.txt").strip()
    return text == "u-123"


_extract_field = EvalTask(
    id="structured.extract_field",
    prompt=(
        "input.json contains a nested object. Extract the value at "
        "meta.id and write it (alone, no quotes) to id.txt in the "
        "current workspace."
    ),
    setup_fn=_setup_for_extract,
    verify_fn=_verify_extract,
    bucket=_BUCKET,
    description="Extract a deeply-nested JSON field by path.",
)


# ---------------------------------------------------------------------------
# 9. Build a TOML config
# ---------------------------------------------------------------------------


def _verify_toml(ctx: VerifyContext) -> bool:
    text = _read(ctx.workspace / "settings.toml")
    if not text:
        return False
    # Tolerant: look for the section header + the two keys.
    has_section = "[server]" in text
    has_host = re.search(r"^host\s*=\s*\"localhost\"", text, re.MULTILINE)
    has_port = re.search(r"^port\s*=\s*8080", text, re.MULTILINE)
    return has_section and bool(has_host) and bool(has_port)


_emit_toml = EvalTask(
    id="structured.emit_toml",
    prompt=(
        "Write a TOML file called settings.toml in the current "
        "workspace. It should contain a [server] section with two "
        "keys: host = \"localhost\" and port = 8080."
    ),
    setup_fn=lambda ws: None,
    verify_fn=_verify_toml,
    bucket=_BUCKET,
    description="Emit a TOML file with a section + two keys.",
)


# ---------------------------------------------------------------------------
# 10. Aggregate a CSV: emit summary JSON
# ---------------------------------------------------------------------------


def _setup_for_aggregate(ws: Path) -> None:
    (ws / "sales.csv").write_text(
        "product,amount\n"
        "apple,10\n"
        "banana,5\n"
        "apple,7\n"
        "banana,3\n",
        encoding="utf-8",
    )


def _verify_aggregate(ctx: VerifyContext) -> bool:
    text = _read(ctx.workspace / "totals.json")
    if not text:
        return False
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return False
    if not isinstance(data, dict):
        return False
    # Numbers may land as int or str — coerce.
    def _n(k):
        v = data.get(k)
        try:
            return int(v) if v is not None else None
        except (TypeError, ValueError):
            try:
                return int(float(v))
            except (TypeError, ValueError):
                return None
    return _n("apple") == 17 and _n("banana") == 8


_aggregate_csv = EvalTask(
    id="structured.aggregate_csv",
    prompt=(
        "sales.csv has columns product, amount. Compute the total "
        "amount per product (sum of all rows for each product) and "
        "write the result to totals.json as a JSON object mapping "
        "product name to total."
    ),
    setup_fn=_setup_for_aggregate,
    verify_fn=_verify_aggregate,
    bucket=_BUCKET,
    description="Aggregate a CSV by key, emit JSON totals.",
)


TASKS: list[EvalTask] = [
    _emit_user_json,
    _csv_to_json,
    _markdown_table,
    _emit_yaml,
    _pretty_print_json,
    _nested_json,
    _json_to_csv,
    _extract_field,
    _emit_toml,
    _aggregate_csv,
]

__all__ = ["TASKS"]
