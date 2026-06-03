"""Pure-Python MP4/MOV box (atom) parser (T4-02.2).

We don't need a full ISO/IEC 14496-12 implementation — just the
top-level box ordering and a few key boxes. That's enough to
answer the single most important container-analysis question:

  Does the file's **moov** atom come BEFORE its **mdat** atom?

If yes, the file has been through a qt-faststart (web-optimised)
remux. A camera or recorder writes moov LAST because the box
contains references into the stream tables that aren't known
until all the samples have been written; a faststart pass moves
moov to the front so HTTP-range readers can stream-decode without
fetching the entire file first.

The point of putting this in pure Python: it's the most useful
container-tampering signal AND it costs us nothing to keep
available on a stripped host without ffmpeg. The ffprobe-backed
modes (codec / encoder / GOP) gracefully degrade; the atom check
always works.
"""

from __future__ import annotations

import dataclasses
import struct
from pathlib import Path
from typing import Any


@dataclasses.dataclass(frozen=True)
class Atom:
    """One top-level box in an MP4/MOV file."""

    type: str  # 4-char box type ("ftyp", "moov", "mdat", ...)
    size: int  # box size in bytes including the 8-byte header
    offset: int  # byte offset in the file


def parse_top_level_atoms(
    path: Path | str,
    *,
    max_atoms: int = 64,
) -> list[Atom]:
    """Walk the top-level box structure of an MP4/MOV file.

    Returns the boxes in file order. ``max_atoms`` caps the walk
    so a malformed file with a runaway box chain can't loop
    forever (a normal MP4 has 3-8 top-level boxes).

    Handles the three box-header shapes:
      - 32-bit size: standard, header is 8 bytes
      - size == 1: 64-bit extended size in the next 8 bytes
        (header is 16 bytes)
      - size == 0: box extends to end-of-file (last box marker)

    Returns ``[]`` for non-MP4/MOV inputs — we can't tell from
    here whether the caller fed us a JPEG, so a defensive empty
    result is safer than raising. Tests that need to validate a
    file is a real MP4 should call :func:`is_likely_isobmff` first.
    """
    p = Path(path)
    atoms: list[Atom] = []
    size_total = p.stat().st_size
    with open(p, "rb") as f:
        offset = 0
        while offset < size_total and len(atoms) < max_atoms:
            f.seek(offset)
            header = f.read(8)
            if len(header) < 8:
                break
            sz = struct.unpack(">I", header[:4])[0]
            try:
                atype = header[4:8].decode("latin-1")
            except UnicodeDecodeError:  # pragma: no cover - latin-1 never raises
                break
            consumed = 8
            if sz == 1:
                ext = f.read(8)
                if len(ext) < 8:
                    break
                sz = struct.unpack(">Q", ext)[0]
                consumed = 16
            elif sz == 0:
                # Last-box-marker: extends to end of file.
                sz = size_total - offset
            atoms.append(Atom(type=atype, size=sz, offset=offset))
            if sz < consumed:
                # Malformed: declared size smaller than the header
                # we already consumed. Stop rather than loop.
                break
            offset += sz
    return atoms


def is_likely_isobmff(atoms: list[Atom]) -> bool:
    """Cheap "is this a real MP4/MOV" check. The ISO base media
    file format starts with an ``ftyp`` box; we look at the first
    parsed atom and accept ``ftyp`` (standard) or ``moov`` (some
    streamers omit ftyp). False otherwise."""
    if not atoms:
        return False
    return atoms[0].type in ("ftyp", "moov", "skip", "free")


def faststart_remux_signature(atoms: list[Atom]) -> dict[str, Any]:
    """Diagnose the moov-vs-mdat ordering.

    Returns a dict with:

      atom_order          : list of box types in file order
      moov_index          : index of moov in atom_order, or -1
      mdat_index          : index of mdat in atom_order, or -1
      moov_before_mdat    : bool — the qt-faststart tell
      interpretation      : a hedged string the model can quote
                            verbatim into a report

    The interpretation string is intentionally hedged: a
    moov-before-mdat layout STRONGLY suggests a remux pass, but
    a small fraction of recorders / streaming muxers natively
    write moov first. We surface the SIGNAL, not a verdict. The
    same discipline runs through the encoder-fingerprint /
    inspect modes.
    """
    order = [a.type for a in atoms]
    moov_idx = order.index("moov") if "moov" in order else -1
    mdat_idx = order.index("mdat") if "mdat" in order else -1
    moov_before_mdat = moov_idx != -1 and mdat_idx != -1 and moov_idx < mdat_idx
    if moov_idx == -1 and mdat_idx == -1:
        interp = (
            "no moov or mdat atom found — input is probably not "
            "MP4 / MOV, or the top-level walk truncated before "
            "reaching them"
        )
    elif moov_idx == -1:
        interp = "moov atom missing — file may be truncated"
    elif mdat_idx == -1:
        interp = "mdat atom missing — file may be truncated"
    elif moov_before_mdat:
        interp = (
            "moov precedes mdat — consistent with a qt-faststart "
            "(web-optimised) remux pass. Camera / recorder muxers "
            "almost always write moov last; moov-first is the "
            "characteristic post-remux ordering."
        )
    else:
        interp = (
            "mdat precedes moov — typical of original camera "
            "capture and recorder output. No faststart remux "
            "evident from box ordering alone."
        )
    return {
        "atom_order": order,
        "moov_index": moov_idx,
        "mdat_index": mdat_idx,
        "moov_before_mdat": moov_before_mdat,
        "interpretation": interp,
    }
