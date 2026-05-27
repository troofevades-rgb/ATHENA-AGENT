"""Markdown-backed user-modeling backend.

Storage: ``~/.athena/profiles/<profile>/user_model/<id>.md``
Each fact is one markdown file with frontmatter mirroring the
existing memory format, plus four extra fields recording
provenance and confidence (``source``, ``extracted_at``,
``session_id``, ``confidence``, ``category``).

The LLM is injected as a callable so the backend stays unit-
testable. Production code wires it to the agent's auxiliary
provider; tests pass a stub that returns a canned JSON string.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Awaitable, Callable
from datetime import date
from pathlib import Path

from .base import (
    BackendHealth,
    ExtractedFact,
    IngestResult,
    QueryResult,
    Transcript,
    UserModelBackend,
)

# A callable that takes a system+user prompt pair and returns the
# model's full response text. Async so production wiring can sit
# atop streaming providers without blocking the event loop, but
# the markdown backend never streams — it just awaits the full
# string.
LLMCall = Callable[[str, str], Awaitable[str]]


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.S)
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


_EXTRACT_SYSTEM_PROMPT = """\
You read conversation transcripts and pull out durable facts about
the user and their project. Output STRICT JSON only — a single array
of fact objects. Each fact:

  {
    "id": "kebab-case-stable-slug",       // ≤ 60 chars, [a-z0-9-_]
    "body": "one-paragraph fact body",
    "category": "communication-style | tech-stack | preferences |
                 project-context | workflow | other",
    "confidence": 0.0-1.0
  }

Rules:
- ONLY emit facts that would be surprising or non-obvious to a
  future-you reading the transcript fresh. Skip restating the
  obvious.
- Reuse an existing ID (passed in `existing_ids`) when you're
  updating a known fact — never invent a new ID for the same
  underlying observation.
- Output ONLY the JSON array. No commentary, no markdown fences,
  no leading prose. If no facts qualify, output ``[]``.
"""


_QUERY_SYSTEM_PROMPT = """\
You answer questions about a user and their project, using ONLY
the facts provided. Each fact is tagged ``[auto]`` (extracted from
prior sessions) or ``[user]`` (explicitly authored by the user).

Rules:
- If the facts don't support an answer, say so plainly. Don't
  invent. Don't generalize beyond the evidence.
- Prefer ``[user]`` facts when they conflict with ``[auto]`` facts —
  user-authored beats auto-extracted.
- Keep your answer under 200 words.
- After your answer, list the fact IDs you drew from on a single
  line prefixed ``SOURCES:`` (comma-separated). If you drew from
  no facts, output ``SOURCES: none``.
