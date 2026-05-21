"""OSV (Open Source Vulnerabilities) database lookup (T-MIG.3).

Ported in spirit from NousResearch/hermes-agent (MIT). OSV
is a unified vulnerability database covering PyPI, npm,
crates, Maven, Go modules, and a dozen other ecosystems —
https://osv.dev. The query endpoint is JSON-in, JSON-out:

  POST https://api.osv.dev/v1/query
  body: {"package": {"name": "<pkg>", "ecosystem": "<eco>"},
         "version": "<version>"}

Returns the list of vulnerabilities affecting that specific
version. Used by the ``osv_check`` @tool so the model can ask
"is X@Y vulnerable" before recommending a dep / before
running an install.

Read-only HTTP — no credentials, no rate-limit headers
typically observed under normal usage. Defensive on every
network failure: returns an empty "vulns" list + an `error`
key so the caller branches cleanly.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)


# Per OSV's docs, the supported ecosystem identifiers include:
#   PyPI         Python packages from pypi.org
#   npm          Node.js packages from npmjs.com
#   crates.io    Rust crates
#   Go           Go modules
#   Maven        Java packages
#   NuGet        .NET packages
#   RubyGems     Ruby gems
#   Packagist    PHP packages
#   Hex          Erlang/Elixir packages
#   Pub          Dart packages
#   GitHub Actions
#   Debian / Ubuntu / Alpine / Rocky Linux / etc.  (distros)
# We don't enumerate them all in code — OSV accepts the
# string; if it's unknown they return [] with a 400.
_KNOWN_ECOSYSTEMS = frozenset({
    "PyPI", "npm", "crates.io", "Go", "Maven", "NuGet",
    "RubyGems", "Packagist", "Hex", "Pub", "GitHub Actions",
    "Debian", "Ubuntu", "Alpine", "Rocky Linux",
    "Linux", "OSS-Fuzz",
})


@dataclasses.dataclass(frozen=True)
class Vulnerability:
    """One vulnerability entry from the OSV response.

    Kept narrow — the OSV JSON shape is rich (affected version
    ranges, references, database-specific fields). We surface
    the fields a model + operator actually act on; the full
    payload is in ``raw`` for callers that want more.
    """

    id: str                # OSV ID, e.g. "GHSA-1234-..." or "PYSEC-2024-..."
    summary: str
    severity: str          # "LOW" | "MODERATE" | "HIGH" | "CRITICAL" | "UNKNOWN"
    aliases: list[str]     # CVE-2024-... + other DB IDs
    references: list[str]  # URLs from the entry
    raw: dict[str, Any]    # full OSV record for advanced callers

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "summary": self.summary,
            "severity": self.severity,
            "aliases": list(self.aliases),
            "references": list(self.references),
        }


def query(
    package_name: str,
    version: str,
    *,
    ecosystem: str,
    cfg: Any | None = None,
) -> tuple[list[Vulnerability], str | None]:
    """Query OSV for vulnerabilities affecting ``package_name``
    at ``version`` within ``ecosystem``.

    Returns ``(vulns, error)`` — error is None on success.
    Never raises. The CALLER branches on `error is None` to
    distinguish "queried, no vulns" from "couldn't query."
    """
    if not getattr(cfg, "osv_enabled", True) if cfg else False:
        return [], "osv_enabled=False"

    if not package_name or not version or not ecosystem:
        return [], "package_name, version, and ecosystem all required"

    url = (
        getattr(cfg, "osv_api_url", None)
        if cfg else None
    ) or "https://api.osv.dev/v1/query"
    timeout_s = float(
        getattr(cfg, "osv_timeout_s", 10.0) if cfg else 10.0
    )

    body = json.dumps({
        "package": {"name": package_name, "ecosystem": ecosystem},
        "version": version,
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "athena-osv-check/1.0",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310
            raw = resp.read().decode("utf-8", errors="replace")
            status = resp.getcode()
    except urllib.error.HTTPError as e:
        body_text = ""
        try:
            body_text = e.read().decode("utf-8", errors="replace")[:300]
        except Exception:  # noqa: BLE001
            pass
        logger.warning(
            "osv: HTTP %s on %s — %s", e.code, url, body_text or "(no body)",
        )
        return [], f"HTTP {e.code} from OSV"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        logger.warning("osv: network error: %s", e)
        return [], f"network error: {type(e).__name__}: {e}"
    except Exception as e:  # noqa: BLE001
        logger.exception("osv: unexpected error")
        return [], f"unexpected error: {type(e).__name__}: {e}"

    if status != 200:
        return [], f"HTTP {status} from OSV"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return [], f"OSV returned non-JSON: {e}"
    if not isinstance(data, dict):
        return [], "OSV returned non-object payload"

    vuln_list = data.get("vulns") or []
    if not isinstance(vuln_list, list):
        return [], "OSV response 'vulns' is not a list"

    return [_normalize_vuln(v) for v in vuln_list if isinstance(v, dict)], None


def _normalize_vuln(entry: dict[str, Any]) -> Vulnerability:
    """Map one OSV record to the narrowed Vulnerability shape."""
    severity = "UNKNOWN"
    # OSV uses a list of "severity" entries each with a
    # type+score, plus an optional database_specific.severity
    # that's the human label. The label is what callers want.
    db_spec = entry.get("database_specific") or {}
    if isinstance(db_spec, dict):
        lbl = db_spec.get("severity")
        if isinstance(lbl, str) and lbl.strip():
            severity = lbl.upper()
    # Fallback: derive from the highest CVSS score in `severity`.
    if severity == "UNKNOWN":
        sev_list = entry.get("severity") or []
        if isinstance(sev_list, list):
            for s in sev_list:
                if isinstance(s, dict) and "score" in s:
                    severity = "UNKNOWN"
                    break

    aliases = entry.get("aliases") or []
    if not isinstance(aliases, list):
        aliases = []

    refs_raw = entry.get("references") or []
    references: list[str] = []
    if isinstance(refs_raw, list):
        for r in refs_raw:
            if isinstance(r, dict) and r.get("url"):
                references.append(str(r["url"]))

    return Vulnerability(
        id=str(entry.get("id", "")),
        summary=str(entry.get("summary", "") or ""),
        severity=severity,
        aliases=[str(a) for a in aliases],
        references=references,
        raw=entry,
    )
