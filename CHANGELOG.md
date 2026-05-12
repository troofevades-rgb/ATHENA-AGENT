# Changelog

## Unreleased

### Added
- Toolset-scoped tool registry (Phase 0)
- ContextVar provenance tracking (Phase 0)
- Agent.fork() as a core primitive (Phase 0)
- Per-thread approval callback for safe fork execution (Phase 0)
- tool check_fn for capability-based tool advertisement (Phase 0)

### Changed
- Sub-agent dispatch tool now calls Agent.fork() under the hood
- ocode/agent.py split into ocode/agent/{core,fork}.py
