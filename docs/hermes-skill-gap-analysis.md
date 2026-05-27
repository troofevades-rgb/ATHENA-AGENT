# Hermes Agent Skill Gap Analysis

**Date:** 2026-05-24
**Source:** [Undermybelt/hermes-skills](https://github.com/Undermybelt/hermes-skills) (900+ skills across 32 top-level categories)

## Athena's Current Skills (4)

| Skill | Category | Status |
|-------|----------|--------|
| `git-commit-style` | Conventions | active |
| `python-typing-style` | Conventions | active |
| `osint-research` | Research / OSINT | active |
| `self-improvement-loop` | Meta / Self-improvement | active |

## Hermes Skill Categories vs. Athena Coverage

### COVERED (athena has equivalent functionality)

| Hermes Category | Hermes Skills | Athena Equivalent |
|----------------|--------------|-------------------|
| `social-media/xitter`, `xurl` | X/Twitter interaction | Built-in `search_x` + `lookup_x_user` tools (T6-02) |
| `software-development/systematic-debugging` | Debugging workflows | Built-in `Diagnose` tool (T5-03R) |
| `software-development/test-driven-development` | TDD patterns | Built-in test runner via Bash |
| `software-development/requesting-code-review` | Code review | Built-in background review fork |
| `software-development/writing-plans` | Planning | Built-in `EnterPlanMode` / `ExitPlanMode` tools |
| `mcp/native-mcp` | MCP server integration | Built-in stdio + HTTP/SSE MCP (Phase 12) |
| `software-development/skill-routing-governance` | Skill management | Built-in skill system (Phase 1) |
| `software-development/slash-command-routing` | Command routing | Built-in slash commands in `__main__.py` |
| `devops/autoskills` | Auto-skill creation | `self-improvement-loop` skill + curator |

### HIGH-PRIORITY GAPS (directly useful, athena has the infrastructure)

| Hermes Skill | Category | Why it matters | Athena infrastructure ready? |
|-------------|----------|---------------|------------------------------|
| `research/arxiv-research-synthesis` | Research | Paper discovery + summarization | Yes — WebFetch + WebSearch tools exist |
| `research/auto-research` | Research | Multi-source deep research | Yes — Agent tool for sub-tasks exists |
| `productivity/ocr-and-documents` | Productivity | PDF/image text extraction | Yes — T4-06 OCR tool exists |
| `productivity/nano-pdf` | Productivity | PDF generation | Partial — document_analyze reads PDFs, no write |
| `mlops/evaluation` | ML/Eval | Model eval benchmarks | Yes — Phase 7 eval framework exists |
| `mlops/training` | ML/Training | Fine-tuning workflows | Yes — Phase 7 transform/training pipeline |
| `mlops/huggingface-hub` | ML/Models | HF model management | Bash available, no dedicated tool |
| `data-science/jupyter-live-kernel` | Data Science | Jupyter notebook execution | Partial — can read .ipynb, no live kernel |
| `software-development/gap-driven-repo-implementation` | Dev | Analyze repo gaps, plan implementation | Yes — all tools available |
| `software-development/karpathy-coding-discipline` | Dev | High-quality coding patterns | Skill-only, easy to port |
| `software-development/hermes-agent-security-review` | Security | Security audit workflows | Yes — tirith scanner + security tools exist |
| `creative/architecture-diagram` | Creative | Generate architecture diagrams | Partial — diagramming possible via Bash |
| `creative/excalidraw` | Creative | Excalidraw diagram generation | No — would need browser tool |
| `mcp/open-computer-use` | Automation | Desktop control | Yes — T6-04 computer use tools exist |
| `github/github-repo-management` | Dev | GitHub automation | Yes — Bash with `gh` CLI |

### MEDIUM-PRIORITY GAPS (useful but less critical)

| Hermes Skill | Category | Notes |
|-------------|----------|-------|
| `productivity/google-workspace` | Productivity | Google Docs/Sheets/Drive — needs OAuth |
| `productivity/linear` | Productivity | Linear issue management via GraphQL |
| `productivity/notion` | Productivity | Notion workspace integration |
| `productivity/powerpoint` | Productivity | PPTX generation |
| `feeds/blogwatcher` | Research | RSS/blog monitoring |
| `media/youtube-content` | Media | YouTube transcript extraction |
| `media/songsee` | Media | Audio spectrogram analysis |
| `creative/manim-video` | Creative | Mathematical animation videos |
| `creative/p5js` | Creative | p5.js creative coding |
| `creative/ascii-art` | Creative | Terminal ASCII art generation |
| `mlops/vector-databases` | ML | Vector DB management (Chroma, Pinecone, etc.) |
| `mlops/inference` | ML | LLM inference optimization (vLLM, TGI) |
| `browser-harness-real-chrome` | Automation | Chrome CDP automation — athena has T4-03 Playwright |
| `smart-home` | IoT | Home Assistant integration |
| `gaming` | Leisure | Game server management |

### LOW-PRIORITY / NOT APPLICABLE

| Hermes Skill | Reason |
|-------------|--------|
| `apple/*` (findmy, shortcuts, homekit) | Platform-specific (macOS/iOS) |
| `red-teaming/godmode` | Security research — athena has safety guardrails by design |
| `domain/domain` | Domain registration — niche |
| `email/*` | Email automation — athena is a coding agent |
| `cognito-registration-flow` | AWS Cognito — very specific |
| `inference-sh` | inference.sh platform-specific |
| Various `ict-engine-*` | Internal to specific projects |

## Recommendations (Priority Order)

### 1. Port immediately (skill-only, no code changes)
These are pure SKILL.md files — instructions the model follows. No new tools needed:
- **`arxiv-research-synthesis`** — athena already has WebFetch/WebSearch
- **`karpathy-coding-discipline`** — coding quality patterns
- **`gap-driven-repo-implementation`** — structured repo analysis
- **`auto-research`** — multi-angle research methodology

### 2. Port with minor tool additions
- **`youtube-content`** — needs a YouTube transcript API call (single tool)
- **`nano-pdf`** — needs a PDF write capability (weasyprint or similar)
- **`linear`** — needs GraphQL client wrapper

### 3. Already built-in, just need skill documentation
Athena has the tools but no skill guiding their use:
- **Security review** — tirith + OSV + URL safety tools exist (T-MIG), need a skill combining them
- **Eval/benchmarking** — Phase 7 eval framework exists, need a skill for running evals
- **Training workflows** — Phase 7 transform pipeline exists, need a skill for end-to-end training

### 4. Infrastructure gaps (need new tools/integrations)
- **Google Workspace** — requires OAuth integration per service
- **Notion/Linear** — require API key management + dedicated tools
- **Live Jupyter kernel** — requires jupyter_client integration

## Summary

| Status | Count | Examples |
|--------|-------|---------|
| Already covered by built-in tools | ~12 | social search, debugging, code review, MCP, planning |
| Portable as skill-only (no code) | ~4 | arxiv research, coding discipline, auto-research |
| Needs minor tool additions | ~3 | YouTube, PDF write, Linear |
| Needs skill docs for existing tools | ~3 | security review, eval, training |
| Medium-priority integrations | ~15 | Google Workspace, Notion, vector DBs |
| Not applicable / low priority | ~10 | Apple-specific, domain reg, email |

**Athena's biggest advantage over Hermes:** athena already has a richer built-in tool surface (vision, audio, video, OCR, browser, computer use, MCP) than what most Hermes skills assume. The gap is mainly in **skill documentation** — teaching the model *when* and *how* to use the tools it already has.
