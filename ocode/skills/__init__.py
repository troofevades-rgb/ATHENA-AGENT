"""ocode v2 file-based skill format.

Skills are folders under ``~/.ocode/skills/`` and ``<workspace>/.ocode/skills/``.
Each folder contains a ``SKILL.md`` with YAML frontmatter (agentskills.io
standard plus ocode v2 lifecycle fields), and optional ``references/``,
``templates/``, and ``scripts/`` subdirectories.

See ``ocode/skills/frontmatter.py`` for the SkillFrontmatter dataclass and
parse/serialize functions.
"""
