---
description: Analyzes task outcomes and generates improvements to skills, prompts,
  and workflows
name: self-improvement-loop
created_at: '2026-05-21T11:42:00Z'
last_activity_at: '2026-05-21T23:35:46Z'
pinned: false
state: active
use_count: 0
write_origin: foreground
---
# Skill Learning from Experience

This skill enables the agent to learn from completed tasks and create reusable skills automatically.

## Core Functionality

1. **Task Completion Analysis**: After completing a task, analyze what patterns or techniques were used
2. **Skill Extraction**: Identify reusable knowledge that could be encapsulated as a skill
3. **Skill Creation**: Generate new skills from extracted patterns
4. **Skill Refinement**: Improve existing skills based on new experiences

## Implementation

```python
import json
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional, Any
from dataclasses import dataclass, asdict
from __future__ import annotations

@dataclass
class TaskRecord:
    """Record of a completed task for learning."""
    task_id: str
    task_type: str
    techniques_used: list[str]
    tools_used: list[str]
    outcome: str
    success: bool
    duration_seconds: float
    timestamp: str
    
@dataclass
class SkillCandidate:
    """A potential new skill extracted from experience."""
    name: str
    description: str
    triggers: list[str]
    implementation: str
    confidence: float
    source_task: str

class SkillLearner:
    """Analyzes task completion and creates/refines skills."""
    
    def __init__(self, memory_dir: Path):
        self.memory_dir = memory_dir
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.records_file = self.memory_dir / "task_records.json"
        self.skills_dir = self.memory_dir / "learned_skills"
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        
    def record_task(self, task_id: str, task_type: str, techniques: list[str],
                    tools: list[str], outcome: str, success: bool,
                    duration: float):
        """Record a completed task for later analysis."""
        record = TaskRecord(
            task_id=task_id,
            task_type=task_type,
            techniques_used=techniques,
            tools_used=tools,
            outcome=outcome,
            success=success,
            duration_seconds=duration,
            timestamp=datetime.now().isoformat()
        )
        records = self._load_records()
        records.append(asdict(record))
        self._save_records(records)
        
    def analyze_for_skills(self, min_success_rate: float = 0.8) -> list[SkillCandidate]:
        """Analyze completed tasks and extract skill candidates."""
        records = self._load_records()
        successful = [r for r in records if r.get('success')]
        
        # Group by task type and find common techniques
        technique_counts: dict[str, int] = {}
        for record in successful:
            for technique in record.get('techniques_used', []):
                technique_counts[technique] = technique_counts.get(technique, 0) + 1
        
        # High-frequency techniques become skill candidates
        candidates = []
        for technique, count in technique_counts.items():
            if count >= 3:  # Used in 3+ successful tasks
                candidate = SkillCandidate(
                    name=f"{technique.replace('_', '-')}"
                    description=f"Use {technique} for {record.get('task_type')} tasks",
                    triggers=[record.get('task_type', 'general')],
                    implementation=f"# Implement {technique} pattern",
                    confidence=min(1.0, count / len(successful)),
                    source_task=record['task_id']
                )
                candidates.append(candidate)
        
        return candidates
    
    def create_skill_from_candidate(self, candidate: SkillCandidate,
                                    implementation: str) -> Path:
        """Create a new skill from a candidate."""
        skill_dir = self.skills_dir / candidate.name
        skill_dir.mkdir(parents=True, exist_ok=True)
        
        frontmatter = {
            "name": candidate.name,
            "description": candidate.description,
            "created_at": datetime.now().isoformat(),
            "source": candidate.source_task
        }
        
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text(
            f"---\n{json.dumps(frontmatter, indent=2)}\n---\n\n{implementation}"
        )
        return skill_dir
    
    def _load_records(self) -> list[dict]:
        if not self.records_file.exists():
            return []
        return json.loads(self.records_file.read_text())
    
    def _save_records(self, records: list[dict]):
        self.records_file.write_text(json.dumps(records, indent=2))
```

## Usage

Call `record_task` after completing a task to log it. Call `analyze_for_skills` periodically to find skill candidates. Create new skills using `create_skill_from_candidate`.

## Example

```python
learner = SkillLearner(Path("~/.athena/projects/my-workspace/memory"))
learner.record_task(
    task_id="task-123",
    task_type="refactor",
    techniques=["extract-method", "rename-variables"],
    tools=["Edit", "Read", "Grep"],
    outcome="cleaned up module",
    success=True,
    duration=120
)

candidates = learner.analyze_for_skills()
for candidate in candidates:
    print(f"New skill: {candidate.name} (confidence: {candidate.confidence})")
```