"""


class MarkdownUserModel:
    """Default user-model backend. Implements ``UserModelBackend``."""

    backend_name = "markdown"

    def __init__(
        self,
        storage_dir: Path,
        llm_call: LLMCall,
        *,
        authored_memory_dir: Path | None = None,
    ) -> None:
        """``storage_dir`` is where auto-extracted facts live. The
        optional ``authored_memory_dir`` lets ``query`` mix in user-
        authored memory (the existing ``~/.athena/projects/.../memory``
        files), tagging each source by provenance so the agent can
        weight them. Pass ``None`` to scope ``query`` to auto facts
        only."""
        self.storage_dir = storage_dir
        self._llm = llm_call
        self.authored_memory_dir = authored_memory_dir

    # ---- ingest --------------------------------------------------

    async def ingest_session(
        self, transcript: Transcript, *, session_id: str
    ) -> IngestResult:
        start = time.perf_counter()
        existing = self._load_existing_ids()
        prompt = self._build_extraction_prompt(transcript, existing)
        try:
            raw = await self._llm(_EXTRACT_SYSTEM_PROMPT, prompt)
        except Exception:  # noqa: BLE001
            return IngestResult(
                facts_added=0,
                facts_updated=0,
                duration_ms=int((time.perf_counter() - start) * 1000),
                backend=self.backend_name,
            )
        facts = _parse_extracted_facts(raw)
        added = 0
        updated = 0
        for fact in facts:
            if not _ID_RE.match(fact.id):
                continue  # silently drop bad IDs; don't crash extraction
            if fact.id in existing:
                updated += 1
            else:
                added += 1
            self._write_fact(fact, session_id=session_id)
        if facts:
            self._refresh_index()
        return IngestResult(
            facts_added=added,
            facts_updated=updated,
            duration_ms=int((time.perf_counter() - start) * 1000),
            backend=self.backend_name,
        )

    # ---- query ---------------------------------------------------

    async def query(
        self, question: str, *, max_tokens: int = 800
    ) -> QueryResult:
        auto_facts = self._load_auto_facts()
        user_facts = self._load_authored_facts()
        if not auto_facts and not user_facts:
            return QueryResult(
                answer="(no facts stored yet — nothing to recall)",
                sources=[],
                confidence=0.0,
            )
        prompt = self._build_query_prompt(
            question, auto=auto_facts, user=user_facts
        )
        try:
            raw = await self._llm(_QUERY_SYSTEM_PROMPT, prompt)
        except Exception as e:  # noqa: BLE001
            return QueryResult(
                answer=f"(memory query failed: {e})",
                sources=[],
                confidence=0.0,
            )
        answer, sources = _split_sources(raw)
        confidence = 1.0 if sources else 0.0
        return QueryResult(answer=answer, sources=sources, confidence=confidence)

    # ---- health --------------------------------------------------

    def health(self) -> BackendHealth:
        try:
            self.storage_dir.mkdir(parents=True, exist_ok=True)
            return BackendHealth(
                status="ready",
                reason=f"storage at {self.storage_dir}",
                backend=self.backend_name,
            )
        except OSError as e:
            return BackendHealth(
                status="down",
                reason=f"cannot create storage dir: {e}",
                backend=self.backend_name,
            )

    # ---- internals -----------------------------------------------

    def _load_existing_ids(self) -> set[str]:
        if not self.storage_dir.exists():
            return set()
        return {p.stem for p in self.storage_dir.glob("*.md") if p.stem != "INDEX"}

    def _load_auto_facts(self) -> list[tuple[str, str]]:
        """Return ``[(id, body), ...]`` for every auto-extracted
        fact on disk."""
        if not self.storage_dir.exists():
            return []
        out: list[tuple[str, str]] = []
        for p in sorted(self.storage_dir.glob("*.md")):
            if p.stem == "INDEX":
                continue
            parsed = _parse_fact_file(p)
            if parsed is not None:
                out.append((p.stem, parsed))
        return out

    def _load_authored_facts(self) -> list[tuple[str, str]]:
        d = self.authored_memory_dir
        if d is None or not d.exists():
            return []
        out: list[tuple[str, str]] = []
        for p in sorted(d.glob("*.md")):
            if p.name == "MEMORY.md":
                continue
            parsed = _parse_fact_file(p)
            if parsed is not None:
                out.append((p.stem, parsed))
        return out

    def _build_extraction_prompt(
        self, transcript: Transcript, existing_ids: set[str]
    ) -> str:
        lines: list[str] = []
        lines.append("existing_ids: " + (", ".join(sorted(existing_ids)) or "(none)"))
        lines.append("")
        lines.append("--- TRANSCRIPT ---")
        for msg in transcript:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if not isinstance(content, str):
                content = json.dumps(content)
            lines.append(f"[{role}] {content}")
        return "\n".join(lines)

    def _build_query_prompt(
        self,
        question: str,
        *,
        auto: list[tuple[str, str]],
        user: list[tuple[str, str]],
    ) -> str:
        lines: list[str] = ["--- FACTS ---"]
        for fid, body in auto:
            lines.append(f"[auto] {fid}: {body}")
        for fid, body in user:
            lines.append(f"[user] {fid}: {body}")
        lines.append("")
        lines.append("--- QUESTION ---")
        lines.append(question)
        return "\n".join(lines)

    def _write_fact(self, fact: ExtractedFact, *, session_id: str) -> Path:
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        target = self.storage_dir / f"{fact.id}.md"
        frontmatter = "\n".join(
            [
                "---",
                f"id: {fact.id}",
                f"category: {fact.category}",
                "source: auto",
                f"extracted_at: {date.today().isoformat()}",
                f"session_id: {session_id}",
                f"confidence: {fact.confidence:.2f}",
                "---",
                "",
            ]
        )
        target.write_text(frontmatter + fact.body.strip() + "\n", encoding="utf-8")
        return target

    def _refresh_index(self) -> None:
        if not self.storage_dir.exists():
            return
        lines: list[str] = ["# user_model index", ""]
        for p in sorted(self.storage_dir.glob("*.md")):
            if p.stem == "INDEX":
                continue
            parsed = _parse_fact_file(p)
            if parsed is None:
                continue
            preview = parsed.splitlines()[0][:100] if parsed else ""
            lines.append(f"- [{p.stem}]({p.name}) — {preview}")
        (self.storage_dir / "INDEX.md").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )


# ---- module-level helpers (no self) ----------------------------------


def _parse_fact_file(path: Path) -> str | None:
    """Read a fact file and return the body. Returns ``None`` on
    parse failure so a malformed file doesn't tank the whole load."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None
    return m.group(2).strip()


def _parse_extracted_facts(raw: str) -> list[ExtractedFact]:
    """Tolerant JSON parser — strips markdown code fences if the
    extractor model adds them despite instructions to the contrary."""
    text = raw.strip()
    if text.startswith("```"):
        # strip ```json ... ``` or ``` ... ```
        text = re.sub(r"^```[a-zA-Z]*\n", "", text)
        text = re.sub(r"\n```\s*$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    out: list[ExtractedFact] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            out.append(
                ExtractedFact(
                    id=str(item["id"]).strip(),
                    body=str(item["body"]).strip(),
                    category=str(item.get("category", "other")).strip(),
                    confidence=float(item.get("confidence", 0.5)),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _split_sources(raw: str) -> tuple[str, list[str]]:
    """Split the query LLM's output into (answer, sources list).
    The model is instructed to end with ``SOURCES: id1, id2, ...``
    or ``SOURCES: none``."""
    text = raw.strip()
    m = re.search(r"^SOURCES:\s*(.*)$", text, re.MULTILINE)
    if not m:
        return text, []
    answer = text[: m.start()].rstrip()
    sources_raw = m.group(1).strip()
    if sources_raw.lower() == "none" or not sources_raw:
        return answer, []
    sources = [s.strip() for s in sources_raw.split(",") if s.strip()]
    return answer, sources


# Static type check — instantiation would fail if Protocol drifted.
_: type[UserModelBackend] = MarkdownUserModel
