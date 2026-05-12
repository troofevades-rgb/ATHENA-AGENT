"""Agent package: the core loop and the fork() primitive.

Split from the original flat ``ocode/agent.py``. ``core`` holds the ``Agent``
class; ``fork`` holds the daemon-thread sub-agent primitive used by sub-agent
dispatch, background review (Phase 5), and the curator (Phase 6).
"""
from . import fork as _fork_module  # noqa: F401 — keep submodule importable as ocode.agent.fork
from .core import Agent, get_current_agent
from .fork import ForkResult

__all__ = ["Agent", "ForkResult", "get_current_agent"]
