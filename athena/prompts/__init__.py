"""System prompt assembly for athena.

Mirrors the sectioned structure of Claude Code's system prompt, adapted for
local Ollama models. Keep sections small and named so they can be A/B'd
independently.
"""

from .system import build_system_prompt

__all__ = ["build_system_prompt"]
