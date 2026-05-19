"""Tests for toolset scoping and check_fn gating in the tool registry."""

from typing import Any

import pytest

from athena.tools import registry
from athena.tools.registry import (
    all_tools,
    ollama_schema,
    tool,
)


@pytest.fixture
def isolated_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Swap in fresh registry dicts so tests don't see real athena tools."""
    monkeypatch.setattr(registry, "_REGISTRY", {})
    monkeypatch.setattr(registry, "_TOOLSETS", {})
    monkeypatch.setattr(registry, "_ALIASES", {})


def _register(name: str, toolset: str = "core", check_fn: Any = None) -> None:
    @tool(
        name=name,
        toolset=toolset,
        description=f"tool {name}",
        parameters={"type": "object", "properties": {}},
        check_fn=check_fn,
    )
    def _fn() -> str:
        return name


def test_tool_decorator_records_toolset(isolated_registry: None) -> None:
    _register("alpha", toolset="file")
    _register("beta", toolset="shell")
    assert registry._TOOLSETS["file"] == {"alpha"}
    assert registry._TOOLSETS["shell"] == {"beta"}
    assert registry._REGISTRY["alpha"].toolset == "file"


def test_all_tools_no_filter_returns_everything(isolated_registry: None) -> None:
    _register("alpha", toolset="file")
    _register("beta", toolset="shell")
    _register("gamma", toolset="web")
    names = {t.name for t in all_tools()}
    assert names == {"alpha", "beta", "gamma"}


def test_enable_list_returns_only_named_toolsets(isolated_registry: None) -> None:
    _register("alpha", toolset="file")
    _register("beta", toolset="shell")
    _register("gamma", toolset="web")
    names = {t.name for t in all_tools(enabled_toolsets=["file", "web"])}
    assert names == {"alpha", "gamma"}


def test_enable_list_empty_returns_nothing(isolated_registry: None) -> None:
    _register("alpha", toolset="file")
    _register("beta", toolset="shell")
    assert all_tools(enabled_toolsets=[]) == []


def test_disabled_list_still_works_with_no_enable_list(isolated_registry: None) -> None:
    _register("alpha", toolset="file")
    _register("beta", toolset="shell")
    names = {t.name for t in all_tools(disabled=["beta"])}
    assert names == {"alpha"}


def test_disabled_list_intersects_with_enable_list(isolated_registry: None) -> None:
    _register("alpha", toolset="file")
    _register("beta", toolset="file")
    _register("gamma", toolset="shell")
    names = {t.name for t in all_tools(enabled_toolsets=["file"], disabled=["beta"])}
    assert names == {"alpha"}


def test_check_fn_omits_unmet_tools_from_schema(isolated_registry: None) -> None:
    _register("always_on", toolset="core", check_fn=lambda: True)
    _register("never_on", toolset="core", check_fn=lambda: False)
    _register("no_check", toolset="core")
    schema_names = {entry["function"]["name"] for entry in ollama_schema()}
    assert schema_names == {"always_on", "no_check"}


def test_check_fn_re_evaluated_each_call(isolated_registry: None) -> None:
    """check_fn is called fresh each time the schema is built, not cached."""
    state = {"available": False}
    _register("flaky", toolset="core", check_fn=lambda: state["available"])

    assert ollama_schema() == []
    state["available"] = True
    schema_names = {entry["function"]["name"] for entry in ollama_schema()}
    assert schema_names == {"flaky"}
    state["available"] = False
    assert ollama_schema() == []
