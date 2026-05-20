"""Tests for ``athena cache status`` + ``athena cache clear`` (T5-06.2)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from athena.cache.cross_session import CrossSessionCache
from athena.cli import cache as cli_cache


def _cfg(**overrides) -> SimpleNamespace:
    base = {
        "cross_session_cache_enabled": True,
        "cache_min_prefix_tokens": 0,
        "cache_index_path": None,
        "profile": "default",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _seed(path: Path, cfg) -> None:
    """Plant two entries (one alive, one expired) in the cache."""
    c = CrossSessionCache(index_path=path, cfg=cfg)
    c.record(
        workspace="/proj/alive",
        prefix_text="X" * 200,
        provider="anthropic",
        provider_cache_id="srv-alive",
        ttl_s=3600,
    )
    e = c.record(
        workspace="/proj/expired",
        prefix_text="Y" * 200,
        provider="openai",
        provider_cache_id="srv-expired",
        ttl_s=60,
    )
    # Backdate the second entry.
    e.created_at = time.time() - 9999
    c._save()


def test_status_lists_entries(tmp_path, monkeypatch, capsys):
    path = tmp_path / "ci.json"
    cfg = _cfg(cache_index_path=str(path))
    _seed(path, cfg)
    monkeypatch.setattr(cli_cache, "load_config", lambda: cfg)

    rc = cli_cache.main(["status"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "2 cache entries" in out
    assert "ALIVE" in out
    assert "EXPIRED" in out
    assert "/proj/alive" in out
    assert "/proj/expired" in out


def test_status_json_shape(tmp_path, monkeypatch, capsys):
    path = tmp_path / "ci.json"
    cfg = _cfg(cache_index_path=str(path))
    _seed(path, cfg)
    monkeypatch.setattr(cli_cache, "load_config", lambda: cfg)

    rc = cli_cache.main(["status", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert isinstance(payload, list)
    assert len(payload) == 2
    keys = set(payload[0].keys())
    assert {"workspace", "prefix_hash", "provider", "ttl_s", "alive"}.issubset(keys)


def test_status_no_index(tmp_path, monkeypatch, capsys):
    cfg = _cfg(cache_index_path=str(tmp_path / "absent.json"))
    monkeypatch.setattr(cli_cache, "load_config", lambda: cfg)
    rc = cli_cache.main(["status"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "no cache index" in out


def test_cache_clear_empties_index(tmp_path, monkeypatch, capsys):
    path = tmp_path / "ci.json"
    cfg = _cfg(cache_index_path=str(path))
    _seed(path, cfg)
    monkeypatch.setattr(cli_cache, "load_config", lambda: cfg)

    rc = cli_cache.main(["clear"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "cleared 2 cache entry" in out
    # The file still exists, but it's empty
    c = CrossSessionCache(index_path=path, cfg=cfg)
    assert c.all() == []


def test_clear_no_index_is_a_no_op(tmp_path, monkeypatch, capsys):
    cfg = _cfg(cache_index_path=str(tmp_path / "absent.json"))
    monkeypatch.setattr(cli_cache, "load_config", lambda: cfg)
    rc = cli_cache.main(["clear"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "nothing to clear" in out


def test_index_path_arg_overrides_cfg(tmp_path, monkeypatch, capsys):
    """--index-path beats cfg.cache_index_path so an operator can
    inspect a non-default profile's cache."""
    other = tmp_path / "other.json"
    cfg = _cfg(cache_index_path=str(tmp_path / "cfg.json"))
    _seed(other, cfg)
    monkeypatch.setattr(cli_cache, "load_config", lambda: cfg)

    rc = cli_cache.main(["status", "--index-path", str(other)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "2 cache entries" in out
