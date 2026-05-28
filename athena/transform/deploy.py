"""Ollama deployment: GGUF → ``ollama create`` → model switch.

Three operations:

- :func:`register_with_ollama` writes a Modelfile next to the GGUF and
  runs ``ollama create <name> -f Modelfile``. Returns the subprocess
  exit code.
- :func:`list_local_models` parses ``ollama list`` and returns the
  available models as a list of dicts.
- :func:`switch_model` mutates the user-level ``config.toml`` so the
  next session uses ``new_model`` by default. Sessions already in
  flight aren't affected — they bind to the model they started with.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore

import tomli_w

logger = logging.getLogger(__name__)


from collections.abc import Callable

# Type for the ``runner`` test seam — ``subprocess._SubprocessTarget`` was
# never a real CPython name; only ``from __future__ import annotations``
# was hiding the AttributeError at runtime introspection.
SubprocessRunner = Callable[..., int]


def register_with_ollama(
    gguf_path: Path,
    model_name: str,
    *,
    base_system_prompt: str | None = None,
    modelfile_path: Path | None = None,
    runner: Any | None = None,
) -> int:
    """Write a Modelfile and call ``ollama create``. Returns exit code.

    The Modelfile lives next to the GGUF unless ``modelfile_path`` is
    given. ``runner`` is a test seam mirroring the runner module.
    """
    gguf_path = Path(gguf_path)
    modelfile_path = modelfile_path or (gguf_path.parent / "Modelfile")
    body = f"FROM {gguf_path}\n"
    if base_system_prompt:
        # ``"""`` inside the system prompt would terminate the SYSTEM
        # block and let the rest of the string inject arbitrary
        # Modelfile directives (e.g. ``FROM /etc/passwd``). The
        # base_system_prompt is plumbed up from user configs and
        # migration imports where strings can originate model-side,
        # so we can't trust it to be quote-free. Reject the unsafe
        # case rather than try to escape — there's no documented
        # escape syntax in the Modelfile grammar.
        if '"""' in base_system_prompt:
            raise ValueError(
                "base_system_prompt must not contain triple double-quotes "
                "(would terminate the Modelfile SYSTEM block)"
            )
        body += f'SYSTEM """{base_system_prompt}"""\n'
    modelfile_path.parent.mkdir(parents=True, exist_ok=True)
    modelfile_path.write_text(body, encoding="utf-8")

    cmd = ["ollama", "create", model_name, "-f", str(modelfile_path)]
    logger.info("registering with Ollama: %s", " ".join(cmd))
    call = runner or subprocess.call
    return call(cmd)


def list_local_models(*, runner: Any | None = None) -> list[dict[str, str]]:
    """Return parsed ``ollama list`` output.

    ``ollama list`` writes a header row followed by ``NAME  ID  SIZE
    MODIFIED`` columns. We split on runs of whitespace and join trailing
    fields back into a single ``modified_at`` so e.g. ``"2 days ago"``
    survives. On any failure (binary missing, non-zero exit), returns
    an empty list with a logged warning.
    """
    call = runner or _run_capture
    try:
        rc, out = call(["ollama", "list"])
    except FileNotFoundError:
        logger.warning("ollama binary not on PATH")
        return []
    if rc != 0:
        logger.warning("ollama list exited %s", rc)
        return []
    lines = [line for line in out.splitlines() if line.strip()]
    if not lines:
        return []
    # Drop header.
    lines = lines[1:]
    models: list[dict[str, str]] = []
    for line in lines:
        parts = line.split()
        if len(parts) < 3:
            continue
        name = parts[0]
        ident = parts[1]
        size = parts[2]
        modified = " ".join(parts[3:]) if len(parts) > 3 else ""
        models.append(
            {
                "name": name,
                "id": ident,
                "size": size,
                "modified_at": modified,
            }
        )
    return models


def switch_model(config_path: Path, new_model: str) -> None:
    """Update ``config_path``'s ``model`` key to ``new_model``.

    Creates the file with just the ``model`` key if it doesn't yet
    exist. Otherwise reads → mutates → writes via ``tomli_w`` (no
    in-place mutation — TOML formatting / comments will be lost; the
    file is machine-managed at this point).
    """
    config_path = Path(config_path)
    if config_path.exists():
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
    else:
        data = {}
    data["model"] = new_model
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "wb") as f:
        tomli_w.dump(data, f)


def show_model(model: str, *, runner: Any | None = None) -> str:
    """Return raw ``ollama show <model>`` stdout, or an empty string on failure."""
    call = runner or _run_capture
    try:
        rc, out = call(["ollama", "show", model])
    except FileNotFoundError:
        return ""
    return out if rc == 0 else ""


def ensure_ollama() -> bool:
    """Return True iff ``ollama`` is on PATH."""
    return shutil.which("ollama") is not None


def _run_capture(cmd: list[str]) -> tuple[int, str]:
    """Default capture runner. Returns (exit_code, stdout-text)."""
    completed = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return completed.returncode, completed.stdout or ""
