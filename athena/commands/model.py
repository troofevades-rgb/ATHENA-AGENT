"""``/model [NAME|N]`` -- show the picker, switch by name, or switch by
picker index.

Three behaviors driven by ``arg``:

  * Empty -- render the picker. Numbered list of available models
    grouped by provider (Ollama local + OpenRouter if a credential
    is configured). The active model is marked with ``*``.
    Operators then run ``/model N`` (pick a number) or
    ``/model NAME`` to switch.
  * Numeric -- index into the last-rendered picker. Resolves to
    ``provider/model`` (or bare ``model`` for Ollama) and switches.
  * Anything else -- treat as a model name. Routes through
    ``resolve_provider`` so the right backend is built, matching
    the pre-picker behavior.

Inspired by Claude Code's ``/model`` picker UX. Differs in two
ways athena leans into:

  * Multi-provider: shows local Ollama AND remote OpenRouter in
    one list so operators see the full surface without bouncing
    between commands.
  * Live OpenRouter catalog: 354+ models pulled from
    ``/api/v1/models``. Cached in-process so the picker doesn't
    re-fetch on every redraw.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from .. import ui
from ..providers.credential_pool import global_pool as _global_pool
from ..providers.runtime_resolver import _route, resolve_provider
from . import command

logger = logging.getLogger(__name__)

# Cache TTL for the OpenRouter catalog. The endpoint returns the same
# data many times per session; 10 min is short enough to pick up new
# model releases without re-fetching on every ``/model`` redraw.
_OPENROUTER_CATALOG_TTL_S = 600


@dataclass
class PickerEntry:
    """One row in the picker. ``label`` is what the user types into
    ``/model`` to select this entry (either the prefixed form for
    routing or the bare Ollama tag)."""

    provider: str
    label: str
    note: str = ""


# Module-level state: the last-rendered picker entries (so ``/model N``
# can map a number back to a label) and the OpenRouter catalog cache.
_LAST_PICKER: list[PickerEntry] = []
_OPENROUTER_CACHE: tuple[float, list[str]] | None = None


def _ollama_models(agent: Any) -> list[str]:
    """Return Ollama's locally-pulled tags, or ``[]`` if the daemon
    is unreachable. Never raises -- the picker degrades gracefully
    when one provider is down.

    Resolution order:

      1. Reuse the agent's live provider when it IS ollama AND the
         call succeeds -- avoids opening a second httpx client.
      2. Construct a fresh ``OllamaProvider()`` and probe. Covers
         the case where the active provider is OpenRouter / Anthropic
         and we still want the local catalog. Also fallback when the
         live provider's call fails for some reason.
    """
    provider = getattr(agent, "provider", None)
    if provider is not None and getattr(provider, "name", "") == "ollama":
        try:
            return provider.list_models()
        except Exception as e:  # noqa: BLE001
            logger.debug("live ollama list_models failed, trying fresh: %s", e)
    try:
        from ..providers.ollama import OllamaProvider

        fresh = OllamaProvider()
        return fresh.list_models()
    except Exception as e:  # noqa: BLE001
        logger.debug("fresh ollama probe failed: %s", e)
        return []


def _openrouter_models() -> list[str]:
    """Fetch and cache the OpenRouter catalog. Returns ``[]`` when
    no credential is configured or the API is unreachable."""
    global _OPENROUTER_CACHE
    now = time.time()
    if _OPENROUTER_CACHE is not None:
        ts, models = _OPENROUTER_CACHE
        if now - ts < _OPENROUTER_CATALOG_TTL_S:
            return models

    try:
        cred = _global_pool().get("openrouter")
    except Exception:  # noqa: BLE001
        cred = None
    if cred is None or not cred.key:
        return []

    try:
        import httpx

        r = httpx.get(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": f"Bearer {cred.key}"},
            timeout=10.0,
        )
        if r.status_code != 200:
            logger.debug("openrouter /models -> %d", r.status_code)
            return []
        data = r.json().get("data", []) or []
        ids = [
            entry.get("id", "")
            for entry in data
            if isinstance(entry, dict) and entry.get("id")
        ]
        ids.sort()
        _OPENROUTER_CACHE = (now, ids)
        return ids
    except Exception as e:  # noqa: BLE001
        logger.debug("openrouter catalog fetch failed: %s", e)
        return []


def _build_picker(agent: Any) -> list[PickerEntry]:
    """Combine Ollama and OpenRouter into one ordered list. Ollama
    first (local, free), then OpenRouter (remote, billed). Updates
    the module-level cache so ``/model N`` can resolve."""
    global _LAST_PICKER
    entries: list[PickerEntry] = []
    for name in _ollama_models(agent):
        entries.append(PickerEntry(provider="ollama", label=name))
    for name in _openrouter_models():
        # The ``openrouter/`` prefix is what ``_route`` looks for to
        # dispatch to OpenRouterProvider. Bare names that contain a
        # ``/`` (vendor/model) without the prefix would route to
        # Ollama and fail.
        entries.append(
            PickerEntry(
                provider="openrouter",
                label=f"openrouter/{name}",
                note=name,
            )
        )
    _LAST_PICKER = entries
    return entries


def _render_picker(agent: Any) -> None:
    """Print the multi-provider picker to the operator. Groups by
    provider with a header, indexed 1..N (1-based so operators don't
    have to remember zero-indexing)."""
    entries = _build_picker(agent)
    if not entries:
        ui.error(
            "no models available. Is Ollama running? "
            "Add an OpenRouter key with: "
            "athena providers add-key openrouter --key sk-or-..."
        )
        return

    active = (agent.model or "").strip()

    def _is_active(entry: PickerEntry) -> bool:
        # Active match: bare model name equals entry.label, OR the
        # entry's OpenRouter ``note`` (bare name) matches.
        return active == entry.label or active == entry.note

    ui.console.print(f"[bold]models[/] (current: [cyan]{active or 'n/a'}[/])\n")
    last_provider = ""
    for i, entry in enumerate(entries, 1):
        if entry.provider != last_provider:
            label = {
                "ollama": "local (Ollama)",
                "openrouter": "OpenRouter",
            }.get(entry.provider, entry.provider)
            ui.console.print(f"\n[dim]── {label} ──[/]")
            last_provider = entry.provider
        marker = "[green]*[/]" if _is_active(entry) else " "
        display = entry.label
        if entry.provider == "openrouter":
            # Trim the redundant ``openrouter/`` prefix for visual
            # density -- the operator already sees the section header.
            display = entry.note or entry.label
        ui.console.print(f"  {marker} [dim]{i:>3}[/]  {display}")

    ui.console.print(
        "\nswitch with: [bold]/model N[/] (pick a number) or "
        "[bold]/model NAME[/]"
    )


def _resolve_picker_index(arg: str) -> str | None:
    """Map a numeric ``arg`` back to the entry from the last
    ``_render_picker`` call. Returns the routable label or
    ``None`` when ``arg`` isn't a number / is out of range."""
    if not arg.isdigit():
        return None
    n = int(arg)
    if not _LAST_PICKER:
        return None
    if n < 1 or n > len(_LAST_PICKER):
        return None
    return _LAST_PICKER[n - 1].label


