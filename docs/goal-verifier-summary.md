# Goal Verifier Summary

The `goal_verifier_command` config option gates `GOAL ACHIEVED` claims by running an external shell command. When set, the agent's achievement claim is rejected unless the command exits with code 0. The `goal_verifier_timeout_s` knob (default: 120s) caps the verifier runtime.

**Example:**
```toml
goal_verifier_command = "pytest tests/ -q"
goal_verifier_timeout_s = 60
```