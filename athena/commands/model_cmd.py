"""``/model [NAME]`` — show or switch the active model.

When the new name routes to a different provider, the agent's
``provider`` is rebuilt via ``resolve_provider`` so the next chat
hits the right backend. Otherwise just the model name is swapped.
"""

from __future__ import annotations

from .. import ui
from ..providers.credential_pool import global_pool as _global_pool
from ..providers.runtime_resolver import _route, resolve_provider
from . import command


@command("model")
def cmd_model(agent, arg: str = "") -> str:
    if not arg:
        ui.info(f"current model: {agent.model}")
        return ""
    new_name = arg.strip()

    current_provider_name = getattr(agent.provider, "name", "")
    new_provider_name = _route(new_name, agent.cfg)
    if new_provider_name != current_provider_name:
        try:
            new_provider, bare_model = resolve_provider(new_name, agent.cfg, _global_pool())
        except Exception as e:
            ui.error(f"could not switch to {new_name}: {e}")
            return ""
        if getattr(agent, "_owns_client", False):
            try:
                agent.provider.close()
            except Exception:
                pass
        agent.provider = new_provider
        agent.client = new_provider  # back-compat alias
        agent._owns_client = True
        agent.model = bare_model
        ui.info(
            f"model set to {new_name} (provider: {current_provider_name} -> {new_provider_name})"
        )
        return ""
    agent.model = new_name
    ui.info(f"model set to {agent.model}")
    return ""
