"""``athena webhook {add, list, info, remove, enable, disable, test}``.

Operator surface for managing webhook subscriptions. The store
lives at ``<profile>/webhooks.db`` so the active profile picks
which set of webhooks the daemon serves.

``test`` is the integration sanity check: it constructs the same
HMAC the listener will verify, POSTs a synthetic payload to the
configured URL, and surfaces the HTTP response so the operator
sees auth + rate-limit + dispatch all working before pointing a
real source at the URL.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import secrets
import sys
from pathlib import Path
from typing import Any

import httpx

from ..config import Config, load_config
from ..config import profile_dir as _profile_dir
from ..profiles.resolution import resolve_active_profile
from ..webhooks.subscription import (
    AuthType,
    WebhookStore,
    WebhookSubscription,
)


def _store_for_active_profile(cfg: Config) -> WebhookStore:
    profile = resolve_active_profile(config_default=cfg.profile)
    p_dir = _profile_dir(profile)
    p_dir.mkdir(parents=True, exist_ok=True)
    return WebhookStore(p_dir / "webhooks.db")


def _format_sub(sub: WebhookSubscription) -> dict[str, Any]:
    return {
        "id": sub.id,
        "description": sub.description,
        "auth_type": sub.auth_type,
        "binding_type": sub.binding_type,
        "skill_name": sub.skill_name,
        "prompt_template": sub.prompt_template,
        "delivery_target": sub.delivery_target,
        "rate_limit_per_minute": sub.rate_limit_per_minute,
        "enabled": sub.enabled,
        "fire_count": sub.fire_count,
        "last_fired_at": (sub.last_fired_at.isoformat() if sub.last_fired_at else None),
        "created_at": sub.created_at.isoformat(),
    }


# ---- add -------------------------------------------------------------


def cmd_add(args: argparse.Namespace) -> int:
    if args.skill and args.prompt_template:
        sys.stderr.write("error: pass either --skill or --prompt-template, not both\n")
        return 2
    if not args.skill and not args.prompt_template:
        sys.stderr.write("error: pass either --skill <name> or --prompt-template <text>\n")
        return 2

    auth_type: AuthType = args.auth
    secret = args.secret
    if auth_type == "none":
        secret = ""
    elif not secret:
        # Auto-generate a fresh secret if the user didn't supply one.
        # 32 bytes = 256 bits of entropy hex-encoded; comfortably
        # past brute-force range.
        secret = secrets.token_hex(32)
        sys.stdout.write(f"generated {auth_type} secret: {secret}\n")
        sys.stdout.write(
            "store this — it won't be displayed again.\n",
        )

    try:
        sub = WebhookSubscription(
            description=args.description or "",
            auth_type=auth_type,
            auth_secret=secret,
            binding_type="skill" if args.skill else "prompt",
            skill_name=args.skill,
            prompt_template=args.prompt_template,
            delivery_target=args.deliver,
            rate_limit_per_minute=args.rate_limit,
        )
    except ValueError as e:
        sys.stderr.write(f"error: {e}\n")
        return 2

    cfg = load_config()
    store = _store_for_active_profile(cfg)
    store.add(sub)

    host = args.host or "127.0.0.1"
    port = args.port or 4747
    url = f"http://{host}:{port}/webhook/{sub.id}"

    if args.json:
        sys.stdout.write(
            json.dumps(
                {
                    "id": sub.id,
                    "url": url,
                    "auth_type": sub.auth_type,
                },
                indent=2,
            )
            + "\n"
        )
        return 0

    sys.stdout.write(f"webhook registered: {sub.id}\n")
    sys.stdout.write(f"  url: {url}\n")
    sys.stdout.write(f"  auth: {sub.auth_type}")
    if auth_type == "hmac_sha256":
        sys.stdout.write(" (sign body with HMAC-SHA256 using the secret above)")
    elif auth_type == "bearer":
        sys.stdout.write(" (send 'Authorization: Bearer <secret>')")
    sys.stdout.write("\n")
    if sub.binding_type == "skill":
        sys.stdout.write(f"  skill: {sub.skill_name}\n")
    else:
        sys.stdout.write(f"  prompt: {(sub.prompt_template or '')[:80]}\n")
    sys.stdout.write(f"  delivery: {sub.delivery_target}\n")
    sys.stdout.write(f"  rate limit: {sub.rate_limit_per_minute}/min\n")
    return 0


# ---- list / info ---------------------------------------------------


def cmd_list(args: argparse.Namespace) -> int:
    cfg = load_config()
    store = _store_for_active_profile(cfg)
    subs = store.list()
    if args.json:
        sys.stdout.write(
            json.dumps(
                [_format_sub(s) for s in subs],
                indent=2,
            )
            + "\n"
        )
        return 0
    if not subs:
        sys.stdout.write("(no webhooks registered)\n")
        return 0
    for sub in subs:
        flags = []
        if not sub.enabled:
            flags.append("disabled")
        bind = f"skill:{sub.skill_name}" if sub.binding_type == "skill" else "prompt-template"
        suffix = f"  [{', '.join(flags)}]" if flags else ""
        sys.stdout.write(
            f"{sub.id[:8]}…  {sub.auth_type:12}  {bind:30}  fires={sub.fire_count}{suffix}\n"
        )
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    cfg = load_config()
    store = _store_for_active_profile(cfg)
    sub = store.get(args.id)
    if sub is None:
        sys.stderr.write(f"error: no webhook with id {args.id}\n")
        return 2
    sys.stdout.write(json.dumps(_format_sub(sub), indent=2) + "\n")
    return 0


# ---- remove / enable / disable ------------------------------------


def cmd_remove(args: argparse.Namespace) -> int:
    cfg = load_config()
    store = _store_for_active_profile(cfg)
    if not store.delete(args.id):
        sys.stderr.write(f"error: no webhook with id {args.id}\n")
        return 2
    sys.stdout.write(f"deleted webhook {args.id}\n")
    return 0


def cmd_enable(args: argparse.Namespace) -> int:
    return _set_enabled(args.id, True)


def cmd_disable(args: argparse.Namespace) -> int:
    return _set_enabled(args.id, False)


def _set_enabled(webhook_id: str, enabled: bool) -> int:
    cfg = load_config()
    store = _store_for_active_profile(cfg)
    if not store.set_enabled(webhook_id, enabled):
        sys.stderr.write(f"error: no webhook with id {webhook_id}\n")
        return 2
    state = "enabled" if enabled else "disabled"
    sys.stdout.write(f"webhook {webhook_id} {state}\n")
    return 0


# ---- test ---------------------------------------------------------


def cmd_test(args: argparse.Namespace) -> int:
    """POST a synthetic payload to the configured URL, signed for
    the webhook's auth_type. Surfaces the HTTP response so the
    operator can verify auth + dispatch work end-to-end before
    pointing a real source at it.

    Requires the daemon (`athena gateway run`) to actually be
    running — this is the integration smoke, not a unit-test
    substitute.
    """
    cfg = load_config()
    store = _store_for_active_profile(cfg)
    sub = store.get(args.id)
    if sub is None:
        sys.stderr.write(f"error: no webhook with id {args.id}\n")
        return 2

    host = args.host or "127.0.0.1"
    port = args.port or 4747
    url = f"http://{host}:{port}/webhook/{sub.id}"

    payload = (
        json.loads(Path(args.payload_file).read_text(encoding="utf-8"))
        if args.payload_file
        else {"event": "athena-webhook-test", "fired_at": _now_iso()}
    )
    body = json.dumps(payload).encode("utf-8")

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if sub.auth_type == "hmac_sha256":
        sig = hmac.new(
            sub.auth_secret.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()
        headers["X-Webhook-Signature"] = sig
    elif sub.auth_type == "bearer":
        headers["Authorization"] = f"Bearer {sub.auth_secret}"

    try:
        response = httpx.post(url, content=body, headers=headers, timeout=10.0)
    except httpx.RequestError as e:
        sys.stderr.write(
            f"error: webhook server unreachable at {url}: {e}\n"
            "is `athena gateway run` running with "
            "[gateway.webhooks].enabled = true?\n"
        )
        return 1

    if args.json:
        sys.stdout.write(
            json.dumps(
                {
                    "status_code": response.status_code,
                    "body": response.text,
                    "url": url,
                },
                indent=2,
            )
            + "\n"
        )
    else:
        sys.stdout.write(f"POST {url} → {response.status_code}\n")
        if response.text.strip():
            sys.stdout.write(f"  body: {response.text.strip()}\n")
    return 0 if response.status_code < 400 else 1


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


# ---- argument parser ----------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="athena webhook")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser("add", help="Register a new webhook.")
    p_add.add_argument("--description", help="Human-readable label.")
    p_add.add_argument(
        "--auth",
        choices=("hmac_sha256", "bearer", "none"),
        default="hmac_sha256",
    )
    p_add.add_argument(
        "--secret",
        help="Auth secret. Auto-generated when omitted (HMAC/Bearer).",
    )
    p_add.add_argument("--skill", help="Skill name to fire on inbound.")
    p_add.add_argument(
        "--prompt-template",
        help="Prompt template; supports {{ payload }} / {{ headers }}.",
    )
    p_add.add_argument(
        "--deliver",
        default="log",
        help="log | none | file:<path> | gateway://<platform>/<chat>",
    )
    p_add.add_argument(
        "--rate-limit",
        type=int,
        default=60,
        help="Max calls per minute (default 60).",
    )
    p_add.add_argument("--host", help="Display host in the printed URL.")
    p_add.add_argument(
        "--port",
        type=int,
        help="Display port in the printed URL.",
    )
    p_add.add_argument("--json", action="store_true")
    p_add.set_defaults(handler=cmd_add)

    p_list = sub.add_parser("list", help="Show every registered webhook.")
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(handler=cmd_list)

    p_info = sub.add_parser("info", help="Full details for one webhook.")
    p_info.add_argument("id")
    p_info.set_defaults(handler=cmd_info)

    p_remove = sub.add_parser("remove", help="Delete a webhook.")
    p_remove.add_argument("id")
    p_remove.set_defaults(handler=cmd_remove)

    p_enable = sub.add_parser("enable", help="Enable a webhook.")
    p_enable.add_argument("id")
    p_enable.set_defaults(handler=cmd_enable)

    p_disable = sub.add_parser("disable", help="Disable a webhook.")
    p_disable.add_argument("id")
    p_disable.set_defaults(handler=cmd_disable)

    p_test = sub.add_parser(
        "test",
        help="POST a synthetic payload to verify the URL works.",
    )
    p_test.add_argument("id")
    p_test.add_argument("--host", help="Override host (default 127.0.0.1).")
    p_test.add_argument(
        "--port",
        type=int,
        help="Override port (default 4747).",
    )
    p_test.add_argument(
        "--payload-file",
        help="Path to a JSON file to use as the body (default: a small synthetic payload).",
    )
    p_test.add_argument("--json", action="store_true")
    p_test.set_defaults(handler=cmd_test)

    return ap


def main(argv: list[str]) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.handler(args) or 0)
