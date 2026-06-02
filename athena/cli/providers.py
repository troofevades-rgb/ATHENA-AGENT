"""``athena providers {list,test,add-key,remove-key}``.

Talks to the same credential pool the agent uses. Credentials are
profile-scoped (``<profile_dir>/credentials.json``): with no
``--profile`` the active profile is used, so ``add-key`` lands the key
where the agent running that profile will read it. ``list`` is a
redacted summary; ``test`` issues a tiny completion request against each
configured hosted provider (and a cheap reachability check against
ollama); ``add-key`` / ``remove-key`` mutate the pool.

Tests pass their own pool file via ``--pool-path`` for isolation.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..config import load_config
from ..providers import list_providers
from ..providers.credential_pool import Credential, CredentialPool, profile_pool


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="athena providers")
    ap.add_argument(
        "--profile",
        default=None,
        help="Target this profile's credentials (default: the active profile).",
    )
    ap.add_argument(
        "--pool-path",
        type=Path,
        default=None,
        help="Override the credential-pool file directly (mainly for tests); "
        "takes precedence over --profile.",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="Show configured providers and credential counts.")

    p_test = sub.add_parser(
        "test",
        help="Ping each provider with a tiny completion request.",
    )
    p_test.add_argument("--provider", default=None, help="Limit the test to one provider name.")
    p_test.add_argument(
        "--model",
        default=None,
        help="Probe this specific model instead of the "
        "built-in sample. Useful when the bundled sample "
        "is stale (provider retired the model).",
    )

    p_add = sub.add_parser("add-key", help="Add a credential for a provider.")
    p_add.add_argument("provider")
    p_add.add_argument("key")
    p_add.add_argument(
        "--label", default="", help="Optional human-readable label (e.g. 'personal')."
    )

    p_rm = sub.add_parser(
        "remove-key",
        help="Remove a credential by exact key, unambiguous prefix, "
        "or suffix (the form `athena providers list` displays — "
        "the leading '...' is optional).",
    )
    p_rm.add_argument("provider")
    p_rm.add_argument(
        "key_or_match", help="Exact key, prefix, or suffix (e.g. 'ttWN' or '...ttWN')."
    )

    p_models = sub.add_parser(
        "models",
        help="List models the configured key has access to on a provider.",
    )
    p_models.add_argument("provider")
    p_models.add_argument(
        "--limit", type=int, default=0, help="Truncate the list to N entries (0 = unlimited)."
    )

    p_caps = sub.add_parser(
        "capabilities",
        help="Show the capability matrix for every registered provider (T5-01R).",
        aliases=["caps"],
    )
    p_caps.add_argument(
        "--json",
        dest="json_out",
        action="store_true",
        help="Machine-readable output.",
    )

    return ap


# ---- capabilities ------------------------------------------------------


def _cmd_capabilities(args) -> int:
    """``athena providers capabilities`` — render the capability matrix."""
    import dataclasses as _dc
    import json as _json

    from ..providers import capability_matrix

    matrix = capability_matrix()
    if args.json_out:
        payload = {name: _dc.asdict(caps) for name, caps in matrix.items()}
        sys.stdout.write(_json.dumps(payload, indent=2, default=str) + "\n")
        return 0

    # Pick a stable column order. tool_calls / streaming first
    # because they're the load-bearing existing surface.
    columns = [
        "tool_calls",
        "streaming",
        "vision",
        "prompt_caching",
        "kv_cache_reuse",
        "structured_output",
        "embeddings",
        "is_local",
    ]
    header = ["provider"] + columns + ["native_format", "max_context_tokens"]
    rows: list[list[str]] = []
    for name in sorted(matrix):
        caps = matrix[name]
        row = [name]
        for col in columns:
            row.append("✓" if getattr(caps, col) else "·")
        row.append(caps.native_format)
        ctx = caps.max_context_tokens
        row.append(f"{ctx:,}" if ctx else "·")
        rows.append(row)

    widths = [max(len(h), max(len(r[i]) for r in rows)) for i, h in enumerate(header)]
    sys.stdout.write("  ".join(h.ljust(widths[i]) for i, h in enumerate(header)) + "\n")
    sys.stdout.write("  ".join("-" * w for w in widths) + "\n")
    for row in rows:
        sys.stdout.write("  ".join(c.ljust(widths[i]) for i, c in enumerate(row)) + "\n")
    return 0


def _open_pool(args) -> CredentialPool:
    # Explicit file override wins (test isolation). Otherwise resolve
    # the profile and hand back its scoped pool — so `athena providers
    # add-key` writes where the agent running that profile reads.
    if args.pool_path:
        return CredentialPool(args.pool_path)
    from ..profiles.resolution import resolve_active_profile

    profile = resolve_active_profile(
        getattr(args, "profile", None),
        config_default=load_config().profile,
    )
    return profile_pool(profile)


# ---- list ---------------------------------------------------------------


def _cmd_list(args) -> int:
    pool = _open_pool(args)
    registered = set(list_providers())
    with_creds = pool.list_credentials()
    for name in sorted(registered):
        bucket = with_creds.get(name, [])
        in_cooldown = sum(1 for c in bucket if c.get("in_cooldown"))
        cooldown_note = f" ({in_cooldown} in cooldown)" if in_cooldown else ""
        suffixes = ", ".join(c["key_suffix"] for c in bucket) or "-"
        print(f"  {name:<14} {len(bucket)} key(s){cooldown_note}   {suffixes}")
    extra = sorted(set(with_creds) - registered)
    for name in extra:
        # Pool has credentials for an unregistered provider — surface it
        # so the user knows they have orphan keys.
        bucket = with_creds[name]
        print(f"  {name:<14} {len(bucket)} key(s)   (unregistered provider — orphan keys)")
    return 0


# ---- add-key / remove-key ----------------------------------------------


def _cmd_add_key(args) -> int:
    registered = set(list_providers())
    if args.provider not in registered:
        print(
            f"warning: {args.provider!r} is not a registered provider. "
            f"Known: {', '.join(sorted(registered))}",
            file=sys.stderr,
        )
        # Don't refuse — user may be adding ahead of a custom plugin
        # that registers its own provider class later.
    pool = _open_pool(args)
    cred = Credential(key=args.key, label=args.label)
    pool.add_credential(args.provider, cred)
    suffix = args.key[-4:] if len(args.key) >= 4 else args.key
    label_str = f" (label: {args.label})" if args.label else ""
    print(f"added key ...{suffix} for {args.provider}{label_str}")
    return 0


def _cmd_remove_key(args) -> int:
    pool = _open_pool(args)
    removed = pool.remove_credential(args.provider, args.key_or_match)
    if removed == 0:
        print(
            f"no credential matched {args.key_or_match!r} for {args.provider!r} "
            "(or the prefix was ambiguous)",
            file=sys.stderr,
        )
        return 2
    print(f"removed {removed} credential(s) for {args.provider}")
    return 0


# ---- test ---------------------------------------------------------------


def _cmd_test(args) -> int:
    pool = _open_pool(args)
    cfg = load_config()
    registered = set(list_providers())
    if args.provider:
        if args.provider not in registered:
            print(
                f"error: {args.provider!r} is not registered. "
                f"Known: {', '.join(sorted(registered))}",
                file=sys.stderr,
            )
            return 2
        targets = [args.provider]
    else:
        targets = sorted(registered)

    any_failed = False
    model_override = getattr(args, "model", None)
    for name in targets:
        ok, detail = _probe_provider(name, cfg, pool, model_override=model_override)
        marker = "ok " if ok else "FAIL"
        print(f"  [{marker}] {name:<14} {detail}")
        if not ok:
            any_failed = True
    return 0 if not any_failed else 1


def _probe_provider(
    name: str,
    cfg,
    pool: CredentialPool,
    *,
    model_override: str | None = None,
) -> tuple[bool, str]:
    """Send the smallest possible probe to ``name``. Returns
    (ok, one-line-detail)."""
    from ..providers.runtime_resolver import resolve_provider

    # For ollama / openai_compat: no credential needed; just verify the
    # server responds on /api/tags or equivalent.
    if name == "ollama":
        try:
            provider, _ = resolve_provider(cfg.model, cfg, pool)
            try:
                models = provider.list_models()
            finally:
                provider.close()
            return True, f"reachable ({len(models)} local models)"
        except Exception as e:
            return False, f"unreachable: {e}"

    if name == "openai_compat":
        host = (cfg.providers or {}).get("openai_compat", {}).get("host")
        if not host:
            return False, "providers.openai_compat.host not configured"
        return True, f"host configured: {host} (no live probe)"

    # Hosted providers: requires at least one credential. Issue a tiny
    # 5-token completion; eat the response, just verify no exception.
    cred = pool.get(name)
    if cred is None:
        return False, "no credential in pool"
    # Resolve via the routing rules — we want to exercise the same path
    # the agent uses.
    sample_model = model_override or _SAMPLE_MODELS.get(name)
    if sample_model is None:
        return False, (
            "no sample model known for this provider; pass --model <name> to probe a specific model"
        )
    try:
        provider, bare = resolve_provider(sample_model, cfg, pool)
    except Exception as e:
        return False, f"resolve failed: {e}"
    try:
        chunks = 0
        for chunk in provider.stream_chat(
            model=bare,
            messages=[{"role": "user", "content": "say hi in one word"}],
            max_tokens=5,
            temperature=0.0,
        ):
            chunks += 1
            if chunks > 50:
                break
        return True, f"{cred.label or '(unlabeled)'} → {chunks} chunks"
    except Exception as e:
        # 401/403 is a "your key is bad" signal; surface it clearly.
        return False, f"{type(e).__name__}: {e}"
    finally:
        provider.close()


# Tiny / cheap models for each hosted provider — used by ``athena
# providers test`` only. If a real ATHENA_PROVIDERS_TEST_MODEL env var
# is set per-provider, that overrides.
_SAMPLE_MODELS: dict[str, str] = {
    # Names go stale fast — `athena providers models <name>` queries the
    # live catalog if these break. Override with --model on `test`.
    "anthropic": "anthropic/claude-haiku-4-5-20251001",
    "openai": "openai/gpt-4o-mini",
    "google": "gemini-1.5-flash",
    "openrouter": "openrouter/openai/gpt-4o-mini",
    "nous": "nous/Hermes-3-Llama-3.1-8B",
}


# ---- Entry point --------------------------------------------------------


def _cmd_models(args) -> int:
    """Query the provider's list-models endpoint and print every available id."""
    pool = _open_pool(args)
    cfg = load_config()
    name = args.provider
    registered = set(list_providers())
    if name not in registered:
        print(
            f"error: {name!r} is not registered. Known: {', '.join(sorted(registered))}",
            file=sys.stderr,
        )
        return 2

    from ..providers.runtime_resolver import resolve_provider

    # Pick any model that routes to this provider so we can build the
    # provider instance with a credential. Hosted providers need the key
    # for list-models too; openai_compat / ollama don't.
    probe_model = _SAMPLE_MODELS.get(name) or cfg.model
    try:
        provider, _ = resolve_provider(probe_model, cfg, pool)
    except Exception as e:
        print(f"error: could not build {name} provider: {e}", file=sys.stderr)
        return 2
    try:
        try:
            models = provider.list_models()
        except Exception as e:
            print(f"error: list_models failed: {e}", file=sys.stderr)
            return 1
    finally:
        provider.close()

    if not models:
        print(f"(no models returned for {name})")
        return 0
    if args.limit > 0:
        models = models[: args.limit]
    for m in sorted(models):
        print(f"  {m}")
    return 0


def main(argv: list[str]) -> int:
    args = _build_parser().parse_args(argv)
    if args.cmd == "list":
        return _cmd_list(args)
    if args.cmd == "test":
        return _cmd_test(args)
    if args.cmd == "add-key":
        return _cmd_add_key(args)
    if args.cmd == "remove-key":
        return _cmd_remove_key(args)
    if args.cmd in ("capabilities", "caps"):
        return _cmd_capabilities(args)
    if args.cmd == "models":
        return _cmd_models(args)
    return 2
