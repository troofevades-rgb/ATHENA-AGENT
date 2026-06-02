"""Per-provider credential pool with automatic rotation on 429.

Credentials are PROFILE-SCOPED: each profile reads only
``<profile_dir>/credentials.json``, so ``--profile experimental`` can
never spend the ``default`` profile's keys. The ``default`` profile is
seeded once (copy) from the legacy global ``~/.athena/credentials.json``
the first time it's accessed; every other profile starts empty by
design. Use :func:`profile_pool` (or :func:`global_pool`, which targets
the active profile) — both are cached per profile. Tests construct their
own pool with a tmp path.

Loaded from the profile's ``credentials.json`` on init. Each provider name
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
"""

from __future__ import annotations

import json
import logging
import shutil
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..safety.secure_files import ensure_secure_dir, secure_write_json

logger = logging.getLogger(__name__)

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

    def rotate_to_next(self, provider_name: str) -> Credential | None:
        """Move the round-robin position past the current credential
        and return the next non-cooldown credential (T2-03.8).

        Used by ``retry_utils.with_retry`` as the
        ``on_rotate_credential`` callback when the classifier returns
        ``ROTATE_CREDENTIAL`` (e.g. repeated 429s on one key).

        Returns the new active ``Credential`` if rotation found a
        usable alternative, or ``None`` when:
          - the provider has fewer than two credentials,
          - or every other credential is in cooldown.

        After a successful ``get()`` the pool's ``_next_idx`` already
        points one slot past the just-returned credential, so calling
        ``get()`` again naturally hands back a DIFFERENT credential
        when one is available (and the same one back when only one
        remains usable). This method layers a "must be different from
        last-returned" guard on top of ``get()`` to avoid the
        single-non-cooldown edge case.
        """
        with self._lock:
            creds = self._creds.get(provider_name) or []
            if len(creds) < 2:
                return None
            now = datetime.now(timezone.utc)
            # Identify the just-returned credential: it's the one
            # immediately before _next_idx.
            n = len(creds)
            next_idx = self._next_idx.get(provider_name, 0) % n
            last_pos = (next_idx - 1) % n
            last_cred = creds[last_pos]
            # Walk forward looking for a non-cooldown credential whose
            # key differs from last_cred.
            for offset in range(n):
                pos = (next_idx + offset) % n
                cred = creds[pos]
                if cred.key == last_cred.key:
                    continue
                if self._in_cooldown(cred, now):
                    continue
                cred.last_used_at = now
                self._next_idx[provider_name] = (pos + 1) % n
                self._save()
                return cred
            return None

    def get_credential_rate_state(self) -> dict[str, dict[str, dict[str, Any]]]:
        """Per-(provider, credential) cooldown + 429 state (T2-02.7).

        Shape::

            {
                "anthropic": {
                    "...abcd": {
                        "in_cooldown": False,
                        "last_429_at": None,
                        "fail_count": 0,
                        "last_used_at": "2026-05-19T...",
                    },
                    ...
                },
                ...
            }

        The credential keys are the same redacted ``...<last-4>`` form
        the provider uses for its rate-limit tracker dict, so consumers
        can correlate the two surfaces. Rate-limit tracker state itself
        lives on the provider (per-request), not on the credential — so
        this method reports the pool's view (cooldown / fail counts).
        T2-03's error classifier joins the two views.
        """
        with self._lock:
            out: dict[str, dict[str, dict[str, Any]]] = {}
            for provider_name, bucket in self._creds.items():
                bucket_state: dict[str, dict[str, Any]] = {}
                for cred in bucket:
                    suffix = cred.key[-4:] if len(cred.key) >= 4 else cred.key
                    bucket_state[f"...{suffix}"] = {
                        "in_cooldown": cred.last_429_at is not None,
                        "last_429_at": (cred.last_429_at.isoformat() if cred.last_429_at else None),
                        "fail_count": cred.fail_count,
                        "last_used_at": (
                            cred.last_used_at.isoformat() if cred.last_used_at else None
                        ),
                    }
                if bucket_state:
                    out[provider_name] = bucket_state
            return out

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
        """Atomic O_EXCL 0o600 write via athena.safety.secure_files."""
        ensure_secure_dir(self._path.parent)
        payload = {name: [c.to_dict() for c in bucket] for name, bucket in self._creds.items()}
        secure_write_json(self._path, payload)


# Per-profile pool cache. Pools are constructed lazily on first access
# (so tests that monkeypatch CONFIG_DIR can do so without racing the
# import) and cached by profile name — credentials are profile-scoped.
_PROFILE_POOLS: dict[str, CredentialPool] = {}
_POOL_LOCK = threading.Lock()


def _seed_default_from_global_if_needed(path: Path) -> None:
    """One-time, idempotent seed of the ``default`` profile's
    credentials from the legacy global ``~/.athena/credentials.json``.

    Credentials are now profile-scoped (strict isolation: each profile
    reads only its own file). To avoid stranding existing users' keys
    when the read path moves under the profile, copy the legacy global
    file into the default profile the first time it's accessed and the
    profile file doesn't exist yet. Copy — not move — so we never delete
    the user's existing file or break external tooling that still reads
    it. Default profile ONLY; other profiles start empty by design so a
    ``--profile x`` switch can never reuse another profile's keys.
    """
    from ..config import CONFIG_DIR

    legacy = CONFIG_DIR / "credentials.json"
    if path.exists() or not legacy.exists() or legacy.resolve() == path.resolve():
        return
    try:
        ensure_secure_dir(path.parent)
        shutil.copy2(str(legacy), str(path))
        logger.info("seeded default-profile credentials from %s", legacy)
    except OSError:
        logger.warning(
            "failed to seed default-profile credentials from global file",
            exc_info=True,
        )


def profile_pool(profile: str | None = None) -> CredentialPool:
    """Return the :class:`CredentialPool` for ``profile``.

    ``profile=None`` resolves the active profile (CLI/env/active-file/
    config, via :func:`athena.profiles.resolution.resolve_active_profile`).
    Each profile reads ONLY ``<profile_dir>/credentials.json`` — strict
    isolation, so switching profiles can never reuse another profile's
    keys. The ``default`` profile is seeded once from the legacy global
    file; other profiles start empty. Pools are cached per profile.
    """
    from ..config import profile_dir
    from ..profiles.resolution import DEFAULT_PROFILE, resolve_active_profile

    name = profile or resolve_active_profile()
    with _POOL_LOCK:
        cached = _PROFILE_POOLS.get(name)
        if cached is not None:
            return cached
        path = profile_dir(name) / "credentials.json"
        if name == DEFAULT_PROFILE:
            _seed_default_from_global_if_needed(path)
        pool = CredentialPool(path)
        _PROFILE_POOLS[name] = pool
        return pool


def global_pool() -> CredentialPool:
    """Return the credential pool for the ACTIVE profile.

    Back-compat shim over :func:`profile_pool` for the many no-argument
    call sites. Prefer ``profile_pool(cfg.profile)`` where a ``Config``
    is in hand so the pool can't diverge from the agent's profile.
    """
    return profile_pool(None)


def reset_global_pool() -> None:
    """Drop every cached per-profile pool. Test affordance — call this
    after monkeypatching CONFIG_DIR so the next pool access rebuilds
    against the new path."""
    with _POOL_LOCK:
        _PROFILE_POOLS.clear()
