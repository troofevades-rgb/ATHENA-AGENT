"""Pre-activation lint for skill bodies.

A skill that ships syntactically broken Python is noise — it pollutes
the catalog and tricks future selves into thinking a problem is solved.
When a skill body contains Python code fences, verify they parse with
``ast.parse`` before the skill is created or patched.

Only Python is checked. Bash/shell grammars are too lenient to parse
sensibly outside an actual shell; non-code prose is freeform.

The check is intentionally narrow: it answers "would Python's parser
accept this?" — not "is this code correct." A skill body that parses
but does the wrong thing is the model's problem; a skill body that
doesn't parse is athena's.
"""

from __future__ import annotations

import ast
import re

# Matches a fenced block whose info string is "python" or "py".
# DOTALL so newlines inside the body match the .*?
_PYTHON_FENCE_RX = re.compile(
    r"```(?:python|py)[^\n]*\n(.*?)```",
    re.DOTALL,
)


def verify_body(body: str) -> tuple[bool, str]:
    """Verify that every ```python fenced block in ``body`` parses.

    Returns ``(ok, message)``. When ``ok`` is False, the message names
    the failing block and the parse error in a form the model can act
    on. When there are no Python blocks, returns ``(True, "")``.
    """
    if not body:
        return True, ""
    blocks = _PYTHON_FENCE_RX.findall(body)
    if not blocks:
        return True, ""
    for i, code in enumerate(blocks, 1):
        try:
            ast.parse(code)
        except SyntaxError as e:
            lineno = e.lineno or 1
            lines = code.splitlines()
            preview = lines[lineno - 1].strip() if 0 < lineno <= len(lines) else "?"
            return False, (
                f"Python block #{i} in the skill body has a SyntaxError "
                f"on line {lineno}: {e.msg}.\n"
                f"  > {preview}\n"
                f"Fix the syntax before activating this skill — a broken "
                f"code block in a skill is worse than no skill at all."
            )
    return True, ""
