"""``athena providers {list,test,add-key,remove-key}``.

Talks to the same credential pool the agent uses (``~/.athena/
credentials.json`` by default). ``list`` is a redacted summary;
``test`` issues a tiny completion request against each configured
hosted provider (and a cheap reachability check against ollama);
``add-key`` / ``remove-key`` mutate the pool.

Operates on the global pool by default; tests pass their own pool via
``--pool-path`` for isolation.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..config import CONFIG_DIR, load_config
from ..providers import list_providers
from ..providers.credential_pool import Credential, CredentialPool


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="athena providers")
    ap.add_argument(
        "--pool-path",
        type=Path,
        default=None,
        help="Override the credential-pool file (default: "
             "<CONFIG_DIR>/credentials.json).",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="Show configured providers and credential counts.")

    p_test = sub.add_parser(
        "test", help="Ping each provider with a tiny completion request.",
    )
    p_test.add_argument("--provider", default=None,
                        help="Limit the test to one provider name.")

    p_add = sub.add_parser("add-key", help="Add a credential for a provider.")
    p_add.add_argument("provider")
    p_add.add_argument("key")
    p_add.add_argument("--label", default="",
                       help="Optional human-readable label (e.g. 'personal').")

    p_rm = sub.add_parser("remove-key", help="Remove a credential by exact key or unambiguous prefix.")
    p_rm.add_argument("provider")
    p_rm.add_argument("key_or_prefix")

    return ap


def _open_pool(args) -> CredentialPool:
    path = args.pool_path or (CONFIG_DIR / "credentials.json")
    return CredentialPool(path)


# ---- list ---------------------------------------------------------------


def _cmd_list(args) -> int:
    pool = _open_pool(args)
    registered = set(list_providers())
    with_creds = pool.list_credentials()
    for name in sorted(registered):
        bucket = with_creds.get(name, [])
        in_cooldown = sum(1 for c in bucket if c.get("in_cooldown"))
        cooldown_note = (
            f" ({in_cooldown} in cooldown)" if in_cooldown else ""
        )
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
    removed = pool.remove_credential(args.provider, args.key_or_prefix)
    if removed == 0:
        print(
            f"no credential matched {args.key_or_prefix!r} for {args.provider!r} "
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
    for name in targets:
        ok, detail = _probe_provider(name, cfg, pool)
        marker = "ok " if ok else "FAIL"
        print(f"  [{marker}] {name:<14} {detail}")
        if not ok:
            any_failed = True
    return 0 if not any_failed else 1


def _probe_provider(name: str, cfg, pool: CredentialPool) -> tuple[bool, str]:
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
    sample_model = _SAMPLE_MODELS.get(name)
    if sample_model is None:
        return False, "no sample model known for this provider"
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
    "anthropic": "anthropic/claude-3-5-haiku-20241022",
    "openai": "openai/gpt-4o-mini",
    "google": "gemini-1.5-flash",
    "openrouter": "openrouter/openai/gpt-4o-mini",
    "nous": "nous/Hermes-3-Llama-3.1-8B",
}


# ---- Entry point --------------------------------------------------------


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
    return 2
