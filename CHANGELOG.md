# Changelog

## Unreleased

### Added
- Toolset-scoped tool registry (Phase 0)
- ContextVar provenance tracking (Phase 0)
- Agent.fork() as a core primitive (Phase 0)
- Per-thread approval callback for safe fork execution (Phase 0)
- tool check_fn for capability-based tool advertisement (Phase 0)
- agentskills.io-compliant skill format (Phase 1)
- Skill state machine (active/stale/archived) (Phase 1)
- Pinning and archive directory (Phase 1)
- Class-level umbrella architecture (references/templates/scripts) (Phase 1)
- skills_list, skill_view, skill_manage tools (Phase 1)
- ocode import-from-hermes for Hermes Agent migration (Phase 1)
- Progressive disclosure of skill catalog in system prompt (Phase 1)

### Changed
- Sub-agent dispatch tool now calls Agent.fork() under the hood
- ocode/agent.py split into ocode/agent/{core,fork}.py
- ocode/skills/ (slash-command handlers) renamed to ocode/commands/ to free
  the name for the new file-based skill format