def _switch_model(agent: Any, new_name: str) -> None:
    """The actual switch path -- shared by the name-arg and
    picker-index branches. Rebuilds the provider when the new name
    routes elsewhere."""
    current_provider_name = getattr(agent.provider, "name", "")
    new_provider_name = _route(new_name, agent.cfg)
    if new_provider_name != current_provider_name:
        try:
            new_provider, bare_model = resolve_provider(
                new_name, agent.cfg, _global_pool()
            )
        except Exception as e:  # noqa: BLE001
            ui.error(f"could not switch to {new_name}: {e}")
            return
        if getattr(agent, "_owns_client", False):
            try:
                agent.provider.close()
            except Exception:  # noqa: BLE001
                pass
        agent.provider = new_provider
        agent.client = new_provider  # back-compat alias
        agent._owns_client = True
        agent.model = bare_model
        ui.info(
            f"model set to {new_name} "
            f"(provider: {current_provider_name} -> {new_provider_name})"
        )
        return
    agent.model = new_name
    ui.info(f"model set to {agent.model}")


@command("model")
def cmd_model(agent, arg: str = "") -> str:
    arg = (arg or "").strip()
    if not arg:
        _render_picker(agent)
        return ""

    # Picker index: ``/model 7`` resolves against the last-rendered
    # list. Numeric model names (an Ollama tag like ``42``) still
    # work via the explicit ``/model NAME`` path -- the picker
    # branch only fires when the number actually maps.
    if arg.isdigit():
        resolved = _resolve_picker_index(arg)
        if resolved is None:
            if not _LAST_PICKER:
                ui.error(
                    f"no picker rendered yet -- run /model first, "
                    f"then /model {arg}"
                )
                return ""
            ui.error(
                f"picker index {arg} out of range (1..{len(_LAST_PICKER)})"
            )
            return ""
        _switch_model(agent, resolved)
        return ""

    _switch_model(agent, arg)
    return ""
