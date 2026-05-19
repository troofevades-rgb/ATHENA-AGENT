"""``athena webhook`` CLI subcommands."""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from athena.cli import webhook as cli
from athena.config import Config
from athena.webhooks.subscription import WebhookStore


@pytest.fixture(autouse=True)
def isolated_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Redirect store + active-profile resolution to tmp_path."""
    from athena import config as cfg_mod
    from athena.profiles import resolution

    def fake_profile_dir(name="default", home=None):
        return tmp_path / "athena_home" / "profiles" / name

    monkeypatch.setattr(cli, "_profile_dir", fake_profile_dir)
    monkeypatch.setattr(cfg_mod, "profile_dir", fake_profile_dir)
    monkeypatch.setattr(resolution, "PROFILES_DIR", tmp_path / "profiles")
    monkeypatch.setattr(
        resolution,
        "ACTIVE_PROFILE_FILE",
        tmp_path / "active_profile",
    )
    monkeypatch.delenv("ATHENA_PROFILE", raising=False)
    monkeypatch.delenv("OCODE_PROFILE", raising=False)
    # load_config returns a stock Config.
    monkeypatch.setattr(
        cli,
        "load_config",
        lambda: Config(profile="default"),
    )
    return tmp_path


def _read_store(tmp_path: Path) -> WebhookStore:
    """Read the store the CLI just wrote to so we can verify rows."""
    return WebhookStore(
        tmp_path / "athena_home" / "profiles" / "default" / "webhooks.db",
    )


# ---- add -----------------------------------------------------------


def test_add_with_skill_and_explicit_secret(
    isolated_profile: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    rc = cli.main(
        [
            "add",
            "--description",
            "github push",
            "--auth",
            "hmac_sha256",
            "--secret",
            "my-secret",
            "--skill",
            "summarize-pr",
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "webhook registered" in out
    assert "url: http://" in out
    assert "skill: summarize-pr" in out
    # Persisted.
    rows = _read_store(isolated_profile).list()
    assert len(rows) == 1
    assert rows[0].skill_name == "summarize-pr"
    assert rows[0].auth_secret == "my-secret"


def test_add_auto_generates_secret(
    isolated_profile: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    rc = cli.main(
        [
            "add",
            "--auth",
            "hmac_sha256",
            "--skill",
            "echo",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "generated hmac_sha256 secret:" in out
    # The secret got persisted (non-empty).
    rows = _read_store(isolated_profile).list()
    assert rows[0].auth_secret


def test_add_with_prompt_template(
    isolated_profile: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    rc = cli.main(
        [
            "add",
            "--auth",
            "none",
            "--prompt-template",
            "Summarize: {{ payload }}",
        ]
    )
    assert rc == 0
    rows = _read_store(isolated_profile).list()
    assert rows[0].binding_type == "prompt"
    assert "{{ payload }}" in rows[0].prompt_template


def test_add_rejects_both_skill_and_template(
    isolated_profile: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    rc = cli.main(
        [
            "add",
            "--skill",
            "x",
            "--prompt-template",
            "y",
        ]
    )
    assert rc == 2
    assert "not both" in capsys.readouterr().err


def test_add_rejects_neither_skill_nor_template(
    isolated_profile: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    rc = cli.main(["add", "--auth", "none"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "--skill" in err and "--prompt-template" in err


def test_add_auth_none_doesnt_generate_secret(
    isolated_profile: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    rc = cli.main(
        [
            "add",
            "--auth",
            "none",
            "--skill",
            "echo",
        ]
    )
    out = capsys.readouterr().out
    assert "generated" not in out
    rows = _read_store(isolated_profile).list()
    assert rows[0].auth_secret == ""


def test_add_json_output(
    isolated_profile: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    rc = cli.main(
        [
            "add",
            "--auth",
            "none",
            "--skill",
            "x",
            "--json",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "id" in payload
    assert payload["url"].startswith("http://127.0.0.1:4747/webhook/")
    assert payload["auth_type"] == "none"


def test_add_with_custom_host_port_in_url(
    isolated_profile: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    cli.main(
        [
            "add",
            "--auth",
            "none",
            "--skill",
            "x",
            "--host",
            "athena.example.com",
            "--port",
            "8443",
        ]
    )
    out = capsys.readouterr().out
    assert "athena.example.com:8443" in out


# ---- list / info --------------------------------------------------


def test_list_empty(
    isolated_profile: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    rc = cli.main(["list"])
    assert rc == 0
    assert "(no webhooks" in capsys.readouterr().out


def test_list_shows_registered(
    isolated_profile: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    cli.main(["add", "--auth", "none", "--skill", "alpha"])
    cli.main(["add", "--auth", "none", "--skill", "beta"])
    capsys.readouterr()  # drain
    rc = cli.main(["list"])
    out = capsys.readouterr().out
    assert "skill:alpha" in out
    assert "skill:beta" in out


def test_list_marks_disabled(
    isolated_profile: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    cli.main(["add", "--auth", "none", "--skill", "x"])
    capsys.readouterr()
    rows = _read_store(isolated_profile).list()
    cli.main(["disable", rows[0].id])
    capsys.readouterr()
    rc = cli.main(["list"])
    assert "disabled" in capsys.readouterr().out


def test_list_json(
    isolated_profile: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    cli.main(["add", "--auth", "none", "--skill", "x"])
    capsys.readouterr()
    cli.main(["list", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert isinstance(payload, list)
    assert payload[0]["skill_name"] == "x"


def test_info_returns_full_record(
    isolated_profile: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    cli.main(["add", "--auth", "none", "--skill", "x", "--description", "the description"])
    capsys.readouterr()
    rows = _read_store(isolated_profile).list()
    cli.main(["info", rows[0].id])
    payload = json.loads(capsys.readouterr().out)
    assert payload["id"] == rows[0].id
    assert payload["description"] == "the description"


def test_info_unknown_returns_2(
    isolated_profile: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    rc = cli.main(["info", "never"])
    assert rc == 2


# ---- remove / enable / disable ------------------------------------


def test_remove_deletes_row(
    isolated_profile: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    cli.main(["add", "--auth", "none", "--skill", "x"])
    capsys.readouterr()
    rows = _read_store(isolated_profile).list()
    rc = cli.main(["remove", rows[0].id])
    assert rc == 0
    assert _read_store(isolated_profile).list() == []


def test_remove_unknown_returns_2(
    isolated_profile: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    rc = cli.main(["remove", "ghost"])
    assert rc == 2


def test_disable_then_enable(
    isolated_profile: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    cli.main(["add", "--auth", "none", "--skill", "x"])
    capsys.readouterr()
    rows = _read_store(isolated_profile).list()
    cli.main(["disable", rows[0].id])
    assert _read_store(isolated_profile).get(rows[0].id).enabled is False
    cli.main(["enable", rows[0].id])
    assert _read_store(isolated_profile).get(rows[0].id).enabled is True


def test_disable_unknown_returns_2(
    isolated_profile: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    rc = cli.main(["disable", "ghost"])
    assert rc == 2


# ---- test ---------------------------------------------------------


def test_test_unknown_returns_2(
    isolated_profile: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    rc = cli.main(["test", "ghost"])
    assert rc == 2


def test_test_hmac_request_signs_body(
    isolated_profile: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    """Synthetic POST signs the body with HMAC using the stored
    secret; we verify by intercepting httpx.post."""
    cli.main(["add", "--auth", "hmac_sha256", "--secret", "shh", "--skill", "x"])
    capsys.readouterr()
    rows = _read_store(isolated_profile).list()
    rid = rows[0].id

    captured: dict = {}

    def fake_post(url, *, content, headers, timeout=10.0):
        captured["url"] = url
        captured["content"] = content
        captured["headers"] = headers
        # Return a 202-shaped response.
        return httpx.Response(202, text="accepted")

    with patch.object(httpx, "post", side_effect=fake_post):
        rc = cli.main(["test", rid])

    assert rc == 0
    assert "X-Webhook-Signature" in captured["headers"]
    expected_sig = hmac.new(
        b"shh",
        captured["content"],
        hashlib.sha256,
    ).hexdigest()
    assert captured["headers"]["X-Webhook-Signature"] == expected_sig


def test_test_bearer_request_carries_authorization(
    isolated_profile: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    cli.main(["add", "--auth", "bearer", "--secret", "tok-123", "--skill", "x"])
    capsys.readouterr()
    rows = _read_store(isolated_profile).list()
    captured: dict = {}

    def fake_post(url, *, content, headers, timeout=10.0):
        captured["headers"] = headers
        return httpx.Response(202, text="accepted")

    with patch.object(httpx, "post", side_effect=fake_post):
        cli.main(["test", rows[0].id])

    assert captured["headers"]["Authorization"] == "Bearer tok-123"


def test_test_connection_failure_returns_1(
    isolated_profile: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    """Server not running → clear error + rc=1."""
    cli.main(["add", "--auth", "none", "--skill", "x"])
    capsys.readouterr()
    rows = _read_store(isolated_profile).list()
    with patch.object(
        httpx,
        "post",
        side_effect=httpx.ConnectError("connection refused"),
    ):
        rc = cli.main(["test", rows[0].id])
    assert rc == 1
    err = capsys.readouterr().err
    assert "unreachable" in err


def test_test_with_custom_payload_file(
    isolated_profile: Path,
    capsys: pytest.CaptureFixture,
    tmp_path: Path,
) -> None:
    cli.main(["add", "--auth", "none", "--skill", "x"])
    capsys.readouterr()
    rows = _read_store(isolated_profile).list()

    payload_file = tmp_path / "payload.json"
    payload_file.write_text(
        json.dumps({"custom": "value"}),
        encoding="utf-8",
    )

    captured: dict = {}

    def fake_post(url, *, content, headers, timeout=10.0):
        captured["content"] = content
        return httpx.Response(202, text="accepted")

    with patch.object(httpx, "post", side_effect=fake_post):
        cli.main(["test", rows[0].id, "--payload-file", str(payload_file)])

    assert b'"custom": "value"' in captured["content"]
