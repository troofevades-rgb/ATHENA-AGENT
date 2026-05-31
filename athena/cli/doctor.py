"""``athena doctor [--json] [--strict]``.

Health-check CLI for the local athena install. Runs a series of
non-destructive read-only checks against the runtime configuration,
credentials, providers, filesystem layout, and TUI bundle, then
reports per-check status (``ok`` / ``warn`` / ``fail``) with the
exit code reflecting the worst result.

Why this exists: the dogfood pattern that motivated it was "is my
key set? is my model id right? does my MCP server reach? is Ollama
running?" -- a sequence of trial-and-error that operators kept
walking through every time something didn't work. ``athena doctor``
walks the sequence once, prints a checklist, and reports exit code 1
when any check actually fails (and 0 for warnings).

Output modes:

  * Default text mode -- per-check ``[OK]`` / ``[WARN]`` / ``[FAIL]``
    lines grouped by section. A single newline-separated summary at
    the end is what to copy-paste when filing a bug.
  * ``--json`` -- machine-readable for CI / Slack-bot integration.
    Same structure, one JSON object per check.

Flags:

  * ``--strict`` -- exit code 1 on WARN too (not just FAIL). For CI
    pipelines that want to gate on "everything healthy."
  * ``--no-network`` -- skip checks that touch a remote API
    (OpenRouter ``/models``, Anthropic ``/v1/messages?test``, etc.).
    Useful in air-gapped CI or when the operator just wants the
    local-state report.

Design notes:

  * Every check is wrapped in a try/except so a broken check can
    never crash the report -- the worst it can do is mark itself
    FAIL with the exception's repr in ``detail``.
  * Network probes are bounded by short timeouts (3s each) so the
    full doctor run finishes in seconds even when an endpoint is
    unreachable.
  * No mutation. ``athena doctor`` MUST be safe to run during an
    incident without making the situation worse.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

Severity = Literal["ok", "warn", "fail", "skip"]


# Pretty-print markers. Plain ASCII so they render in every shell
# (PowerShell, cmd, gnome-terminal, conhost). Operators with
# emoji-capable terminals can prettify their own output downstream.
_MARKER = {
    "ok": "[ OK ]",
    "warn": "[WARN]",
    "fail": "[FAIL]",
    "skip": "[SKIP]",
}


@dataclass
class CheckResult:
    """One row in the doctor report. ``name`` is short ID for
    machines (e.g. ``ollama.daemon``); ``label`` is human prose
    (``"Ollama daemon reachable"``); ``detail`` is the data point
    or error message (``"24 models, 18ms"``).

    ``severity`` drives the exit code: any ``fail`` -> exit 1;
    ``warn`` -> exit 1 only under ``--strict``.
    """

    section: str
    name: str
    label: str
    severity: Severity
    detail: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def _safe(label: str, fn: Callable[[], CheckResult]) -> CheckResult:
    """Wrap a check so an unexpected exception becomes a FAIL row
    rather than crashing the whole report."""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        return CheckResult(
            section="error",
            name="check.crashed",
            label=label,
            severity="fail",
            detail=f"check raised: {type(e).__name__}: {e}",
        )


# ── Section: config ─────────────────────────────────────────────────


def _check_config_loads() -> CheckResult:
    from ..config import load_config

    cfg = load_config()
    detail = f"profile={cfg.profile!r}, model={cfg.model!r}"
    return CheckResult(
        section="config",
        name="config.load",
        label="Config parses",
        severity="ok",
        detail=detail,
    )


def _check_deprecated_config_keys() -> CheckResult:
    """One-stop summary of deprecated keys that fired warnings
    during config load this process. Empty -> OK. Non-empty ->
    WARN with the full list so operators see every key to fix in
    one place instead of scattered ``warning:`` lines."""
    from ..config import load_config, reported_deprecations

    # Ensure the config has actually been loaded at least once so
    # the dedup set is populated. ``load_config()`` is cheap (parses
    # a small TOML file) and idempotent.
    load_config()
    deprecations = reported_deprecations()
    if not deprecations:
        return CheckResult(
            section="config",
            name="config.deprecations",
            label="Deprecated config keys",
            severity="ok",
            detail="none",
        )
    # Sort for stable ordering across runs.
    keys = sorted({legacy_key for _path, legacy_key in deprecations})
    return CheckResult(
        section="config",
        name="config.deprecations",
        label="Deprecated config keys",
        severity="warn",
        detail=(
            f"{len(keys)} key(s) flagged: {', '.join(keys)}. "
            "Each emits a stderr warning once per process."
        ),
        extra={"keys": keys},
    )


def _check_config_path_exists() -> CheckResult:
    config_path = Path.home() / ".athena" / "config.toml"
    if config_path.exists():
        size = config_path.stat().st_size
        return CheckResult(
            section="config",
            name="config.file",
            label="Config file present",
            severity="ok",
            detail=f"{config_path} ({size} bytes)",
        )
    return CheckResult(
        section="config",
        name="config.file",
        label="Config file present",
        severity="warn",
        detail=f"{config_path} missing -- defaults will apply",
    )


# ── Section: credentials ────────────────────────────────────────────


def _check_credentials_pool() -> CheckResult:
    """List providers with at least one credential. Never prints the
    key itself -- only provider names + last-used age."""
    from ..providers.credential_pool import global_pool

    try:
        pool = global_pool()
        provider_names = pool.providers()
    except Exception as e:  # noqa: BLE001
        return CheckResult(
            section="credentials",
            name="credentials.pool",
            label="Credential pool readable",
            severity="fail",
            detail=str(e),
        )
    if not provider_names:
        return CheckResult(
            section="credentials",
            name="credentials.pool",
            label="Credential pool",
            severity="warn",
            detail=(
                "no provider credentials configured -- "
                "use `athena providers add-key <provider> --key ...`"
            ),
        )
    return CheckResult(
        section="credentials",
        name="credentials.pool",
        label="Credential pool",
        severity="ok",
        detail=f"providers configured: {', '.join(sorted(provider_names))}",
        extra={"providers": sorted(provider_names)},
    )


def _check_dotenv_present() -> CheckResult:
    """``~/.athena/.env`` is the alternative credential surface +
    home for feature flags like ``ATHENA_ALLOW_GODMODE``."""
    dotenv = Path.home() / ".athena" / ".env"
    if not dotenv.exists():
        return CheckResult(
            section="credentials",
            name="dotenv.file",
            label="~/.athena/.env",
            severity="skip",
            detail="optional file not present",
        )
    return CheckResult(
        section="credentials",
        name="dotenv.file",
        label="~/.athena/.env",
        severity="ok",
        detail=f"{dotenv} ({dotenv.stat().st_size} bytes)",
    )


# ── Section: ollama ─────────────────────────────────────────────────


def _check_ollama_daemon() -> CheckResult:
    """Probe Ollama's ``/api/tags``. Bounded by a 3s timeout so a
    stuck daemon doesn't wedge the doctor report."""
    try:
        import httpx
    except ImportError:
        return CheckResult(
            section="ollama",
            name="ollama.daemon",
            label="Ollama daemon",
            severity="fail",
            detail="httpx not importable",
        )
    from ..config import load_config

    host = load_config().ollama_host
    started = time.perf_counter()
    try:
        r = httpx.get(f"{host}/api/tags", timeout=3.0)
    except Exception as e:  # noqa: BLE001
        return CheckResult(
            section="ollama",
            name="ollama.daemon",
            label="Ollama daemon reachable",
            severity="fail",
            detail=f"{host}: {type(e).__name__}: {e}",
        )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    if r.status_code != 200:
        return CheckResult(
            section="ollama",
            name="ollama.daemon",
            label="Ollama daemon reachable",
            severity="fail",
            detail=f"{host} -> {r.status_code}",
        )
    models = (r.json() or {}).get("models") or []
    return CheckResult(
        section="ollama",
        name="ollama.daemon",
        label="Ollama daemon reachable",
        severity="ok",
        detail=f"{host} -- {len(models)} model(s), {elapsed_ms}ms",
        extra={"model_count": len(models), "host": host},
    )


