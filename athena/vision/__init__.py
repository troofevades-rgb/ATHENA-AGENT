"""Vision analysis (T4-01).

Local pixel ops + provider-agnostic image passthrough. See
:mod:`athena.vision.analyze` for the public ``vision_analyze``
tool entry point; this package's other modules are
implementation details that the tool composes.

Mirrors :mod:`athena.computer` in spirit: a permissioned,
audit-logged surface that gives the model a structured way to
*reason about images* without bypassing the rest of athena's
safety story (no raw bytes leak into chat history, every read
of every file is hash-logged for provenance).
"""

from __future__ import annotations
