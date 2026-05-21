"""Per-test isolation for the T6-04R approval ContextVars.

The new PermissionGate routes through
:mod:`athena.safety.approval_guard` + the active
:mod:`athena.safety.approval_callback`. Both live in ContextVars
that survive across test function calls within the same pytest
session — so a callback bound by test A would bleed into test B
unless we reset.

This autouse fixture snapshots + restores both ContextVars per
test plus clears the approval grant cache + the panic flag, so
every test starts with the default interactive callback +
empty grants.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_approval_state():
    from athena.computer.permission import (
        computer_use_unpanic,
        panic_engaged,
    )
    from athena.safety.approval_callback import (
        _approval as _approval_cb_var,
        _interactive_approval,
    )
    from athena.safety.approval_guard import _approval_grants, clear_grants

    cb_token = _approval_cb_var.set(_interactive_approval)
    grants_token = _approval_grants.set({})
    yield
    clear_grants()
    if panic_engaged():
        computer_use_unpanic()
    _approval_cb_var.reset(cb_token)
    _approval_grants.reset(grants_token)
