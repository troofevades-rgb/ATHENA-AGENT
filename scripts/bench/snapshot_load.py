"""Snapshot-creation latency benchmark.

Measures :meth:`SnapshotStore.snapshot_and_mutate` against a 1 MB
skill tree (one SKILL.md ~64 KB + 15 reference files ~64 KB each).
Reports mean / p95 / p99 wall-clock in milliseconds over 30 runs.

The Phase 17.7 design budget is **mean < 50 ms** on a 1 MB tree.
If this regresses, the snapshot path has grown too much work
(usually: too many file members in the tar, sidecar I/O on the
critical path, or sha hashing of files that don't need it).
"""
from __future__ import annotations

import statistics
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

# Make sure repo root is importable when this is run directly.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _build_one_mb_skill_tree(root: Path) -> Path:
    skill_dir = root / "skills" / "bench_demo"
    skill_dir.mkdir(parents=True, exist_ok=True)
    body_chunk = "x" * 1024  # 1 KB
    skill_md = "---\nname: bench_demo\ndescription: bench fixture\n---\n\n"
    skill_md += body_chunk * 60  # ~64 KB
    (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")

    refs = skill_dir / "references"
    refs.mkdir(exist_ok=True)
    for i in range(15):
        (refs / f"ref_{i}.md").write_text(body_chunk * 64, encoding="utf-8")
    return skill_dir


def run() -> dict[str, Any]:
    """Returns a result dict compatible with scripts/bench/runner.py."""
    from athena.safety.snapshots import SnapshotStore

    with tempfile.TemporaryDirectory(prefix="athena-bench-snapshot-") as tmp:
        tmp_path = Path(tmp)
        store_root = tmp_path / "snapshots"
        skill_dir = _build_one_mb_skill_tree(tmp_path)
        store = SnapshotStore(root=store_root, relative_to=tmp_path)

        # Warm-up so the first-run tar/gzip cost doesn't skew the stats.
        with store.snapshot_and_mutate([skill_dir]):
            pass

        latencies_ms: list[float] = []
        for _ in range(30):
            t0 = time.perf_counter()
            with store.snapshot_and_mutate([skill_dir]):
                pass
            latencies_ms.append((time.perf_counter() - t0) * 1000.0)

    mean = statistics.mean(latencies_ms)
    p95 = statistics.quantiles(latencies_ms, n=20)[-1]  # 95th percentile
    try:
        p99 = statistics.quantiles(latencies_ms, n=100)[-1]
    except statistics.StatisticsError:
        p99 = max(latencies_ms)
    return {
        "name": "snapshot_load",
        "metric": "ms",
        "value": mean,
        "p95_ms": p95,
        "p99_ms": p99,
        "min_ms": min(latencies_ms),
        "max_ms": max(latencies_ms),
        "iterations": len(latencies_ms),
        "tree_size_bytes": 1_024 * 64 * 16,  # ~1 MB
    }


if __name__ == "__main__":
    result = run()
    print(
        f"snapshot_load: mean={result['value']:.2f} ms "
        f"p95={result['p95_ms']:.2f} ms "
        f"p99={result['p99_ms']:.2f} ms "
        f"(over {result['iterations']} runs on a ~{result['tree_size_bytes']/1024:.0f} KB tree)"
    )
