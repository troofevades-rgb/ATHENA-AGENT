"""Windows desktop backend — OBSERVE surface only (T6-04.3).

Implements the observe half of :class:`DesktopBackend` using
stdlib only (``ctypes`` + the built-in BMP wrapping logic).
No third-party deps required for the observe path:

  screenshot()        BitBlt of the desktop DC → BMP bytes →
                      PNG via stdlib (the simplest portable
                      route on Windows without Pillow)
  active_app()        GetForegroundWindow + GetWindowText
  accessibility_tree() None (would require pywinauto / uiautomation;
                      callers fall back to vision-on-screenshot)
  supports()          ["screenshot"] in T6-04.3; T6-04.5 extends
  perform()           NotImplementedError until T6-04.5

The actual click/type/key/scroll path lands in T6-04.5 with
``user32.SendInput``. Until then the backend is observe-only
and ``perform`` raises — there is literally no way for the
agent to drive input via this backend.

Where the platform supports a richer accessibility tree
(UIAutomation), a future enhancement adds it via an optional
``pywin32`` / ``uiautomation`` import. The classifier already
treats unreadable elements as destructive (T6-04.1) so the
absence of a11y doesn't unsafe the gate — it just means more
prompts.
"""

from __future__ import annotations

import ctypes
import logging
import struct
import sys
from ctypes import wintypes
from typing import Optional

from ..contract import Action, ActionType, Screenshot

logger = logging.getLogger(__name__)


_SUPPORTED_OBSERVE: list[ActionType] = ["screenshot"]
# T6-04.5 input verbs wired below via SendInput.
_SUPPORTED_INPUT: list[ActionType] = [
    "move",
    "click",
    "double_click",
    "right_click",
    "type",
    "key",
    "scroll",
]


class WindowsBackend:
    """Observe-only Windows backend. Input lands in T6-04.5."""

    name: str = "windows"

    def is_available(self) -> bool:
        """Win32 APIs reachable? Returns False on every non-
        Windows host so cross-platform CI doesn't try to use
        this backend."""
        if sys.platform != "win32":
            return False
        try:
            ctypes.windll.user32  # noqa: B018 — attribute access probes
        except Exception:  # noqa: BLE001
            return False
        return True

    def supports(self) -> list[ActionType]:
        return list(_SUPPORTED_OBSERVE) + list(_SUPPORTED_INPUT)

    # ------------------------------------------------------------------
    # Observe surface
    # ------------------------------------------------------------------

    def screenshot(self) -> Screenshot:
        """Capture the virtual screen (all monitors) to a BMP
        blob then wrap it in a minimal PNG container. Returns
        a :class:`Screenshot` with the byte payload + geometry.

        Implementation notes:
        - Uses ``BitBlt`` from the desktop DC, the standard
          Windows screenshot recipe.
        - Returns BMP bytes inside Screenshot.png_bytes for the
          first release. Callers that need true PNG can decode
          via stdlib (PIL not required) — flagged in the type
          name as "png_bytes" for the eventual conversion, but
          docs are explicit about the current shape.
        - Scale factor read from the per-monitor DPI to map
          logical coordinates → physical pixels at perform()
          time (T6-04.5).
        """
        if not self.is_available():
            raise RuntimeError("windows backend unavailable on this host")

        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32

        # Per-monitor DPI: ask user32 once + record the scale so
        # the loop can map logical coordinates to physical
        # pixels. Falls back to 1.0 on hosts that don't expose
        # the API (Windows 7 / earlier).
        scale = self._dpi_scale()

        # Virtual screen geometry covers every monitor.
        SM_XVIRTUALSCREEN = 76
        SM_YVIRTUALSCREEN = 77
        SM_CXVIRTUALSCREEN = 78
        SM_CYVIRTUALSCREEN = 79
        x = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        y = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        width = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
        height = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)

        # Desktop DC, compatible DC, compatible bitmap.
        hdc_screen = user32.GetDC(None)
        if not hdc_screen:
            raise RuntimeError("GetDC failed")
        try:
            hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
            hbm = gdi32.CreateCompatibleBitmap(hdc_screen, width, height)
            try:
                gdi32.SelectObject(hdc_mem, hbm)
                SRCCOPY = 0x00CC0020
                ok = gdi32.BitBlt(
                    hdc_mem, 0, 0, width, height,
                    hdc_screen, x, y, SRCCOPY,
                )
                if not ok:
                    raise RuntimeError("BitBlt failed")
                bmp_bytes = _hbitmap_to_bmp(hbm, width, height, gdi32)
            finally:
                gdi32.DeleteObject(hbm)
                gdi32.DeleteDC(hdc_mem)
        finally:
            user32.ReleaseDC(None, hdc_screen)

        return Screenshot(
            png_bytes=bmp_bytes,
            width=width,
            height=height,
            scale=scale,
        )

    def active_app(self) -> Optional[str]:
        """Return the foreground window's title. Best-effort —
        empty string when no foreground window, None on error."""
        if not self.is_available():
            return None
        try:
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return None
            # GetWindowTextW returns the UTF-16 title; we
            # allocate a generous buffer.
            length = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value.strip()
            return title or None
        except Exception as e:  # noqa: BLE001
            logger.debug("active_app() failed: %s", e)
            return None

    def accessibility_tree(self) -> Optional[dict]:
        """Not implemented on Windows without an optional
        ``uiautomation`` / ``pywin32`` dep. Returning None means
        the classifier (T6-04.1) treats unreadable elements as
        destructive — the safe default."""
        return None

    # ------------------------------------------------------------------
    # Input surface — NOT IMPLEMENTED until T6-04.5
    # ------------------------------------------------------------------

    def perform(self, action: Action) -> None:
        """Perform an input action via Win32 SendInput (T6-04.5).

        The caller MUST go through the loop's
        :class:`PermissionGate` first — this method assumes the
        action was already approved. The loop is the only call
        site in athena.

        Coordinates here are SCREEN PIXELS (not normalised);
        the loop's :func:`map_coords` already clamped them.

        Unsupported verbs raise ``NotImplementedError`` so the
        caller surfaces the gap rather than silently no-oping.
        """
        if not self.is_available():
            raise RuntimeError("windows backend unavailable on this host")

        if action.type == "move":
            _send_mouse_move(*_require_coords(action))
        elif action.type == "click":
            _send_mouse_click(*_require_coords(action), button="left")
        elif action.type == "double_click":
            _send_mouse_click(*_require_coords(action), button="left")
            _send_mouse_click(*_require_coords(action), button="left")
        elif action.type == "right_click":
            _send_mouse_click(*_require_coords(action), button="right")
        elif action.type == "type":
            _send_text(action.text or "")
        elif action.type == "key":
            _send_key(action.key or "")
        elif action.type == "scroll":
            # text is "up"/"down" + optional amount; default 3
            # wheel clicks per scroll.
            direction = (action.text or "down").lower()
            _send_scroll(direction)
        else:
            raise NotImplementedError(
                f"windows backend does not implement {action.type!r} "
                "(drag is intentionally composed from primitives)"
            )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _dpi_scale(self) -> float:
        """Return the primary display's logical → physical scale
        factor. Defaults to 1.0 on hosts where the DPI API isn't
        available."""
        try:
            # GetDpiForSystem on Win10+ returns the system DPI;
            # 96 is the 1.0 baseline.
            user32 = ctypes.windll.user32
            dpi = user32.GetDpiForSystem()
            return float(dpi) / 96.0 if dpi else 1.0
        except (AttributeError, OSError):
            return 1.0


