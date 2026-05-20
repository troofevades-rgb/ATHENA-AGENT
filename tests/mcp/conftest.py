"""Shared fixtures for tests/mcp/test_server*, test_tools, test_resources.

Build an :class:`AthenaMCPServer` against a tmp-path home so the
tests stay hermetic (no touching ~/.athena).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from athena.mcp.resources import AthenaMCPResources
from athena.mcp.server import AthenaMCPServer
from athena.mcp.tools import AthenaMCPTools
from athena.safety.snapshots import SnapshotStore


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture
def audit_dir(tmp_path: Path) -> Path:
    d = tmp_path / "audit"
    d.mkdir()
    return d


@pytest.fixture
def snapshot_store(tmp_path: Path) -> SnapshotStore:
    """SnapshotStore rooted in tmp; relative_to=tmp_path so member
    names in the tarball are positional under the tmp dir."""
    return SnapshotStore(
        root=tmp_path / "snapshots",
        relative_to=tmp_path,
    )


@pytest.fixture
def mcp_tools(workspace, audit_dir, snapshot_store) -> AthenaMCPTools:
    return AthenaMCPTools(
        workspace=workspace,
        memory_profile="default",
        audit_dir=audit_dir,
        snapshot_store=snapshot_store,
    )


@pytest.fixture
def mcp_resources(workspace, audit_dir) -> AthenaMCPResources:
    return AthenaMCPResources(
        workspace=workspace,
        memory_profile="default",
        audit_dir=audit_dir,
    )


@pytest.fixture
def server(mcp_tools, mcp_resources) -> AthenaMCPServer:
    return AthenaMCPServer(tools=mcp_tools, resources=mcp_resources)
