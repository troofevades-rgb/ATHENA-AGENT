"""Per-provider credential pool with automatic rotation on 429.

Loaded from ``~/.athena/credentials.json`` on init. Each provider name
maps to an ordered list of :class:`Credential` records; :meth:`get`
returns the next non-cooldown credential round-robin. When a provider
sees a 429 it calls :meth:`mark_429` which stamps ``last_429_at`` on
that credential — the pool will skip it until ``cooldown_seconds``
elapses.

Persistence: ``_save()`` writes the JSON file atomically (tmp-then-
rename) so a crashed process can't leave a half-written file. Keys are
stored as-is on disk; the file should have user-only permissions in
production. ``list_credentials()`` returns a redacted view (last 4
chars only) safe for human display.

Thread safety: one lock guards every mutation and every read of the
internal dicts. Round-robin position is per-provider so two threads
pulling credentials don't both get the same one.

A module-level :data:`GLOBAL_CREDENTIAL_POOL` is the singleton most
callers reach for. Tests construct their own pool with a tmp path.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_DEFAULT_COOLDOWN = 60  # seconds


@dataclass
class Credential:
    """One API key for one provider.

    ``label`` is free-form (``"personal"``, ``"work"``, ``"team-a"``)
    so the user can target a specific credential when removing.
    ``last_429_at`` is set by :meth:`CredentialPool.mark_429`;
    ``fail_count`` is bumped by :meth:`mark_failure` (auth errors,
    parse errors, anything non-429 that suggests the credential is
    broken).
    """

    key: str
    label: str = ""
    last_429_at: datetime | None = None
    fail_count: int = 0
    last_used_at: datetime | None = None

    # ---- (de)serialization ----

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for k in ("last_429_at", "last_used_at"):
            v = d.get(k)
            if isinstance(v, datetime):
                d[k] = v.isoformat()
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Credential:
        kwargs: dict[str, Any] = dict(d)
        for k in ("last_429_at", "last_used_at"):
            v = kwargs.get(k)
            if isinstance(v, str):
                try:
                    kwargs[k] = datetime.fromisoformat(v)
                except ValueError:
                    kwargs[k] = None
            elif v is not None and not isinstance(v, datetime):
                kwargs[k] = None
        return cls(**kwargs)

    # ---- Display ----

    def redacted(self) -> dict[str, Any]:
        """Display-safe dict — last 4 chars of the key only."""
        suffix = self.key[-4:] if len(self.key) >= 4 else self.key
        return {
            "key_suffix": f"...{suffix}",
            "label": self.label,
            "fail_count": self.fail_count,
            "last_used_at": (self.last_used_at.isoformat() if self.last_used_at else None),
            "in_cooldown": self.last_429_at is not None,
            "last_429_at": (self.last_429_at.isoformat() if self.last_429_at else None),
        }


class CredentialPool:
    """Thread-safe per-provider credential rotation with cooldown."""

    def __init__(
        self,
        config_path: Path,
        *,
        cooldown_seconds: int = _DEFAULT_COOLDOWN,
    ):
        self._path = Path(config_path)
        self._cooldown = timedelta(seconds=cooldown_seconds)
        self._lock = threading.Lock()
        self._creds: dict[str, list[Credential]] = {}
        self._next_idx: dict[str, int] = {}
        self._load()

    # ---- Public API --------------------------------------------------

    def get(self, provider_name: str) -> Credential | None:
        """Return the next available credential for ``provider_name``.

        Round-robin: starts at the position after the last credential
        returned; skips any credential whose 429 cooldown hasn't
        elapsed. If every credential is in cooldown, returns ``None``.
        On hit, stamps ``last_used_at`` and advances the index.
        """
        with self._lock:
            creds = self._creds.get(provider_name) or []
            if not creds:
                return None
            now = datetime.now(timezone.utc)
            n = len(creds)
            start = self._next_idx.get(provider_name, 0) % n
            for offset in range(n):
                pos = (start + offset) % n
                cred = creds[pos]
                if not self._in_cooldown(cred, now):
                    cred.last_used_at = now
                    self._next_idx[provider_name] = (pos + 1) % n
                    self._save()
                    return cred
            return None  # all in cooldown

    def mark_429(self, provider_name: str, key: str) -> bool:
        """Mark a credential as rate-limited. Returns True if found."""
        with self._lock:
            cred = self._find_locked(provider_name, key)
            if cred is None:
                return False
            cred.last_429_at = datetime.now(timezone.utc)
            self._save()
            return True

    def mark_failure(self, provider_name: str, key: str) -> bool:
        """Bump fail_count on a credential. Returns True if found."""
        with self._lock:
            cred = self._find_locked(provider_name, key)
            if cred is None:
                return False
            cred.fail_count += 1
            self._save()
            return True

    def clear_cooldown(self, provider_name: str, key: str) -> bool:
        """Manually clear a credential's cooldown stamp. Test affordance
        and an escape hatch for human operators."""
        with self._lock:
            cred = self._find_locked(provider_name, key)
            if cred is None:
                return False
            cred.last_429_at = None
            self._save()
            return True

    def add_credential(self, provider_name: str, cred: Credential) -> None:
        """Append a new credential. Duplicates by exact-key match are
        ignored (idempotent add)."""
        with self._lock:
            bucket = self._creds.setdefault(provider_name, [])
            if any(c.key == cred.key for c in bucket):
                return
            bucket.append(cred)
            self._save()

    def remove_credential(self, provider_name: str, key_or_match: str) -> int:
        """Remove credentials matching ``key_or_match``.

        Match priority: exact key first, then prefix, then suffix.
        Each step only succeeds if it matches exactly one credential
        (ambiguous matches at any step bail). A leading ``...``
        (the listing prefix) is stripped before matching, so the user
        can copy the display form (``...ttWN``) verbatim. Returns the
        number removed (0 or 1).
        """
        with self._lock:
            bucket = self._creds.get(provider_name) or []
            if not bucket:
                return 0
            needle = key_or_match.removeprefix("...")
            # Exact match wins outright.
            exact = [c for c in bucket if c.key == needle]
            if exact:
                target = exact[0]
            else:
                # Prefix match.
                matches = [c for c in bucket if c.key.startswith(needle)]
                if not matches:
                    # Suffix match — supports the display form.
                    matches = [c for c in bucket if c.key.endswith(needle)]
                if len(matches) != 1:
                    return 0
                target = matches[0]
            bucket.remove(target)
            self._save()
            return 1

    def list_credentials(self, provider_name: str | None = None) -> dict[str, list[dict[str, Any]]]:
        """Return a redacted view of every credential.

        Without ``provider_name``: ``{provider: [{...redacted}]}`` for
        every provider with at least one credential. With one: just
        that provider's bucket, still wrapped in the same dict shape.
        """
        with self._lock:
            if provider_name is not None:
                bucket = self._creds.get(provider_name) or []
                return {provider_name: [c.redacted() for c in bucket]}
            return {
                name: [c.redacted() for c in bucket] for name, bucket in sorted(self._creds.items())
            }

    def providers(self) -> list[str]:
        """Names of every provider with at least one credential, sorted."""
        with self._lock:
            return sorted(name for name, bucket in self._creds.items() if bucket)

    # ---- Internals ---------------------------------------------------

    def _in_cooldown(self, cred: Credential, now: datetime) -> bool:
        if cred.last_429_at is None:
            return False
        return (now - cred.last_429_at) < self._cooldown

    def _find_locked(self, provider_name: str, key: str) -> Credential | None:
        bucket = self._creds.get(provider_name) or []
        for cred in bucket:
            if cred.key == key:
                return cred
        return None

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(raw, dict):
            return
        creds: dict[str, list[Credential]] = {}
        for name, items in raw.items():
            if not isinstance(items, list):
                continue
            bucket: list[Credential] = []
            for it in items:
                if isinstance(it, dict) and "key" in it:
                    try:
                        bucket.append(Credential.from_dict(it))
                    except TypeError:
                        continue
            if bucket:
                creds[name] = bucket
        self._creds = creds

    def _save(self) -> None:
        """Atomic write: tmp-then-rename so a crash mid-write can't
        leave a half-written file."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {name: [c.to_dict() for c in bucket] for name, bucket in self._creds.items()}
        # tempfile in the same directory so rename is atomic on POSIX
        # and Windows alike.
        fd, tmp = tempfile.mkstemp(
            prefix=".credentials-", suffix=".json", dir=str(self._path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, sort_keys=True)
                f.write("\n")
            os.replace(tmp, self._path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


# Module-level singleton. Constructed lazily on first access so tests
# that monkeypatch Path.home() / CONFIG_DIR can do so without racing
# the import.
_GLOBAL_POOL: CredentialPool | None = None
_GLOBAL_LOCK = threading.Lock()


def global_pool() -> CredentialPool:
    """Return the lazily-constructed global :class:`CredentialPool`.

    Reads from ``CONFIG_DIR / "credentials.json"``. Most callers use
    this; tests construct their own pool with a tmp path.
    """
    global _GLOBAL_POOL
    with _GLOBAL_LOCK:
        if _GLOBAL_POOL is None:
            from ..config import CONFIG_DIR

            _GLOBAL_POOL = CredentialPool(CONFIG_DIR / "credentials.json")
        return _GLOBAL_POOL


def reset_global_pool() -> None:
    """Drop the cached global pool. Test affordance — call this after
    monkeypatching CONFIG_DIR so the next ``global_pool()`` rebuilds
    against the new path."""
    global _GLOBAL_POOL
    with _GLOBAL_LOCK:
        _GLOBAL_POOL = None