# ---------------------------------------------------------------------------
# Helpers — BMP wrapping
# ---------------------------------------------------------------------------


def _hbitmap_to_bmp(hbm: int, width: int, height: int, gdi32) -> bytes:
    """Extract pixel bytes from an HBITMAP + wrap with a minimal
    BMP header. Returned bytes are a valid BMP that any image
    library (or the OS preview) can read."""
    # 32-bit BI_RGB bitmap. Row stride is width * 4 bytes
    # (top-down rows when biHeight is negative).
    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [
            ("bmiHeader", BITMAPINFOHEADER),
            ("bmiColors", wintypes.DWORD * 3),
        ]

    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = width
    bmi.bmiHeader.biHeight = -height  # top-down
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = 0  # BI_RGB

    pixel_count = width * height * 4
    buf = (ctypes.c_ubyte * pixel_count)()
    # GetDC(NULL) returns a screen DC that we MUST release; the prior
    # code passed it inline and never freed it, leaking one user-object
    # DC per screenshot. Windows caps per-process user DCs around 10k,
    # so a long-running computer-use loop eventually started silently
    # failing screenshots (BitBlt/GetDIBits would return 0).
    screen_dc = ctypes.windll.user32.GetDC(None)
    try:
        rows = gdi32.GetDIBits(
            screen_dc,
            hbm,
            0,
            height,
            ctypes.byref(buf),
            ctypes.byref(bmi),
            0,
        )
    finally:
        ctypes.windll.user32.ReleaseDC(None, screen_dc)
    if not rows:
        raise RuntimeError("GetDIBits failed")

    # Build the BMP file: 14-byte file header + 40-byte info
    # header + pixel array.
    pixel_array = bytes(buf)
    file_size = 14 + 40 + len(pixel_array)
    bmp = struct.pack("<2sIHHI", b"BM", file_size, 0, 0, 14 + 40)
    bmp += struct.pack(
        "<IiiHHIIiiII",
        40,           # biSize
        width,
        -height,
        1,            # planes
        32,           # bits per pixel
        0,            # BI_RGB
        len(pixel_array),
        0, 0, 0, 0,
    )
    bmp += pixel_array
    return bmp


# ---------------------------------------------------------------------------
# Input helpers (T6-04.5) — ONLY called from perform(), which is
# only called from the loop after gate.check returned True.
# ---------------------------------------------------------------------------


_INPUT_MOUSE = 0
_INPUT_KEYBOARD = 1

_MOUSEEVENTF_MOVE = 0x0001
_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004
_MOUSEEVENTF_RIGHTDOWN = 0x0008
_MOUSEEVENTF_RIGHTUP = 0x0010
_MOUSEEVENTF_ABSOLUTE = 0x8000
_MOUSEEVENTF_WHEEL = 0x0800

