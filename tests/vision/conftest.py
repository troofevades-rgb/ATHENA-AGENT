"""Auto-build synthesised fixtures before any vision test runs.

The fixtures are NOT checked in — see :mod:`tests.vision.fixtures`
— so pytest collection on a clean checkout has to build them once
before any module imports ``tests.vision.fixtures.FIXTURES_DIR``.
"""

from __future__ import annotations

from tests.vision.fixtures import ensure_fixtures


def pytest_collection_modifyitems(config, items):  # noqa: ARG001
    ensure_fixtures()
