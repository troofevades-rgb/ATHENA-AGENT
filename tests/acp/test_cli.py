"""``athena acp`` CLI subcommands."""

from __future__ import annotations

import json

import pytest

from athena.cli import acp as cli


def test_install_zed_prints_snippet(
    capsys: pytest.CaptureFixture,
) -> None:
    rc = cli.main(["install-zed"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "agent_servers" in out
    assert "athena" in out
    # Instructions tell the user where to drop it.
    assert "settings.json" in out


def test_install_zed_json_output(
    capsys: pytest.CaptureFixture,
) -> None:
    rc = cli.main(["install-zed", "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "agent_servers" in payload
    config = payload["agent_servers"]["athena"]
    assert config["command"] == "athena"
    assert config["args"] == ["acp", "serve"]
    assert "env" in config


def test_no_subcommand_errors() -> None:
    with pytest.raises(SystemExit):
        cli.main([])


def test_unknown_subcommand_errors() -> None:
    with pytest.raises(SystemExit):
        cli.main(["telegram"])