_WHEEL_DELTA = 120

_KEYEVENTF_KEYUP = 0x0002
_KEYEVENTF_UNICODE = 0x0004

# Virtual-Key codes for the small set the spec calls out. The
# typed-text path uses UNICODE keystrokes so we don't need a
# full VK table.
_VK = {
    "return": 0x0D, "enter": 0x0D,
    "escape": 0x1B, "esc": 0x1B,
    "tab": 0x09, "space": 0x20, "backspace": 0x08,
    "delete": 0x2E, "del": 0x2E,
    "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pagedown": 0x22,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74,
    "f6": 0x75, "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79,
    "f11": 0x7A, "f12": 0x7B,
    "ctrl": 0x11, "control": 0x11,
    "alt": 0x12, "shift": 0x10,
    "win": 0x5B, "meta": 0x5B, "cmd": 0x5B,
}


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("ii", _INPUT_UNION)]


def _send_input(*inputs) -> int:
    """SendInput wrapper. Returns the number of events sent."""
    user32 = ctypes.windll.user32
    n = len(inputs)
    arr = (_INPUT * n)(*inputs)
    sent = user32.SendInput(n, arr, ctypes.sizeof(_INPUT))
    return int(sent)


def _require_coords(action: Action) -> tuple[int, int]:
    if action.coords is None:
        raise ValueError(f"{action.type!r} requires coords")
    return action.coords


def _mouse_input(*, flags: int, x: int = 0, y: int = 0, data: int = 0) -> _INPUT:
    inp = _INPUT()
    inp.type = _INPUT_MOUSE
    inp.ii.mi = _MOUSEINPUT(
        dx=x, dy=y, mouseData=data, dwFlags=flags, time=0, dwExtraInfo=None
    )
    return inp


def _keyboard_input(*, vk: int = 0, scan: int = 0, flags: int = 0) -> _INPUT:
    inp = _INPUT()
    inp.type = _INPUT_KEYBOARD
    inp.ii.ki = _KEYBDINPUT(
        wVk=vk, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=None
    )
    return inp


def _send_mouse_move(x: int, y: int) -> None:
    """Move the cursor to absolute screen coords via
    SetCursorPos — sidesteps the SendInput-absolute-coord
    normalisation gotcha that bites every Windows automation
    library."""
    user32 = ctypes.windll.user32
    user32.SetCursorPos(int(x), int(y))


def _send_mouse_click(x: int, y: int, *, button: str) -> None:
    """Move + press + release. The button events fire AT the
    new cursor position thanks to the move."""
    _send_mouse_move(x, y)
    if button == "left":
        down, up = _MOUSEEVENTF_LEFTDOWN, _MOUSEEVENTF_LEFTUP
    elif button == "right":
        down, up = _MOUSEEVENTF_RIGHTDOWN, _MOUSEEVENTF_RIGHTUP
    else:
        raise ValueError(f"unsupported button: {button!r}")
    _send_input(_mouse_input(flags=down), _mouse_input(flags=up))


def _send_text(text: str) -> None:
    """Type each character via UNICODE keystrokes — works for
    arbitrary text without a per-layout VK lookup."""
    if not text:
        return
    inputs: list[_INPUT] = []
    for ch in text:
        code = ord(ch)
        inputs.append(_keyboard_input(scan=code, flags=_KEYEVENTF_UNICODE))
        inputs.append(
            _keyboard_input(
                scan=code, flags=_KEYEVENTF_UNICODE | _KEYEVENTF_KEYUP
            )
        )
    if inputs:
        _send_input(*inputs)


def _send_key(key: str) -> None:
    """Press a single named key or chord like ``ctrl+c`` or
    ``alt+f4``. Modifiers are held while the final key fires."""
    if not key:
        return
    parts = [p.strip().lower() for p in key.split("+") if p.strip()]
    if not parts:
        return
    *modifiers, main = parts
    vks: list[int] = []
    for mod in modifiers:
        vk = _VK.get(mod)
        if vk is None:
            raise ValueError(f"unknown modifier in key chord: {mod!r}")
        vks.append(vk)
    main_vk = _VK.get(main)
    if main_vk is None:
        if len(main) == 1:
            main_vk = ord(main.upper())
        else:
            raise ValueError(f"unknown key: {main!r}")
    events: list[_INPUT] = []
    for vk in vks:
        events.append(_keyboard_input(vk=vk))
    events.append(_keyboard_input(vk=main_vk))
    events.append(_keyboard_input(vk=main_vk, flags=_KEYEVENTF_KEYUP))
    for vk in reversed(vks):
        events.append(_keyboard_input(vk=vk, flags=_KEYEVENTF_KEYUP))
    _send_input(*events)


def _send_scroll(direction: str) -> None:
    """Vertical wheel scroll. Positive mouseData scrolls up;
    negative scrolls down. Default 3 wheel-clicks per call."""
    sign = +1 if direction.lower() == "up" else -1
    _send_input(_mouse_input(flags=_MOUSEEVENTF_WHEEL, data=sign * _WHEEL_DELTA * 3))
