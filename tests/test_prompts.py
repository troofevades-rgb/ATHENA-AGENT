from pathlib import Path

from athena.prompts.system import (
    LEAN_KEEP,
    SECTIONS,
    TIGHT_RULES,
    build_system_prompt,
)

WORKSPACE = Path("/tmp")
MODEL = "test-model"


def test_default_includes_all_sections():
    out = build_system_prompt(workspace=WORKSPACE, model=MODEL)
    for body in SECTIONS.values():
        assert body in out


def test_lean_keeps_only_lean_set():
    out = build_system_prompt(workspace=WORKSPACE, model=MODEL, lean=True)
    for key, body in SECTIONS.items():
        if key in LEAN_KEEP:
            assert body in out, f"lean dropped {key}"
        else:
            assert body not in out, f"lean kept {key}"


def test_disabled_sections_drop_named_blocks():
    out = build_system_prompt(
        workspace=WORKSPACE,
        model=MODEL,
        disabled_sections=["executing_with_care", "session_guidance"],
    )
    assert SECTIONS["executing_with_care"] not in out
    assert SECTIONS["session_guidance"] not in out
    # Non-disabled sections still present
    assert SECTIONS["identity"] in out
    assert SECTIONS["tight_rules"] in out


def test_disabled_overrides_lean_when_keys_overlap():
    # tight_rules is in LEAN_KEEP; disabling it must remove it even in lean mode.
    out = build_system_prompt(
        workspace=WORKSPACE,
        model=MODEL,
        lean=True,
        disabled_sections=["tight_rules"],
    )
    assert TIGHT_RULES not in out


def test_unknown_disabled_names_are_ignored():
    # Forward-compat: a config from an older repo with renamed sections should
    # not blow up; unknown keys are silently ignored.
    out = build_system_prompt(
        workspace=WORKSPACE,
        model=MODEL,
        disabled_sections=["does_not_exist", "also_fake"],
    )
    # All real sections still rendered.
    for body in SECTIONS.values():
        assert body in out
