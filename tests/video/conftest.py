"""Build video fixtures lazily on first need.

Unlike vision fixtures (always synthesised), video fixtures need
ffmpeg — when it's absent we don't build them, and the test
modules use ``pytest.mark.skipif(not have_ffmpeg(), ...)`` so
the test pass remains green on CI nodes that lack ffmpeg.
"""

from __future__ import annotations

from tests.video.fixtures import ensure_fixtures, have_ffmpeg


def pytest_collection_modifyitems(config, items):  # noqa: ARG001
    if have_ffmpeg():
        ensure_fixtures()
