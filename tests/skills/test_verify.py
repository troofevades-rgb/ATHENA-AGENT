"""Tests for athena.skills.verify — Python-fence parse gate."""

from __future__ import annotations

from athena.skills.verify import verify_body


def test_empty_body_passes():
    ok, msg = verify_body("")
    assert ok is True
    assert msg == ""


def test_prose_only_passes():
    body = "# Heading\n\nSome instructions.\n\n- bullet\n- another\n"
    ok, msg = verify_body(body)
    assert ok is True


def test_valid_python_block_passes():
    body = """# Skill

Some intro.

```python
def hello(name: str) -> str:
    return f"hi {name}"
```

More prose.
"""
    ok, msg = verify_body(body)
    assert ok is True


def test_multiple_valid_blocks_pass():
    body = """```python
x = 1
```

and

```python
y = 2
```
"""
    ok, msg = verify_body(body)
    assert ok is True


def test_broken_python_block_fails():
    """The exact failure pattern from the failed session — a bare
    ``successful =`` with no value and a misplaced future-import."""
    body = """```python
from dataclasses import dataclass

@dataclass
class TaskRecord:
    pass

from __future__ import annotations

successful =
```
"""
    ok, msg = verify_body(body)
    assert ok is False
    assert "SyntaxError" in msg
    assert "line" in msg.lower()


def test_failure_message_names_block_number():
    """When multiple blocks exist, the message identifies which one failed."""
    body = """```python
ok = 1
```

```python
broken =
```
"""
    ok, msg = verify_body(body)
    assert ok is False
    assert "#2" in msg


def test_unfenced_python_like_text_passes():
    """Prose that looks like Python but isn't fenced — leave it alone."""
    body = """When you call `def foo(x):` with an invalid arg,
the system returns ERROR.
"""
    ok, msg = verify_body(body)
    assert ok is True


def test_py_alias_fence_also_checked():
    body = """```py
broken =
```
"""
    ok, msg = verify_body(body)
    assert ok is False
    assert "SyntaxError" in msg


def test_fence_with_extra_info_string_still_parsed():
    """```python title=foo.py ... ``` should still trigger the parse."""
    body = """```python title=example.py
broken =
```
"""
    ok, msg = verify_body(body)
    assert ok is False
