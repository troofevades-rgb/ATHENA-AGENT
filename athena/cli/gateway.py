"""``athena gateway {run,routes,link,unlink,canonical-users}``.

Subcommands:

- ``run`` — start the daemon, connect every adapter configured in
  ``cfg.gateway.platforms``, and run in foreground until SIGINT/SIGTERM.
- ``routes`` — list every persisted gateway route (no daemon required).
- ``link`` — register a canonical user → platform-id binding for
  cross-platform continuity. No daemon required.
- ``unlink`` — remove a canonical user's bindings.
- ``canonical-users`` — list distinct canonical users known to the
  router.

Service-manager integration (``install``, ``start``, ``stop``,
``status``) is deliberately out of scope here. systemd / launchd /
Windows service wrapping varies enough that a one-size CLI helper
ends up being worse than just letting users wrap ``athena gateway
run`` in their preferred supervisor. The :mod:`.daemon` module's
SIGINT handling means a plain unit file works fine.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import sys
from pathlib import Path
from typing import Any

from ..config import Config, load_config, profile_dir
from ..gateway.continuity import ContinuityManager
from ..gateway.daemon import GatewayDaemon
from ..gateway.router import SessionRouter
from ..sessions.store import SessionStore

logger = logging.getLogger("athena.gateway.cli")


# ---- subcommand: run ----------------------------------------------------


def _build_adapters(daemon: GatewayDaemon, cfg: Config) -> list[str]:
    """Construct and register every adapter named in
    ``cfg.gateway.platforms``. Returns the list of platform names
    successfully registered."""
    registered: list[str] = []
    platforms = cfg.gateway.platforms or {}
    if not isinstance(platforms, dict):
        logger.warning(
            "config: gateway.platforms must be a table; got %r — ignoring",
            type(platforms).__name__,
        )
        return registered

    for name, settings in platforms.items():
        if not isinstance(settings, dict):
            logger.warning(
                "config: gateway.platforms.%s must be a table — skipping",
                name,
            )
            continue
        if not settings.get("enabled", True):
            logger.info("skipping disabled platform %r", name)
            continue
        try:
            adapter = _instantiate_adapter(daemon, name, settings)
        except ValueError as e:
            logger.error("could not configure platform %r: %s", name, e)
            continue
        except ImportError as e:
            logger.error(
                "platform %r requires the [gateway] extras: %s",
                name,
                e,
            )
            continue
        daemon.register(adapter)
        registered.append(name)
    return registered


def _instantiate_adapter(
    daemon: GatewayDaemon,
    name: str,
    settings: dict[str, Any],
):
    """Construct one adapter by name. Raises ``ValueError`` for
    missing required settings; ``ImportError`` for missing SDKs."""
    if name == "telegram":
        from ..gateway.platforms.telegram import TelegramAdapter

        token = settings.get("bot_token")
        if not token:
            raise ValueError("telegram requires bot_token")
        return TelegramAdapter(daemon, bot_token=token)
    if name == "slack":
        from ..gateway.platforms.slack import SlackAdapter

        bot = settings.get("bot_token")
        app = settings.get("app_token")
        if not bot or not app:
            raise ValueError("slack requires bot_token and app_token")
        return SlackAdapter(daemon, bot_token=bot, app_token=app)
    if name == "discord":
        from ..gateway.platforms.discord import DiscordAdapter

        token = settings.get("bot_token")
        if not token:
            raise ValueError("discord requires bot_token")
        return DiscordAdapter(daemon, bot_token=token)
    if name == "signal":
        from ..gateway.platforms.signal import SignalAdapter

        rest_url = settings.get("rest_url")
        account = settings.get("account_number")
        if not rest_url or not account:
            raise ValueError(
                "signal requires rest_url and account_number",
            )
        return SignalAdapter(
            daemon,
            rest_url=rest_url,
            account_number=account,
        )
    if name == "imessage":
        from ..gateway.platforms.imessage import IMessageAdapter

        server = settings.get("server_url")
        password = settings.get("password")
        if not server or not password:
            raise ValueError(
                "imessage requires server_url and password",
            )
        return IMessageAdapter(
            daemon,
            server_url=server,
            password=password,
        )
    if name == "matrix":
        from ..gateway.platforms.matrix import MatrixAdapter

        homeserver = settings.get("homeserver")
        user_id = settings.get("user_id")
        access_token = settings.get("access_token")
        device_id = settings.get("device_id")
        missing = [
            k
            for k, v in {
                "homeserver": homeserver,
                "user_id": user_id,
                "access_token": access_token,
                "device_id": device_id,
            }.items()
            if not v
        ]
        if missing:
            raise ValueError(
                f"matrix requires {', '.join(missing)}",
            )
        store_path_raw = settings.get("store_path")
        store_path = Path(store_path_raw).expanduser() if store_path_raw else None
        return MatrixAdapter(
            daemon,
            homeserver=homeserver,
            user_id=user_id,
            access_token=access_token,
            device_id=device_id,
            store_path=store_path,
        )
    if name == "email":
        from ..gateway.platforms.email import EmailAdapter

        required = (
            "imap_host",
            "imap_user",
            "imap_password",
            "smtp_host",
            "smtp_user",
            "smtp_password",
            "from_address",
        )
        missing = [k for k in required if not settings.get(k)]
        if missing:
            raise ValueError(
                f"email requires {', '.join(missing)}",
            )
        return EmailAdapter(
            daemon,
            imap_host=settings["imap_host"],
            imap_user=settings["imap_user"],
            imap_password=settings["imap_password"],
            smtp_host=settings["smtp_host"],
            smtp_user=settings["smtp_user"],
            smtp_password=settings["smtp_password"],
            from_address=settings["from_address"],
            imap_port=int(settings.get("imap_port", 993)),
            smtp_port=int(settings.get("smtp_port", 587)),
            subject_prefix=settings.get("subject_prefix", "[athena] "),
            allowed_senders=settings.get("allowed_senders"),
        )
    raise ValueError(f"unknown platform: {name!r}")


def cmd_run(args: argparse.Namespace) -> int:
    cfg = load_config()
    if args.profile:
        cfg.profile = args.profile

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    daemon = GatewayDaemon(cfg)
    registered = _build_adapters(daemon, cfg)
    if not registered:
        sys.stderr.write(
            "no gateway platforms configured. Set [gateway.platforms.<name>]\n"
            "in ~/.athena/config.toml — bot_token for telegram/discord, "
            "bot_token + app_token for slack.\n"
        )
        return 2

    sys.stdout.write(f"gateway up: profile={cfg.profile} platforms={', '.join(registered)}\n")
    sys.stdout.flush()

    return asyncio.run(_run_until_signal(daemon))


async def _run_until_signal(daemon: GatewayDaemon) -> int:
    """Start the daemon, install signal handlers, and park until
    SIGINT/SIGTERM. Posix only — on Windows we fall back to a
    keyboard-interrupt sentinel because ``add_signal_handler`` isn't
    supported there."""
    await daemon.start()

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _stop(_signum: int = 0) -> None:
        stop_event.set()

    if sys.platform != "win32":
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _stop, int(sig))
            except (NotImplementedError, RuntimeError):
                pass

    try:
        await stop_event.wait()
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("gateway shutting down…\n")
        sys.stdout.flush()
        await daemon.stop()
    return 0


# ---- subcommand: routes -------------------------------------------------


def cmd_routes(args: argparse.Namespace) -> int:
    cfg = load_config()
    if args.profile:
        cfg.profile = args.profile
    router = _read_only_router(cfg)
    routes = router.list_routes(platform=args.platform)
    if args.json:
        payload = [
            {
                "platform": r.platform,
                "chat_id": r.chat_id,
                "user_id": r.user_id,
                "session_id": r.session_id,
                "profile": r.profile,
                "created_at": r.created_at.isoformat(),
                "last_seen_at": r.last_seen_at.isoformat(),
            }
            for r in routes
        ]
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        return 0

    if not routes:
        sys.stdout.write("(no routes)\n")
        return 0
    for r in routes:
        sys.stdout.write(
            f"{r.platform:8} {r.chat_id:>20}  {r.user_id:>20}  "
            f"session={r.session_id[:8]}  last_seen={r.last_seen_at.isoformat()}\n"
        )
    return 0


# ---- subcommand: link ---------------------------------------------------


def cmd_link(args: argparse.Namespace) -> int:
    """``athena gateway link --canonical alice
    --telegram tg-1 --slack U-x --discord 1234567``."""
    cfg = load_config()
    if args.profile:
        cfg.profile = args.profile
    router = _read_only_router(cfg)
    cm = ContinuityManager(router)
    platform_ids: dict[str, str] = {}
    for plat in ("telegram", "slack", "discord"):
        value = getattr(args, plat, None)
        if value:
            platform_ids[plat] = value
    if not platform_ids:
        sys.stderr.write("error: provide at least one of --telegram --slack --discord\n")
        return 2
    try:
        cm.link_canonical(args.canonical, platform_ids)
    except ValueError as e:
        sys.stderr.write(f"error: {e}\n")
        return 2
    pairs = cm.platforms_for(args.canonical)
    sys.stdout.write(f"linked {args.canonical}:\n")
    for plat, pid in pairs:
        sys.stdout.write(f"  {plat}: {pid}\n")
    return 0


# ---- subcommand: unlink -------------------------------------------------


def cmd_unlink(args: argparse.Namespace) -> int:
    cfg = load_config()
    if args.profile:
        cfg.profile = args.profile
    router = _read_only_router(cfg)
    cm = ContinuityManager(router)
    n = cm.unlink_canonical(args.canonical)
    if n == 0:
        sys.stdout.write(f"no bindings found for {args.canonical}\n")
        return 0
    sys.stdout.write(f"unlinked {args.canonical} ({n} bindings removed)\n")
    return 0


# ---- subcommand: canonical-users ----------------------------------------


def cmd_canonical_users(args: argparse.Namespace) -> int:
    cfg = load_config()
    if args.profile:
        cfg.profile = args.profile
    router = _read_only_router(cfg)
    cm = ContinuityManager(router)
    users = cm.list_canonical_users()
    if not users:
        sys.stdout.write("(no canonical users)\n")
        return 0
    for u in users:
        pairs = cm.platforms_for(u)
        platform_list = ", ".join(f"{p}={pid}" for p, pid in pairs)
        sys.stdout.write(f"{u}: {platform_list}\n")
    return 0


# ---- helpers ------------------------------------------------------------


def _read_only_router(cfg: Config) -> SessionRouter:
    """Construct a SessionRouter for inspection-only CLI commands.

    Uses the same on-disk database the running daemon does, so
    ``athena gateway routes`` works whether the daemon is up or
    down. The model / provider names are placeholders since we never
    actually mint sessions from a CLI inspection.
    """
    profile = cfg.profile or "default"
    p_dir = profile_dir(profile)
    p_dir.mkdir(parents=True, exist_ok=True)
    store = SessionStore(p_dir)
    return SessionRouter(
        p_dir,
        store,
        profile=profile,
        model=cfg.model,
        provider="ollama",  # placeholder; not used for inspection
        continuity=cfg.gateway.continuity,
    )


# ---- argument parser ----------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="athena gateway")
    ap.add_argument(
        "--profile",
        help="Profile name (default: from config / ATHENA_PROFILE).",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="Run the gateway daemon in foreground.")
    p_run.set_defaults(handler=cmd_run)

    p_routes = sub.add_parser(
        "routes",
        help="List persisted (platform, chat, user) → session routes.",
    )
    p_routes.add_argument("--platform", help="Filter by platform.")
    p_routes.add_argument(
        "--json",
        action="store_true",
        help="JSON output for scripting.",
    )
    p_routes.set_defaults(handler=cmd_routes)

    p_link = sub.add_parser(
        "link",
        help="Link a canonical user to platform identities.",
    )
    p_link.add_argument(
        "--canonical",
        required=True,
        help="Canonical user id (your choice).",
    )
    p_link.add_argument("--telegram", help="Telegram user id (numeric).")
    p_link.add_argument("--slack", help="Slack user id (Uxxxxx).")
    p_link.add_argument("--discord", help="Discord user id (snowflake).")
    p_link.set_defaults(handler=cmd_link)

    p_unlink = sub.add_parser(
        "unlink",
        help="Remove every binding for a canonical user.",
    )
    p_unlink.add_argument("--canonical", required=True)
    p_unlink.set_defaults(handler=cmd_unlink)

    p_users = sub.add_parser(
        "canonical-users",
        help="List canonical users and their platform bindings.",
    )
    p_users.set_defaults(handler=cmd_canonical_users)

    return ap


def main(argv: list[str]) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.handler(args) or 0)
