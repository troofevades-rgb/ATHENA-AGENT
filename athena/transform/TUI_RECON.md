# T3-05R recon — labeling UI on top of the existing review seam

This phase is **not** a parallel labeling system. It slots into
`athena/transform/review.py`'s existing `LabelPrompt` callable +
sidecar write path so the labels a TUI produces are
byte-identical to those `athena train review` writes today.

## (a) LabelPrompt signature + ReviewSession driver

From `athena/transform/review.py`:

```python
LabelPrompt = Callable[[Trajectory, Label], Label]
# Receives (trajectory, auto_label_suggestion) → user's chosen Label
```

`ReviewSession` enumerates pending trajectories one at a time
(`pending()` yields `(SessionMeta, Trajectory)`) and `start(prompt)`
calls `prompt(t, t.auto_label)` for each. The callable returns one
of:

| Return | Effect |
|--------|--------|
| `"good" | "bad" | "preference_pair"` | persisted via `save_label`, advance |
| `"skip"` | no persist, advance |
| `"unreviewed"` | quit-sentinel; loop returns |

`auto_label` is set by `extract_trajectories` + `auto_classify` in
`pending()` BEFORE `prompt` is called — the prompt sees the
heuristic suggestion as its second arg.

`Label` is the literal `"good"|"bad"|"preference_pair"|"skip"|"unreviewed"`
from `transform/classifier.py`. The retargeted spec drops
"preference_pair" from default hotkeys (it shows up under `p` /
`P`) but the underlying Label enum keeps it.

## (b) Add a batch method or wrap the iterator?

**Wrap the iterator.** The least-invasive option:

- The batch driver calls `ReviewSession.pending()` directly to
  materialise `[(meta, trajectory), ...]`.
- The TUI works over the full list, then calls
  `save_label(profile_dir, meta.session_id, _trajectory_key(t), label)`
  for each decision — the existing function in `review.py` already
  exposed for exactly this.
- `ReviewSession.start(prompt)` stays the one-at-a-time path used
  by `default_prompt` and `--no-tui`.

No new method on `ReviewSession`. Both the existing
`default_prompt` flow and the new batch TUI use the same
underlying write function (`save_label`).

## (c) Sidecar file format (must stay byte-identical)

```
<profile_dir>/labels/<session_id>.json
```

Flat dict, one entry per labelled trajectory:

```json
{
  "0-3": "good",
  "4-8": "bad",
  "9-12": "skip",
  "13-15": "preference_pair"
}
```

Keys: `"<turn_start>-<turn_end>"` from `_trajectory_key`.
Values: a `Label` literal (NOT `"unreviewed"` — that's the
quit-sentinel and never gets written).

Existing writer: `save_label` (lines 70-79 of review.py) —
reads-modifies-writes the whole file, `sort_keys=True, indent=2,
trailing \n`. The batch driver MUST go through this function so
formatting stays stable across the one-at-a-time and batch paths.

## (d) `athena train review` argparse — slot for --no-tui

Current parser (cli/train.py lines 381-383):

```python
p_review = sub.add_parser("review", help="Interactively label trajectories.")
p_review.add_argument("--since-days", type=int, default=30)
p_review.add_argument("--profile", default="default")
```

Add:

```python
p_review.add_argument("--no-tui", action="store_true",
                      help="Use the existing one-at-a-time prompt instead of the textual TUI.")
p_review.add_argument("--keymap", choices=["default", "vim", "basic"], default="default")
```

`_cmd_review` switches on `args.no_tui`:
- `True` (or textual unavailable) → existing `default_prompt` path
  (unchanged)
- `False` → new TUI from `athena.transform.review_tui`

Textual is optional via `athena[train]` so the import is lazy
inside `_cmd_review` and gracefully falls back to `default_prompt`
if textual isn't installed.

## (e) No new write sites

The batch driver and TUI both go through `save_label` —
`<profile_dir>/labels/<session_id>.json` is already an
existing write site (review.py is implicitly allowlisted by virtue
of being the canonical writer). No new entries needed in
`tests/safety/test_no_raw_writes.py:ALLOWLIST`.

## (f) Reuse, not parallel implementations

| Concern | Reused from |
|---------|-------------|
| Trajectory enumeration | `ReviewSession.pending` |
| Auto-label suggestion | `classifier.auto_classify` (already set on `t.auto_label`) |
| Per-session sidecar | `review.save_label` / `load_labels` |
| Label enum | `classifier.Label` (5-value literal) |
| Argparse parent | `athena/cli/train.py:p_review` |

What's new (in scope for T3-05R):

- `athena/transform/batch_driver.py` — headless decision applier.
- `athena/transform/review_tui.py` — textual app wrapping the batch
  driver.
- `athena/transform/suggestion.py` — wraps `auto_classify` and
  optionally enriches with T3-06 skill metrics when available.
- `tests/transform/test_batch_review.py` + `test_review_tui.py` +
  `test_suggestion_enhancer.py`.

That's it. No new label format, no new file location, no new
classifier, no parallel `Label` enum.
