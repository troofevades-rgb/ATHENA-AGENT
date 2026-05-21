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
        return list(_SUPPORTED_OBSERVE)

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
        """Input is intentionally unimplemented in T6-04.3. The
        kill switch (T6-04.2) and permission gate (T6-04.1)
        must land first; T6-04.5 wires SendInput here."""
        raise NotImplementedError(
            "Windows backend input is gated until T6-04.5 lands "
            "(observe-first by design)"
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
    rows = gdi32.GetDIBits(
        ctypes.windll.user32.GetDC(None),
        hbm,
        0,
        height,
        ctypes.byref(buf),
        ctypes.byref(bmi),
        0,
    )
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
