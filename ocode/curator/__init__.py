"""Curator: the 7-day umbrella consolidation pass.

The curator runs as a background fork at session start when both gates pass
(``interval_hours`` since the last run AND ``min_idle_hours`` since the
last session ended). It walks the skill library, decides KEEP_AS_IS /
CONSOLIDATE_INTO / CREATE_UMBRELLA / PRUNE for each, and emits a
structured YAML report. State and reports live under ``~/.ocode/skills/``
and ``~/.ocode/logs/curator/`` respectively.
"""
