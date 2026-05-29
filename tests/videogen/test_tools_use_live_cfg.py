"""``video_generate`` must read the live agent's cfg, not a fresh
disk load. Without this, ``/video set xai_video`` (which mutates
``agent.cfg.video_backend`` in memory) is invisible to the tool and
generation silently routes to the stub.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


def _live_agent(**cfg_overrides):
    """Mint an agent stub with a cfg that carries the overrides.
    Post-R4 stage 5: video_* flat names are translated to the nested
    cfg.video_generation namespace."""
    legacy_to_nested = {
        "video_generation_enabled": "enabled",
        "video_backend": "backend",
        "video_backend_prefer": "backend_prefer",
        "video_confirm_over_seconds": "confirm_over_seconds",
        "video_confirm_over_cost": "confirm_over_cost",
        "video_output_dir": "output_dir",
        "video_poll_interval_s": "poll_interval_s",
    }
    vg = dict(
        enabled=True,
        backend=None,
        backend_prefer="local",
        confirm_over_seconds=60.0,
        confirm_over_cost=1.0,
        output_dir=None,
        poll_interval_s=0.01,
    )
    top: dict = {}
    for k, v in cfg_overrides.items():
        if k in legacy_to_nested:
            vg[legacy_to_nested[k]] = v
        elif k in vg:
            vg[k] = v
        else:
            top[k] = v
    agent = MagicMock()
    agent.cfg = SimpleNamespace(
        video_generation=SimpleNamespace(**vg),
        **top,
    )
    return agent


def test_load_cfg_prefers_live_agent_cfg():
    """When an agent is bound, _load_cfg returns its cfg — not a
    fresh disk load."""
    from athena.videogen import tools as tools_mod

    agent = _live_agent(video_backend="xai_video")
    with patch(
        "athena.agent.core.get_current_agent", return_value=agent,
    ):
        cfg = tools_mod._load_cfg()
    assert cfg is agent.cfg
    assert cfg.video_generation.backend == "xai_video"


def test_load_cfg_falls_back_to_disk_load_when_no_agent():
    """No bound agent → fall back to load_config() so CLI / batch /
    test contexts still work."""
    from athena.videogen import tools as tools_mod

    fake_disk_cfg = SimpleNamespace(
        video_generation=SimpleNamespace(backend=None),
    )
    with patch(
        "athena.agent.core.get_current_agent", return_value=None,
    ), patch(
        "athena.config.load_config", return_value=fake_disk_cfg,
    ):
        cfg = tools_mod._load_cfg()
    assert cfg is fake_disk_cfg


def test_load_cfg_falls_back_when_get_current_agent_raises():
    """A bad import / missing module shouldn't break tool dispatch.
    The defensive try/except in _load_cfg matters."""
    from athena.videogen import tools as tools_mod

    fake_disk_cfg = SimpleNamespace(
        video_generation=SimpleNamespace(backend=None),
    )
    with patch(
        "athena.agent.core.get_current_agent",
        side_effect=ImportError("simulated"),
    ), patch(
        "athena.config.load_config", return_value=fake_disk_cfg,
    ):
        cfg = tools_mod._load_cfg()
    assert cfg is fake_disk_cfg


def test_video_generate_routes_through_live_selector():
    """End-to-end through the dispatch path: when the live agent's
    cfg pins video_backend, the tool routes to that backend rather
    than the broker's auto-pick (which would land on the stub)."""
    from athena.videogen import tools as tools_mod

    agent = _live_agent(video_backend="xai_video")

    # Stub the actual backend so we can verify the pin was honoured
    # without making real HTTP calls.
    fake_backend = MagicMock()
    fake_backend.name = "xai_video"
    fake_backend.estimate.return_value = MagicMock(
        seconds_est=30.0, cost_est=None,
        needs_confirm=lambda cfg: False,
    )
    fake_backend.submit.return_value = MagicMock(
        backend="xai_video", job_id="job-fake", status="done",
        progress=1.0, extra={"poll_response": {}}, error=None,
    )
    fake_backend.poll.return_value = fake_backend.submit.return_value

    # Use a temp file the fake fetch will return.
    import tempfile
    from pathlib import Path

    tmp = Path(tempfile.mkdtemp()) / "out.mp4"
    tmp.write_bytes(b"FAKE-MP4")
    fake_backend.fetch.return_value = tmp

    with patch(
        "athena.agent.core.get_current_agent", return_value=agent,
    ), patch(
        "athena.videogen.tools.resolve_backend", return_value=fake_backend,
    ) as resolve_mock:
        tools_mod.video_generate(prompt="a cat", duration_s=3.0)

    # The tool called resolve_backend with the agent's live cfg
    # (which has video_backend='xai_video'), not a freshly-loaded
    # disk cfg.
    resolve_mock.assert_called_once()
    passed_cfg = resolve_mock.call_args[0][0]
    assert passed_cfg.video_generation.backend == "xai_video"
