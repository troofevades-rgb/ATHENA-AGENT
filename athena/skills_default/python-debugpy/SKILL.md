---
description: Debug Python with pdb interactively or debugpy remotely via DAP
name: python-debugpy
created_at: '2026-05-27T00:00:00Z'
last_activity_at: '2026-05-27T00:00:00Z'
pinned: false
state: active
use_count: 0
write_origin: foreground
---
# Python Debugging

Disciplined Python debugging via ``pdb`` (interactive REPL) and
``debugpy`` (remote DAP). The premise: print-debugging works for
simple bugs; real debugging tools work for everything else —
including async, multi-process, and production-like setups.

## When to use this skill

Use when print-debugging isn't enough:
- Bug only reproduces in a specific call stack you can't easily
  reach
- You need to inspect / modify state mid-execution
- The bug is in async / multi-process / multi-threaded code
- You need to debug a running production-like process (with
  ``debugpy``)

Pairs with [[systematic-debugging]] — that's the methodology;
this is the tooling.

## Path 1: pdb (interactive REPL)

The cheapest entry. Built into stdlib.

### Drop into pdb at a specific line

```python
def compute_total(items):
    breakpoint()        # Python 3.7+ — drops into pdb here
    return sum(i.price for i in items)
```

Run the script normally. When execution hits ``breakpoint()``,
the pdb prompt opens. From there:

```
(Pdb) p items                  # print value
(Pdb) pp items                  # pretty-print
(Pdb) l                         # list source around current line
(Pdb) w                         # where — current stack
(Pdb) n                         # next line (step over)
(Pdb) s                         # step into
(Pdb) c                         # continue until next breakpoint
(Pdb) !items.append(x)          # ! prefix runs arbitrary Python
(Pdb) b checkout.py:42          # set another breakpoint
(Pdb) cl 1                      # clear breakpoint #1
(Pdb) q                         # quit
```

### Post-mortem on a crash

```bash
python -m pdb -c continue script.py
```

If the script crashes, pdb opens at the crash site. You can
inspect locals at the moment of failure.

Or in code:

```python
try:
    risky()
except Exception:
    import pdb; pdb.post_mortem()
```

### Better pdb: ipdb / pdbpp

```bash
pip install ipdb     # ipython-flavored pdb with tab completion
pip install pdbpp    # syntax highlighting, sticky mode
```

Set ``PYTHONBREAKPOINT=ipdb.set_trace`` to make ``breakpoint()``
drop into ipdb instead of pdb.

## Path 2: debugpy (remote DAP)

For attaching a real IDE debugger (VS Code, Cursor, PyCharm) to
a running Python process — even one running inside Docker, a
remote machine, or behind a network boundary.

### Install

```bash
pip install debugpy
```

### Attach mode (recommended)

Insert this near the start of your program:

```python
import debugpy
debugpy.listen(("0.0.0.0", 5678))
print("waiting for debugger to attach on :5678")
debugpy.wait_for_client()    # blocks until IDE connects
print("debugger attached, continuing")
```

Then in VS Code, create ``.vscode/launch.json``:

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Python: Attach",
      "type": "debugpy",
      "request": "attach",
      "connect": { "host": "localhost", "port": 5678 },
      "pathMappings": [
        { "localRoot": "${workspaceFolder}",
          "remoteRoot": "/app" }
      ]
    }
  ]
}
```

Run your program → it pauses at ``wait_for_client()`` → start
the VS Code debug session → it connects and execution resumes →
hit any breakpoints set in the IDE.

### Launch mode

Instead of attaching, launch your program FROM the IDE with
debugpy active:

```json
{
  "name": "Python: Launch",
  "type": "debugpy",
  "request": "launch",
  "module": "athena",
  "args": ["run", "--config", "test.toml"]
}
```

Simpler for local development.

### Debugging tests

```json
{
  "name": "Python: pytest current file",
  "type": "debugpy",
  "request": "launch",
  "module": "pytest",
  "args": ["${file}", "-v"]
}
```

Set breakpoints in test code OR production code; pytest exercises
both with the debugger active.

## Debugging async / asyncio

Async code prints a confusing stack trace because the await chain
splits frames. pdb handles it well:

```python
async def f():
    breakpoint()         # pdb works inside async functions
    return await g()
```

When stepping in async code:
- ``n`` over an ``await`` runs the awaited coroutine to completion
- ``s`` into an ``await`` enters the coroutine's first await point
- ``w`` shows the async stack, including ``__await__`` frames

For asyncio bugs specifically:
- ``asyncio.run(main(), debug=True)`` enables asyncio's debug
  mode (warns on slow callbacks, slow tasks, never-awaited
  coroutines)
- ``asyncio.all_tasks()`` from pdb to inspect running tasks

## Debugging multi-process

For ``multiprocessing.Process`` / ``concurrent.futures``:

```python
import debugpy

def worker():
    debugpy.listen(("0.0.0.0", 5679))  # different port per worker
    debugpy.wait_for_client()
    # rest of worker code
```

Attach a separate debug session per worker port. Tedious but
works.

For pytest with multiple processes (e.g., ``pytest-xdist``):
disable xdist while debugging — debug with ``-p no:xdist`` to run
sequentially.

## Common patterns

### Conditional breakpoint

```python
for item in items:
    if item.id == "stuck-id":
        breakpoint()       # only breaks for the problem item
    process(item)
```

Or from pdb:

```
(Pdb) b checkout.py:42, item.id == "stuck-id"
```

### Tracing function calls

```python
import sys

def tracer(frame, event, arg):
    if event == "call":
        print(f"-> {frame.f_code.co_name}")
    return tracer

sys.settrace(tracer)
# code to trace
sys.settrace(None)
```

Useful when you want to see WHICH functions get called without
breakpoints everywhere.

### Inspecting tight loops

pdb in a tight loop is painful — too many ``n`` presses. Instead:

```python
for i, item in enumerate(items):
    if i == problematic_index:
        breakpoint()
    process(item)
```

## Anti-patterns

- **Print-debugging when pdb would be faster**: 3+ prints in a
  function = use pdb. You'll save time.
- **Leaving breakpoints in committed code**: ``breakpoint()`` in
  prod code is a production outage waiting to happen. Linters
  (ruff: ``T100``) flag this — keep the lint on.
- **debugpy without authentication on a public interface**:
  ``debugpy.listen(("0.0.0.0", 5678))`` on a public network = a
  remote code execution vector. Bind to ``127.0.0.1`` or use SSH
  port-forwarding.
- **Skipping post-mortem**: when a script crashes, ``python -m
  pdb -c continue`` post-mortem is often FASTER than re-running
  with prints added.
- **Debugger blindness**: spending an hour stepping through code
  when reading the code carefully for 10 minutes would have
  found the bug. Debugger is a tool; thinking is the work.