# ── Section: hosted providers (auth probe) ──────────────────────────


def _check_openrouter_auth(skip_network: bool) -> CheckResult:
    """Cheapest possible auth probe: GET ``/api/v1/models``. No
    completion fired; just verifies the key resolves to a valid
    account."""
    from ..providers.credential_pool import global_pool

    cred = global_pool().get("openrouter")
    if cred is None or not cred.key:
        return CheckResult(
            section="providers",
            name="openrouter.auth",
            label="OpenRouter auth",
            severity="skip",
            detail="no credential in pool -- run `athena providers add-key openrouter --key ...`",
        )
    if skip_network:
        return CheckResult(
            section="providers",
            name="openrouter.auth",
            label="OpenRouter auth",
            severity="skip",
            detail="--no-network: not probed",
        )
    import httpx

    started = time.perf_counter()
    try:
        r = httpx.get(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": f"Bearer {cred.key}"},
            timeout=5.0,
        )
    except Exception as e:  # noqa: BLE001
        return CheckResult(
            section="providers",
            name="openrouter.auth",
            label="OpenRouter auth",
            severity="fail",
            detail=f"{type(e).__name__}: {e}",
        )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    if r.status_code == 401 or r.status_code == 403:
        return CheckResult(
            section="providers",
            name="openrouter.auth",
            label="OpenRouter auth",
            severity="fail",
            detail=f"unauthorized ({r.status_code}) -- key invalid or revoked",
        )
    if r.status_code != 200:
        return CheckResult(
            section="providers",
            name="openrouter.auth",
            label="OpenRouter auth",
            severity="warn",
            detail=f"unexpected status {r.status_code}",
        )
    model_count = len((r.json() or {}).get("data") or [])
    return CheckResult(
        section="providers",
        name="openrouter.auth",
        label="OpenRouter auth",
        severity="ok",
        detail=f"key valid, {model_count} models visible, {elapsed_ms}ms",
        extra={"model_count": model_count},
    )


