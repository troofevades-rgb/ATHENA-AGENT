"""T-MIG.3 — OSV client + osv_check @tool tests.

Stubs urllib.request.urlopen so no live HTTP fires.
"""

from __future__ import annotations

import io
import json
import urllib.error
from types import SimpleNamespace
from typing import Any

import pytest

from athena.safety import osv as osv_mod
from athena.safety.osv import Vulnerability, query


def _cfg(**overrides: Any) -> SimpleNamespace:
    base = dict(
        osv_enabled=True,
        osv_api_url="https://api.osv.dev/v1/query",
        osv_timeout_s=10.0,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class _FakeResponse:
    """Mimics http.client.HTTPResponse — context manager that
    yields readable + getcode()."""

    def __init__(self, *, status: int = 200, body: str = "{}"):
        self._status = status
        self._body = body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._body

    def getcode(self):
        return self._status


# ---------------------------------------------------------------
# Disabled / validation paths
# ---------------------------------------------------------------


def test_query_disabled_returns_error():
    vulns, err = query("requests", "2.31.0", ecosystem="PyPI",
                       cfg=_cfg(osv_enabled=False))
    assert vulns == []
    assert "disabled" in err.lower() or "False" in err


def test_query_requires_all_three_args():
    vulns, err = query("", "2.31.0", ecosystem="PyPI", cfg=_cfg())
    assert vulns == []
    assert "required" in err.lower()
    vulns, err = query("requests", "", ecosystem="PyPI", cfg=_cfg())
    assert "required" in err.lower()
    vulns, err = query("requests", "2.31.0", ecosystem="", cfg=_cfg())
    assert "required" in err.lower()


# ---------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------


def test_query_happy_path_no_vulns(monkeypatch):
    """Endpoint returns {"vulns": []} — no CVEs for this version."""
    monkeypatch.setattr(
        osv_mod.urllib.request, "urlopen",
        lambda req, timeout=None: _FakeResponse(
            body=json.dumps({}),
        ),
    )
    vulns, err = query("requests", "2.31.0", ecosystem="PyPI", cfg=_cfg())
    assert err is None
    assert vulns == []


def test_query_parses_vuln_records(monkeypatch):
    """End-to-end: stub a realistic OSV payload, verify the
    Vulnerability dataclass populates correctly."""
    payload = {
        "vulns": [
            {
                "id": "PYSEC-2024-001",
                "summary": "RCE via crafted header",
                "aliases": ["CVE-2024-12345"],
                "database_specific": {"severity": "HIGH"},
                "references": [
                    {"type": "ADVISORY",
                     "url": "https://github.com/x/y/security/advisories/GHSA-..."},
                    {"type": "FIX",
                     "url": "https://github.com/x/y/commit/abc"},
                ],
            },
        ],
    }
    monkeypatch.setattr(
        osv_mod.urllib.request, "urlopen",
        lambda req, timeout=None: _FakeResponse(body=json.dumps(payload)),
    )
    vulns, err = query("requests", "2.31.0", ecosystem="PyPI", cfg=_cfg())
    assert err is None
    assert len(vulns) == 1
    v = vulns[0]
    assert isinstance(v, Vulnerability)
    assert v.id == "PYSEC-2024-001"
    assert v.summary == "RCE via crafted header"
    assert v.severity == "HIGH"
    assert v.aliases == ["CVE-2024-12345"]
    assert len(v.references) == 2
    assert all(r.startswith("https://github.com/x/y") for r in v.references)
    # to_dict shape
    d = v.to_dict()
    assert set(d.keys()) == {"id", "summary", "severity", "aliases", "references"}


def test_query_request_argv_shape(monkeypatch):
    """Verify the POST body is the canonical OSV shape:
    {"package": {"name", "ecosystem"}, "version": ...}."""
    captured: dict[str, Any] = {}

    def _spy(req, timeout=None):
        captured["data"] = req.data
        captured["url"] = req.full_url
        captured["headers"] = dict(req.headers)
        return _FakeResponse(body='{"vulns": []}')

    monkeypatch.setattr(osv_mod.urllib.request, "urlopen", _spy)
    query("requests", "2.31.0", ecosystem="PyPI", cfg=_cfg())

    body = json.loads(captured["data"].decode("utf-8"))
    assert body == {
        "package": {"name": "requests", "ecosystem": "PyPI"},
        "version": "2.31.0",
    }
    # Content-Type set so OSV parses our body as JSON.
    assert captured["headers"]["Content-type"] == "application/json"


# ---------------------------------------------------------------
# Network failure modes
# ---------------------------------------------------------------


def test_query_http_error_returns_structured_error(monkeypatch):
    """OSV returned 4xx/5xx → error string includes the code."""
    def _raise_http(req, timeout=None):
        raise urllib.error.HTTPError(
            url=req.full_url, code=429, msg="rate limited",
            hdrs={}, fp=io.BytesIO(b'{"message": "too many requests"}'),
        )
    monkeypatch.setattr(osv_mod.urllib.request, "urlopen", _raise_http)
    vulns, err = query("requests", "2.31.0", ecosystem="PyPI", cfg=_cfg())
    assert vulns == []
    assert "429" in err


def test_query_network_error_returns_structured_error(monkeypatch):
    """Connection refused / DNS failure / etc. → error string
    names the underlying exception."""
    def _raise_net(req, timeout=None):
        raise urllib.error.URLError("Name resolution failed")
    monkeypatch.setattr(osv_mod.urllib.request, "urlopen", _raise_net)
    vulns, err = query("requests", "2.31.0", ecosystem="PyPI", cfg=_cfg())
    assert vulns == []
    assert "network error" in err.lower()


def test_query_timeout_returns_structured_error(monkeypatch):
    def _raise_timeout(req, timeout=None):
        raise TimeoutError("read timeout")
    monkeypatch.setattr(osv_mod.urllib.request, "urlopen", _raise_timeout)
    vulns, err = query("requests", "2.31.0", ecosystem="PyPI", cfg=_cfg())
    assert vulns == []
    assert "TimeoutError" in err or "timeout" in err.lower()


def test_query_non_json_response_returns_error(monkeypatch):
    monkeypatch.setattr(
        osv_mod.urllib.request, "urlopen",
        lambda req, timeout=None: _FakeResponse(body="not json"),
    )
    vulns, err = query("requests", "2.31.0", ecosystem="PyPI", cfg=_cfg())
    assert vulns == []
    assert "non-JSON" in err


def test_query_malformed_vulns_field(monkeypatch):
    """OSV returns {"vulns": "string instead of list"} — parser
    rejects cleanly."""
    monkeypatch.setattr(
        osv_mod.urllib.request, "urlopen",
        lambda req, timeout=None: _FakeResponse(
            body='{"vulns": "not a list"}',
        ),
    )
    vulns, err = query("requests", "2.31.0", ecosystem="PyPI", cfg=_cfg())
    assert vulns == []
    assert "not a list" in err


def test_query_skips_non_dict_vuln_entries(monkeypatch):
    """A vulns list with mixed shapes (some dicts, some not):
    we skip the non-dicts cleanly."""
    monkeypatch.setattr(
        osv_mod.urllib.request, "urlopen",
        lambda req, timeout=None: _FakeResponse(body=json.dumps({
            "vulns": [
                {"id": "PYSEC-1", "summary": "ok"},
                "string instead of dict",
                None,
                {"id": "PYSEC-2", "summary": "also ok"},
            ],
        })),
    )
    vulns, err = query("requests", "2.31.0", ecosystem="PyPI", cfg=_cfg())
    assert err is None
    assert [v.id for v in vulns] == ["PYSEC-1", "PYSEC-2"]


# ---------------------------------------------------------------
# Severity normalization
# ---------------------------------------------------------------


def test_severity_picks_up_database_specific_label(monkeypatch):
    monkeypatch.setattr(
        osv_mod.urllib.request, "urlopen",
        lambda req, timeout=None: _FakeResponse(body=json.dumps({
            "vulns": [{
                "id": "X-1",
                "database_specific": {"severity": "critical"},
            }],
        })),
    )
    vulns, _ = query("requests", "2.31.0", ecosystem="PyPI", cfg=_cfg())
    # Upper-cased at normalization.
    assert vulns[0].severity == "CRITICAL"


def test_severity_defaults_to_unknown(monkeypatch):
    monkeypatch.setattr(
        osv_mod.urllib.request, "urlopen",
        lambda req, timeout=None: _FakeResponse(body=json.dumps({
            "vulns": [{"id": "X-1"}],
        })),
    )
    vulns, _ = query("requests", "2.31.0", ecosystem="PyPI", cfg=_cfg())
    assert vulns[0].severity == "UNKNOWN"


# ---------------------------------------------------------------
# @tool wrapper
# ---------------------------------------------------------------


def test_osv_check_tool_registered():
    import athena.tools  # noqa: F401
    from athena.tools.registry import get_tool
    t = get_tool("osv_check")
    assert t is not None
    assert t.toolset == "safety"


def test_osv_check_tool_missing_args(monkeypatch):
    monkeypatch.setattr(
        "athena.tools.security.load_config", lambda: _cfg(),
    )
    from athena.tools.security import osv_check
    out = json.loads(osv_check())
    assert out["available"] is False
    assert "required" in out["error"]


def test_osv_check_tool_returns_structured_json(monkeypatch):
    """End-to-end through the tool: stub query, verify the
    tool packages the verdict + the underlying error key."""
    monkeypatch.setattr(
        "athena.tools.security.load_config", lambda: _cfg(),
    )

    def _stub_query(name, version, *, ecosystem, cfg):
        return [
            Vulnerability(
                id="PYSEC-2024-001",
                summary="oops",
                severity="HIGH",
                aliases=["CVE-2024-12345"],
                references=["https://example.com/advisory"],
                raw={},
            ),
        ], None
    monkeypatch.setattr("athena.safety.osv.query", _stub_query)

    from athena.tools.security import osv_check
    out = json.loads(osv_check(
        package="requests", version="2.31.0", ecosystem="PyPI",
    ))
    assert out["available"] is True
    assert out["package"] == "requests"
    assert out["version"] == "2.31.0"
    assert out["ecosystem"] == "PyPI"
    assert len(out["vulns"]) == 1
    assert out["vulns"][0]["id"] == "PYSEC-2024-001"
    assert out["vulns"][0]["severity"] == "HIGH"
    # Error field present + None on success.
    assert out["error"] is None


def test_osv_check_tool_surfaces_query_error(monkeypatch):
    """When query() returns (vulns, error) with error set,
    the tool surfaces available=False + the error message."""
    monkeypatch.setattr(
        "athena.tools.security.load_config", lambda: _cfg(),
    )
    monkeypatch.setattr(
        "athena.safety.osv.query",
        lambda *a, **kw: ([], "HTTP 429 from OSV"),
    )

    from athena.tools.security import osv_check
    out = json.loads(osv_check(
        package="x", version="1", ecosystem="PyPI",
    ))
    assert out["available"] is False
    assert "429" in out["error"]
    assert out["vulns"] == []
