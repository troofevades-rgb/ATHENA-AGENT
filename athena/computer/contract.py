"""Desktop backend contract + action types (T6-04.1).

Pure data — no I/O at import, no OS calls. The platform
backends (T6-04.3 / T6-04.5) implement the protocol; the
permission gate (T6-04.1) and the loop (T6-04.5) consume
:class:`Action` values.

Tiering vocabulary lives here so the safety-boundary tests
(``tests/computer/test_permission.py``) import only this module
+ ``permission`` — no OS, no asyncio, no model dependency.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Literal, Optional, Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# Action + tier vocabulary
# ---------------------------------------------------------------------------


ActionType = Literal[
    "screenshot",
    "move",
    "click",
    "double_click",
    "right_click",
    "type",
    "key",
    "scroll",
    "drag",
]


Tier = Literal["observe", "input", "destructive"]


_INPUT_ACTION_TYPES: frozenset[str] = frozenset(
    (
        "move",
        "click",
        "double_click",
        "right_click",
        "type",
        "key",
        "scroll",
        "drag",
    )
)


@dataclasses.dataclass
class Action:
    """One proposed (or executed) desktop action.

    Fields:

      ``type``         the verb
      ``coords``       (x, y) target pixel for clicks / moves / drags
      ``text``         text to type (type) or scroll delta description
      ``key``          key name for ``key`` actions (e.g. "Return")
      ``target_desc``  label / role / accessibility name of the
                       target element when readable — the classifier
                       reads this to decide destructive vs input
      ``app``          active app name for the allow/denylist gate
    """

    type: ActionType
    coords: tuple[int, int] | None = None
    text: str | None = None
    key: str | None = None
    target_desc: str | None = None
    app: str | None = None

    @property
    def is_input(self) -> bool:
        """True iff this action mutates the OS / world. ``screenshot``
        is the only non-input verb today; future read-only actions
        (e.g. ``a11y_query``) would add here."""
        return self.type in _INPUT_ACTION_TYPES

    def describe(self) -> str:
        """Human-readable preview for confirmation prompts. Never
        includes typed-text content for actions whose ``text`` is
        the model's proposed payload — confirmation should be on
        the *action*, not show a 5 KB typed string in the prompt."""
        bits: list[str] = [self.type]
        if self.target_desc:
            bits.append(f"on {self.target_desc!r}")
        if self.coords is not None:
            bits.append(f"at ({self.coords[0]}, {self.coords[1]})")
        if self.app:
            bits.append(f"in {self.app}")
        if self.type == "type" and self.text:
            preview = self.text[:40].replace("\n", " ")
            bits.append(f"(text: {preview!r}{'...' if len(self.text) > 40 else ''})")
        elif self.type == "key" and self.key:
            bits.append(f"(key: {self.key})")
        return " ".join(bits)


@dataclasses.dataclass
class Screenshot:
    """One screen capture passed between backend + vision + loop.

    ``scale`` accounts for retina / fractional DPI — a click at
    logical (100, 100) on a 2× scaled display maps to physical
    pixel (200, 200). The loop's coordinate mapper consumes this.
    """

    png_bytes: bytes
    width: int
    height: int
    scale: float = 1.0


# ---------------------------------------------------------------------------
# Backend protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class DesktopBackend(Protocol):
    """Protocol every platform backend implements.

    Observe surface (T6-04.3) — implemented before any input:
      ``is_available``       can this backend run on the host?
      ``supports``           which ActionTypes are wired
      ``screenshot``         capture the active display
      ``active_app``         best-effort current foreground app
      ``accessibility_tree`` optional structured UI tree;
                             improves classification reliability

    Input surface (T6-04.5) — implemented only after the gate +
    kill switch land:
      ``perform``            one call site only, post-gate
    """

    name: str

    def is_available(self) -> bool: ...
    def supports(self) -> list[ActionType]: ...
    def screenshot(self) -> Screenshot: ...
    def active_app(self) -> str | None: ...
    def accessibility_tree(self) -> dict[str, Any] | None: ...
    def perform(self, action: Action) -> None: ...
