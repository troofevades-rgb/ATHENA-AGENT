#!/usr/bin/env python3
"""Load all godmode scripts into the current Python session.

This loader handles the __name__ == '__main__' issue that occurs when
scripts are executed via exec() in execute_code.
"""
import os
import sys
from pathlib import Path

def get_skill_dir():
    """Get the godmode skill directory."""
    # Check both workspace and ~/.athena/skills paths
    paths = [
        Path(__file__).parent.parent,
        Path.home() / ".athena" / "skills" / "godmode",
    ]
    for p in paths:
        if p.exists():
            return p
    raise FileNotFoundError("Could not find godmode skill directory")

def load_script(name):
    """Load a script into the current namespace."""
    skill_dir = get_skill_dir()
    script_path = skill_dir / "scripts" / f"{name}.py"
    
    if not script_path.exists():
        raise FileNotFoundError(f"Script not found: {script_path}")
    
    with open(script_path, "r") as f:
        code = f.read()
    
    # Execute in a namespace that prevents __main__ entry points
    namespace = {}
    exec(code, namespace)
    
    # Copy all non-underscore names to current namespace
    for name, obj in namespace.items():
        if not name.startswith("_"):
            globals()[name] = obj
            locals()[name] = obj

def load_all():
    """Load all godmode scripts."""
    scripts = ["auto_jailbreak", "parseltongue", "godmode_race"]
    for script in scripts:
        try:
            load_script(script)
            print(f"✓ Loaded {script}")
        except FileNotFoundError as e:
            print(f"✗ {script}: {e}")
    
    print("\nAvailable functions:")
    print("  auto_jailbreak(model=None, dry_run=False)")
    print("  parseltongue_encode(text, tier=1)")
    print("  godmode_race(queries, tier='standard')")

if __name__ == "__main__":
    load_all()
