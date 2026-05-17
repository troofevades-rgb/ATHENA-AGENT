"""/init — generate an ATHENA.md by surveying the workspace.

Asks the model to write ATHENA.md based on what it finds in the project.
"""
from __future__ import annotations

from . import command


_PROMPT = """\
Initialize this project with an ATHENA.md file. Survey the codebase using \
Read, Glob, Grep, and Bash (e.g. `ls`, `git log --oneline -20`). Write a \
concise ATHENA.md (under 80 lines) that includes:

- Project name and one-line description
- Stack (language, framework, key libraries)
- Build / test / run commands
- Repo layout (top-level dirs and what they contain)
- Any non-obvious conventions or gotchas you found

Use the Write tool to create ATHENA.md at the workspace root. Don't include \
license boilerplate. Don't speculate — only document what you can verify by \
reading the code. After writing it, summarize what you put in it.
"""


@command("init")
def cmd_init(agent, arg: str = "") -> str:
    return _PROMPT
