# T1-07 plan — file_ops.py inventory and migration map

Pre-implementation surface inventory for the path-security phase. The
implementation in T1-07.4 follows this layout.

## Public surface of `athena/tools/file_ops.py`

| Function | Args | I/O | Current boundary check |
|---|---|---|---|
| `Read` | `file_path`, `offset`, `limit` | **read** | None — comment says "the user may legitimately want to view /etc/something" |
| `Write` | `file_path`, `content` | **write** | `_within_workspace(p)` returns `ERROR:` string if outside |
| `Edit` | `file_path`, `old_string`, `new_string`, `replace_all` | **read + write** | `_within_workspace(p)` (write-side only); read happens before the check |
| `list_dir` | `path` | **read** | None |

Private helpers (used by all four): `set_workspace`, `_resolve`,
`_within_workspace`. After T1-07.2 the path-security module owns
the workspace contextvar; `set_workspace` here can stay as a thin
delegate or be deleted (test which is simpler after T1-07.6).

## Behaviour change in T1-07.4

Every public function gets `p = validate_path(file_path, intent=...)`
at the top, replacing the existing `_resolve` + `_within_workspace`
pair. `Read` and `list_dir` use `intent="read"`; `Write` uses
`intent="write"`; `Edit` calls `validate_path(file_path, intent="write")`
once — write intent covers both the read-back and the rewrite, so we
don't double-prompt the user.

The current `Write`/`Edit` `ERROR:` string return on outside-workspace
becomes a `PathSecurityDenied` raise. This is a **behaviour change**
visible to callers — callers that captured the ERROR string need to
move to try/except. The agent loop already surfaces tool exceptions as
tool errors, so the user experience is equivalent.

## Internal callers (`grep -rln 'file_ops'` under athena/)

- `athena/agent/core.py` — agent tool dispatch (`ToolRegistry` import)
- `athena/__main__.py` — `set_workspace` at CLI entry
- `athena/tools/memory_tools.py` — does not call file_ops directly,
  imports from same package
- `athena/tools/search.py` — same
- `athena/tools/shell.py` — same
- `athena/tools/skill_tools.py` — same

The only **caller** of `file_ops.set_workspace` is `__main__.py` at
CLI launch; agents inherit through the registry import.

## Test surface that exercises file_ops outside `tmp_path`

Surveyed by `grep -rln 'from athena.tools.file_ops\|file_ops\.\|tools.file_ops' tests/`.
Tests that read or write outside `tmp_path` (and therefore need
`allow_external` wrapping or workspace-fixture migration in T1-07.5):

- `tests/tools/test_file_ops.py` — uses `tmp_path` and sets it as
  the workspace; should pass without migration once the autouse
  `_path_security_workspace` fixture lands.
- `tests/test_fork_full.py` — fork-test rig may write under
  `tmp_path` but the fork's own cwd is something else; verify in
  T1-07.5.
- Any test that asserts the current `ERROR: refusing to write outside
  workspace` string (rare; if any exist they must be updated to
  match `pytest.raises(PathSecurityDenied)`).

## Migration plan recap

T1-07.2 creates `athena/safety/path_security.py`.
T1-07.3 tests it.
T1-07.4 migrates `file_ops.py` (this inventory's purpose).
T1-07.5 installs the autouse test fixture; migrates whatever else fails.
T1-07.6 wires `set_workspace` into agent init / Config.
T1-07.7 verification grep + CHANGELOG + docs.
