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
from typing import Any, cast

from .. import ui
from ..providers.credential_pool import global_pool as _global_pool
from ..providers.runtime_resolver import _bare_model, _route, resolve_provider
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
    routing or the bare Ollama tag). ``supports_tools`` is False for
    OpenRouter models whose ``/api/v1/models`` ``supported_parameters``
    lacks ``"tools"`` -- these models will 404 every agent turn since
    every athena turn ships tool schemas."""

    provider: str
    label: str
    note: str = ""
    supports_tools: bool = True


# Module-level state: the last-rendered picker entries (so ``/model N``
# can map a number back to a label) and the OpenRouter catalog cache.
# Cache shape: ``(fetched_at_unix, {model_id: supports_tools})``.
_LAST_PICKER: list[PickerEntry] = []
_OPENROUTER_CACHE: tuple[float, dict[str, bool]] | None = None


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
            return cast("list[str]", provider.list_models())
        except Exception as e:  # noqa: BLE001
            logger.debug("live ollama list_models failed, trying fresh: %s", e)
    try:
        from ..providers.ollama import OllamaProvider

        fresh = OllamaProvider()
        return fresh.list_models()
    except Exception as e:  # noqa: BLE001
        logger.debug("fresh ollama probe failed: %s", e)
        return []


def _openrouter_models() -> dict[str, bool]:
    """Fetch and cache the OpenRouter catalog as ``{model_id:
    supports_tools}``.

    ``supports_tools`` reads OpenRouter's ``/api/v1/models``
    ``supported_parameters`` array -- a model is tool-capable when
    that array contains ``"tools"``. The agent ships tool schemas on
    every turn, so a non-tool model 404s the moment the user sends a
    prompt. Surfacing this at the picker (and warning at the switch)
    catches the mismatch before it bites.

    Returns an empty dict when no credential is configured or the
    API is unreachable -- callers degrade gracefully (the picker
    still shows local Ollama models).
    """
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
        return {}

    try:
        import httpx

        r = httpx.get(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": f"Bearer {cred.key}"},
            timeout=10.0,
        )
        if r.status_code != 200:
            logger.debug("openrouter /models -> %d", r.status_code)
            return {}
        data = r.json().get("data", []) or []
        models = {}
        for entry in data:
            if not isinstance(entry, dict):
                continue
            model_id = entry.get("id", "")
            if not model_id:
                continue
            params = entry.get("supported_parameters") or []
            supports_tools = isinstance(params, list) and "tools" in params
            models[model_id] = supports_tools
        _OPENROUTER_CACHE = (now, models)
        return models
    except Exception as e:  # noqa: BLE001
        logger.debug("openrouter catalog fetch failed: %s", e)
        return {}


def _openrouter_model_supports_tools(bare_model: str) -> bool | None:
    """Return whether ``bare_model`` (e.g.
    ``nousresearch/hermes-4-405b``, without the ``openrouter/``
    routing prefix) supports tool calling. ``None`` when the catalog
    hasn't been fetched / the model isn't in it -- callers treat
    None as "don't know, assume yes" so an unknown model doesn't
    spam warnings."""
    cached = _OPENROUTER_CACHE
    if cached is None:
        return None
    _ts, models = cached
    return models.get(bare_model)


def _build_picker(agent: Any) -> list[PickerEntry]:
    """Combine Ollama and OpenRouter into one ordered list. Ollama
    first (local, free), then OpenRouter (remote, billed). Updates
    the module-level cache so ``/model N`` can resolve.

    OpenRouter entries carry ``supports_tools`` so the picker can
    flag models that won't work for the agent (every athena turn
    ships tool schemas; a no-tools model 404s on the first prompt)."""
    global _LAST_PICKER
    entries: list[PickerEntry] = []
    for name in _ollama_models(agent):
        # Ollama models -- assume tools (Ollama's tool-calling
        # support is per-model but we can't probe it cheaply;
        # operators figure out fast which local models tool-call).
        entries.append(PickerEntry(provider="ollama", label=name))
    or_catalog = _openrouter_models()
    for name in sorted(or_catalog.keys()):
        # The ``openrouter/`` prefix is what ``_route`` looks for to
        # dispatch to OpenRouterProvider. Bare names that contain a
        # ``/`` (vendor/model) without the prefix would route to
        # Ollama and fail.
        entries.append(
            PickerEntry(
                provider="openrouter",
                label=f"openrouter/{name}",
                note=name,
                supports_tools=or_catalog[name],
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
        # Tool-capability marker: only flag the negative case (no
        # tools) so the operator's eye catches it. The agent ships
        # tool schemas every turn; picking a no-tools model is a
        # dead-end in practice.
        tools_marker = " [dim red][no-tools][/]" if not entry.supports_tools else ""
        ui.console.print(f"  {marker} [dim]{i:>3}[/]  {display}{tools_marker}")

    ui.console.print("\nswitch with: [bold]/model N[/] (pick a number) or [bold]/model NAME[/]")
    ui.console.print(
        "[dim red][no-tools][/] [dim]entries can't run agent "
        "turns -- they 404 on every tool-schema request[/]"
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


_KNOWN_PROVIDER_PREFIXES: tuple[str, ...] = (
    "anthropic",
    "codex",
    "openai",
    "google",
    "openrouter",
    "nous",
    "xai",
)


def _typo_suggestion(name: str) -> str | None:
    """Detect ``<prefix>/<rest>`` where ``<prefix>`` is a near-miss
    of a known provider routing prefix and return a suggestion
    string. ``None`` means "no typo detected; let the regular router
    handle this" -- which preserves the legitimate
    ``vendor/model`` ollama tag form (``mistralai/mistral-7b``)
    that doesn't resemble any provider name.

    Surfaced via ``_switch_model`` so the operator gets a clear
    "did you mean X?" instead of a 404 cascade on every subsequent
    turn (the dogfood that surfaced this: ``/model
    athropic/claude-opus-4-7`` silently fell through to ollama and
    burned 174 goal-loop turns hammering Ollama with the typo'd
    model name)."""
    import difflib

    if "/" not in name:
        return None
    prefix = name.split("/", 1)[0]
    # Already a known provider — _route handles it; not a typo.
    if prefix in _KNOWN_PROVIDER_PREFIXES:
        return None
    # Skip prefixes that aren't plausible provider names (host:port,
    # http(s):// URL components, or anything with non-letters). Those
    # are legitimate Ollama / openai_compat tag forms.
    if not prefix.isalpha():
        return None
    # The cutoff is intentionally aggressive (0.75). At that
    # threshold, ``athropic`` -> ``anthropic`` (one deletion, 9 vs
    # 8 chars) matches at ~0.94 ratio, ``opena`` -> ``openai``
    # matches, and unrelated vendor names like ``mistralai`` or
    # ``qwen`` correctly score below cutoff and pass through.
    matches = difflib.get_close_matches(
        prefix.lower(),
        _KNOWN_PROVIDER_PREFIXES,
        n=1,
        cutoff=0.75,
    )
    if not matches:
        return None
    rest = name.split("/", 1)[1]
    return f"unknown provider prefix '{prefix}/'. Did you mean '{matches[0]}/{rest}'?"


def _switch_model(agent: Any, new_name: str) -> None:
    """The actual switch path -- shared by the name-arg and
    picker-index branches. Rebuilds the provider when the new name
    routes elsewhere. Warns when switching to an OpenRouter model
    whose catalog entry doesn't list ``tools`` in
    ``supported_parameters`` -- such a model 404s on every athena
    turn (we ship tool schemas unconditionally)."""
    # Strip a leading slash that snuck in from a paste / typo.
    # Surfaced when an operator typed ``/model /troofevades-q35:athena``
    # and Ollama rejected the request with HTTP 400 "invalid model
    # name" (Ollama does not accept slash-prefixed names). A leading
    # slash never has a valid provider-routing meaning -- every
    # known prefix is ``<letters>/``, never starts with ``/`` --
    # so this strip is safe.
    new_name = new_name.lstrip("/")
    if not new_name:
        ui.error("model name is empty after stripping the leading slash")
        return
    typo = _typo_suggestion(new_name)
    if typo is not None:
        ui.error(typo)
        return
    current_provider_name = getattr(agent.provider, "name", "")
    new_provider_name = _route(new_name, agent.cfg)
    if new_provider_name != current_provider_name:
        try:
            new_provider, bare_model = resolve_provider(new_name, agent.cfg, _global_pool())
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
            f"model set to {new_name} (provider: {current_provider_name} -> {new_provider_name})"
        )
        _warn_if_openrouter_no_tools(new_provider_name, bare_model)
        return
    # Same-provider switch -- still strip the routing prefix so
    # ``agent.model`` doesn't carry it onto the wire. Without this,
    # ``/model anthropic/A`` -> ``/model anthropic/B`` sends
    # ``anthropic/B`` to the API and Anthropic 404s on the prefix.
    bare = _bare_model(new_provider_name, new_name)
    agent.model = bare
    ui.info(f"model set to {agent.model}")
    _warn_if_openrouter_no_tools(new_provider_name, agent.model)


def _warn_if_openrouter_no_tools(provider_name: str, bare_model: str) -> None:
    """Emit a clear warning when the operator switched to an
    OpenRouter model that won't tool-call. Best-effort -- a None
    answer (catalog not fetched yet) is silently OK so a fresh
    session that switches directly via ``/model NAME`` doesn't
    spam an unjustified warning."""
    if provider_name != "openrouter":
        return
    supports = _openrouter_model_supports_tools(bare_model)
    if supports is False:
        ui.warn(
            f"{bare_model} does NOT advertise tool-calling support on "
            "OpenRouter. The agent ships tool schemas every turn, so "
            "your next prompt will 404. Pick a model whose "
            "/api/v1/models supported_parameters includes 'tools' "
            "(e.g. anthropic/claude-sonnet-4.6, openai/gpt-4o, "
            "meta-llama/llama-3.3-70b-instruct)."
        )


@command("model")
def cmd_model(agent: Any, arg: str = "") -> str:
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
                ui.error(f"no picker rendered yet -- run /model first, then /model {arg}")
                return ""
            ui.error(f"picker index {arg} out of range (1..{len(_LAST_PICKER)})")
            return ""
        _switch_model(agent, resolved)
        return ""

    _switch_model(agent, arg)
    return ""
