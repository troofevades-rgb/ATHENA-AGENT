---
name: python-typing-style
description: When writing or editing Python in this codebase use modern PEP 604 syntax — `str | None` rather than `Optional[str]`, `list[int]` not `List[int]`. Don't import from `typing` unless using something not yet in the builtins (Callable, Iterator, Protocol, TYPE_CHECKING). Always include `from __future__ import annotations` so annotations are stringified.
write_origin: foreground
---

# Python typing conventions

The athena codebase commits to Python 3.11+ and uses the modern
annotation syntax throughout. Adhere strictly to:

- `str | None` instead of `Optional[str]` (PEP 604, Python 3.10+)
- `list[int]` instead of `List[int]` (PEP 585, Python 3.9+)
- `dict[str, Any]` instead of `Dict[str, Any]`
- `tuple[Path, ...]` for variadic tuples

The `typing` module is still the canonical home for things that
don't live in builtins:

- `Callable[[int], str]`
- `Iterator[T]`, `AsyncIterator[T]`
- `Protocol` (when defining structural-typed interfaces)
- `TYPE_CHECKING` (guard for forward references that would
   otherwise cycle on import)

Every module starts with `from __future__ import annotations` so
runtime introspection never has to resolve annotations.
