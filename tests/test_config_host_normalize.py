"""Regression: ``OLLAMA_HOST=0.0.0.0`` is a bind-only address (the
Ollama server side); rewriting to ``127.0.0.1`` lets the HTTP client
connect instead of failing with WinError 10049 / EADDRNOTAVAIL.
"""
from __future__ import annotations

import pytest

from athena.config import _normalize_ollama_host


@pytest.mark.parametrize("raw,expected", [
    # IPv4 wildcard → loopback
    ("0.0.0.0:11434", "http://127.0.0.1:11434"),
    ("http://0.0.0.0:11434", "http://127.0.0.1:11434"),
    ("http://0.0.0.0", "http://127.0.0.1"),
    # IPv6 wildcard → loopback
    ("http://[::]:11434", "http://[::1]:11434"),
    ("http://[0:0:0:0:0:0:0:0]:11434", "http://[::1]:11434"),
    # Already-loopback values pass through.
    ("127.0.0.1:11434", "http://127.0.0.1:11434"),
    ("http://127.0.0.1:11434", "http://127.0.0.1:11434"),
    ("http://localhost:11434", "http://localhost:11434"),
    # Remote hosts pass through untouched.
    ("http://gpu-box.lan:11434", "http://gpu-box.lan:11434"),
    ("gpu-box.lan:11434", "http://gpu-box.lan:11434"),
])
def test_normalize_ollama_host(raw: str, expected: str) -> None:
    assert _normalize_ollama_host(raw) == expected
