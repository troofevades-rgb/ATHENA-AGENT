"""Video analysis (T4-02).

Two-layer discipline: the *container* (atom ordering, format,
muxer signatures) and the *elementary stream* (codec, encoder
fingerprint, GOP shape) are reported separately. A remux pass
can touch the container while the underlying stream stays
authentic; collapsing them into one "is it real" boolean is the
exact failure this module is designed to prevent.

Public surface lives in :mod:`athena.video.analyze` —
``video_analyze`` with modes ``probe`` / ``atoms`` / ``gop`` /
``encoder_fingerprint`` / ``inspect`` / ``frames`` / ``analyze``.
The other modules are implementation details:

  :mod:`athena.video.atoms`   pure-Python MP4/MOV box parser
                              (no ffmpeg needed)
  :mod:`athena.video.probe`   ffprobe-backed inspection
  :mod:`athena.video.extract` ffmpeg frame extraction
"""

from __future__ import annotations