# ── Section: filesystem layout ──────────────────────────────────────


def _check_athena_home_writable() -> CheckResult:
    """``~/.athena/`` must be writable for sessions / audit / etc."""
    import tempfile

    home = Path.home() / ".athena"
    if not home.exists():
        # The directory should be auto-created on first run; missing
        # is OK at doctor time -- the first session will create it.
        return CheckResult(
            section="filesystem",
            name="filesystem.home",
            label="~/.athena writable",
            severity="warn",
            detail=f"{home} does not exist yet (will be created on first run)",
        )
    try:
        with tempfile.NamedTemporaryFile(
            dir=str(home), prefix=".doctor_probe_", delete=True
        ):
            pass
    except OSError as e:
        return CheckResult(
            section="filesystem",
            name="filesystem.home",
            label="~/.athena writable",
            severity="fail",
            detail=f"{home}: {e}",
        )
    return CheckResult(
        section="filesystem",
        name="filesystem.home",
        label="~/.athena writable",
        severity="ok",
        detail=str(home),
    )


# ── Section: TUI bundle ─────────────────────────────────────────────


def _check_node_on_path() -> CheckResult:
    node = shutil.which("node")
    if node is None:
        return CheckResult(
            section="tui",
            name="tui.node",
            label="node on PATH",
            severity="fail",
            detail="node not found -- the Ink TUI subprocess can't spawn",
        )
    return CheckResult(
        section="tui",
        name="tui.node",
        label="node on PATH",
        severity="ok",
        detail=node,
    )


def _check_tui_bundle() -> CheckResult:
    """The Ink bundle is built into ``ui-tui/dist/main.js`` at
    install time. Operators editing the TUI need to ``bun run build``
    in ``ui-tui/``; without the bundle, the REPL can't launch."""
    # The bundle path is relative to the installed athena package.
    # ``athena/tui_gateway/`` knows how to find it; we just check the
    # canonical location.
    import athena

    pkg_root = Path(athena.__file__).parent.parent
    bundle = pkg_root / "ui-tui" / "dist" / "main.js"
    if not bundle.exists():
        return CheckResult(
            section="tui",
            name="tui.bundle",
            label="Ink TUI bundle",
            severity="fail",
            detail=(
                f"{bundle} missing -- "
                "run `cd ui-tui && bun run build`"
            ),
        )
    return CheckResult(
        section="tui",
        name="tui.bundle",
        label="Ink TUI bundle",
        severity="ok",
        detail=f"{bundle} ({bundle.stat().st_size} bytes)",
    )


# ── Section: crash log ──────────────────────────────────────────────


def _check_recent_crashes() -> CheckResult:
    """Count crash records from the last 7 days. Zero -> OK; any
    crashes recorded -> WARN with a count so operators triage at
    a glance. Always points at the directory."""
    from ..crash_log import recent_crashes

    recent = recent_crashes(within_days=7)
    crash_dir = Path.home() / ".athena" / "crashes"
    if not recent:
        return CheckResult(
            section="crashes",
            name="crashes.recent",
            label="Recent crashes (7d)",
            severity="ok",
            detail=f"none recorded -- log dir: {crash_dir}",
        )
    newest = recent[0]
    return CheckResult(
        section="crashes",
        name="crashes.recent",
        label="Recent crashes (7d)",
        severity="warn",
        detail=(
            f"{len(recent)} record(s); newest: {newest.name}. "
            f"Inspect: {crash_dir}"
        ),
        extra={"count": len(recent), "newest": str(newest)},
    )


# ── Section: gates / feature flags ──────────────────────────────────


