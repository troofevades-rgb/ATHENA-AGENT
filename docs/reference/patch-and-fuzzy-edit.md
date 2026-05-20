# `patch_apply` and `Edit` fuzzy fallback

Two related improvements to file editing landed in T2-07.

## `patch_apply` — atomic unified-diff application

Use `patch_apply` when an edit touches more than two callsites, or
when several hunks together need to land as one unit. The tool
accepts the output of `diff -u`:

```
--- a/path/to/file.py
+++ b/path/to/file.py
@@ -10,3 +10,3 @@
 def foo():
-    return 1
+    return 2
 def bar():
```

Multi-file patches: include multiple `---` / `+++` header pairs in
the same call.

### Atomicity contract

Either every hunk in every file lands, or no file is modified.
Under the hood:

1. Every `new_path` is routed through
   `path_security.validate_path(intent="write")` before any
   write happens. A `path_security` deny aborts the operation
   cleanly.
2. For each file the tool will modify, the original content is
   copied to a temp `.bak` file.
3. Each file's hunks are applied in-memory; the result is written
   to the target.
4. If **any** file fails (context mismatch, target missing, OS
   error), every file touched so far is restored from its backup
   and the backups are unlinked. The tool returns an `ERROR:`
   string with the failure reason.
5. On full success, backups are unlinked. The tool returns a
   summary: `applied N hunk(s) across M file(s): <list>`.

### When NOT to use patch_apply

- Single-line tweaks: use `Edit` (str_replace).
- New file creation: use `Write`.
- Binary edits: not supported.

## `Edit` (str_replace) fuzzy fallback

By default, `Edit` requires `old_string` to match verbatim. Pass
`fuzzy=True` to enable a sliding-window fuzzy fallback when the
verbatim match fails.

### Contract

- **Verbatim path is unchanged.** The fuzzy code runs only when
  `text.count(old_string) == 0`. Setting `fuzzy=True` doesn't
  penalise the happy path.
- **Exactly one near-match required.** Two-or-more near-matches
  above the threshold return an `ERROR:` asking the agent to
  include more context. The tool never picks one of N — that's
  the safety property.
- **Threshold default 0.95.** Configurable per-call via
  `fuzzy_threshold` (0..1).
- **Score reported on success.** The success line carries
  `(fuzzy: score=0.953, matched N chars)` so the agent (and the
  human reading logs) can see how loose the match was.

### Parameters

```json
{
  "file_path": "...",
  "old_string": "...",
  "new_string": "...",
  "replace_all": false,
  "fuzzy": false,
  "fuzzy_threshold": 0.95
}
```

### When to enable fuzzy

Default is `fuzzy=false`. Turn it on after a verbatim Edit has
failed once and you suspect a whitespace or minor-formatting
mismatch. The error string from a failed verbatim Edit explicitly
mentions `fuzzy=true` as the recovery hint.

### Backend choice

The fuzzy matcher prefers `rapidfuzz` if installed, otherwise falls
back to `difflib.SequenceMatcher` (stdlib). `rapidfuzz` is **not** a
hard dependency.

## Implementation

- `athena/tools/patch_parser.py` — pure parse + apply for unified
  diffs.
- `athena/tools/patch_apply.py` — the `patch_apply` tool;
  per-file backup-restore for atomicity.
- `athena/tools/fuzzy_match.py` — `find_fuzzy_matches` returning
  ALL near-matches above threshold; caller decides what to do
  with `len(matches) != 1`.
- `athena/tools/file_ops.py:Edit` — fuzzy fallback when verbatim
  count is zero and `fuzzy=True`.
