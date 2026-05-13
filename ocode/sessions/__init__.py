"""Per-profile session store: JSONL append + SQLite FTS5 mirror.

Plain files are the source of truth at
``~/.ocode/profiles/<profile>/sessions/<session_id>.jsonl``. SQLite at
``~/.ocode/profiles/<profile>/sessions.db`` is a cache — losing it doesn't
lose data, ``ocode reindex`` rebuilds from JSONL.
"""