def _check_godmode_gate() -> CheckResult:
    """``ATHENA_ALLOW_GODMODE`` resolves via dotenv or env. Report
    whether the gate is currently open -- not a fail either way; just
    surface the state so operators know."""
    from ..env import get_credential

    value = get_credential("ATHENA_ALLOW_GODMODE")
    if value == "1":
        return CheckResult(
            section="gates",
            name="godmode.gate",
            label="/godmode gate",
            severity="warn",
            detail=(
                "ATHENA_ALLOW_GODMODE=1 -- /godmode is unlocked. "
                "Templates weaken model safety posture."
            ),
        )
    return CheckResult(
        section="gates",
        name="godmode.gate",
        label="/godmode gate",
        severity="ok",
        detail="closed (gate requires ATHENA_ALLOW_GODMODE=1)",
    )


# ── Orchestrator ────────────────────────────────────────────────────


def run_all_checks(skip_network: bool = False) -> list[CheckResult]:
    """Run every check and return the result list. Each check is
    safe-wrapped so an unexpected exception becomes a fail row
    rather than crashing the doctor."""
    checks: list[tuple[str, Callable[[], CheckResult]]] = [
        ("Config parses", _check_config_loads),
        ("Config file present", _check_config_path_exists),
        ("Deprecated config keys", _check_deprecated_config_keys),
        ("Credential pool", _check_credentials_pool),
        ("~/.athena/.env", _check_dotenv_present),
        ("Ollama daemon reachable", _check_ollama_daemon),
        ("OpenRouter auth", lambda: _check_openrouter_auth(skip_network)),
        ("~/.athena writable", _check_athena_home_writable),
        ("node on PATH", _check_node_on_path),
        ("Ink TUI bundle", _check_tui_bundle),
        ("Recent crashes (7d)", _check_recent_crashes),
        ("/godmode gate", _check_godmode_gate),
    ]
    return [_safe(label, fn) for label, fn in checks]


def render_text_report(results: list[CheckResult]) -> str:
    """Group rows by section, render each as
    ``[STATUS] label: detail``, append a summary footer."""
    lines: list[str] = []
    last_section = ""
    for r in results:
        if r.section != last_section:
            lines.append(f"\n[{r.section}]")
            last_section = r.section
        marker = _MARKER[r.severity]
        if r.detail:
            lines.append(f"  {marker} {r.label}: {r.detail}")
        else:
            lines.append(f"  {marker} {r.label}")
    # Summary footer
    counts = {"ok": 0, "warn": 0, "fail": 0, "skip": 0}
    for r in results:
        counts[r.severity] += 1
    lines.append("")
    lines.append(
        f"summary: {counts['ok']} ok, {counts['warn']} warn, "
        f"{counts['fail']} fail, {counts['skip']} skip"
    )
    return "\n".join(lines).lstrip("\n")


def render_json_report(results: list[CheckResult]) -> str:
    """Machine-readable: one JSON object with ``checks`` and
    ``summary`` keys."""
    payload = {
        "checks": [
            {
                "section": r.section,
                "name": r.name,
                "label": r.label,
                "severity": r.severity,
                "detail": r.detail,
                "extra": r.extra,
            }
            for r in results
        ],
        "summary": {
            "ok": sum(1 for r in results if r.severity == "ok"),
            "warn": sum(1 for r in results if r.severity == "warn"),
            "fail": sum(1 for r in results if r.severity == "fail"),
            "skip": sum(1 for r in results if r.severity == "skip"),
        },
    }
    return json.dumps(payload, indent=2)


def _compute_exit_code(results: list[CheckResult], strict: bool) -> int:
    """Exit 1 on any FAIL. With ``--strict``, exit 1 on WARN too."""
    severities = {r.severity for r in results}
    if "fail" in severities:
        return 1
    if strict and "warn" in severities:
        return 1
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    results = run_all_checks(skip_network=args.no_network)
    if args.json:
        sys.stdout.write(render_json_report(results) + "\n")
    else:
        sys.stdout.write(render_text_report(results) + "\n")
    return _compute_exit_code(results, strict=args.strict)


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="athena doctor",
        description=(
            "Read-only health check: config, credentials, providers, "
            "filesystem, TUI bundle, feature gates. Exits 0 on all "
            "OK (or only warnings); 1 on any FAIL."
        ),
    )
    ap.add_argument(
        "--json",
        action="store_true",
        help="JSON output for scripting / CI.",
    )
    ap.add_argument(
        "--strict",
        action="store_true",
        help="Exit code 1 on WARN too (default: only on FAIL).",
    )
    ap.add_argument(
        "--no-network",
        action="store_true",
        help="Skip checks that probe remote endpoints.",
    )
    ap.set_defaults(handler=cmd_doctor)
    return ap


def main(argv: list[str]) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return int(args.handler(args) or 0)
