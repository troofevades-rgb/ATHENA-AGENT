# Closed training loop

ocode's headline differentiator: the agent reviews its own sessions,
trains a new LoRA + DPO adapter from them, merges it into a GGUF, and
registers the result with Ollama under a new tag. Subsequent sessions
run against the freshly-trained model.

This is a 1.0 launch demo path. Phase 7 wired it together end-to-end.

## Prerequisites

- A workstation with CUDA 12.x and a 16 GB-class GPU (RTX 4070 Ti Super
  or better for 14B at LoRA rank 32; smaller GPUs work for the 1.5 B
  base model used in the demo).
- `ollama` on PATH, with the base model already pulled
  (e.g. `ollama pull qwen2.5-coder:1.5b`).
- `llama.cpp` checked out somewhere — `transform/scripts/export_to_ollama.py`
  uses its `convert_hf_to_gguf.py` and `quantize` binary. Either set
  `LLAMA_CPP=<path>` or pass `--llama-cpp <path>`.
- Training extras installed: `pip install -e ".[train]"`. This pulls in
  trl, peft, transformers, datasets, accelerate, bitsandbytes. They are
  GPU-only and are NOT installed by default.

## One-shot flow

```bash
# 1. Run real sessions for some period (days / weeks).
ocode

# 2. Label trajectories.
ocode train review --since-days 30
#   For each trajectory: render → ask for [g]ood / [b]ad / [p]reference /
#   [s]kip / [q]uit. Labels persist to
#   ~/.ocode/profiles/default/labels/<session>.json — pick up from
#   where you left off on the next invocation.

# 3. Build the SFT + DPO JSONL files.
ocode train build-dataset --since-days 30
#   Writes transform/datasets/sft-<ts>.jsonl and dpo-<ts>.jsonl.
#   The SFT file is every "good"-labeled trajectory rendered in the
#   qwen-coder chat template. The DPO file pairs each
#   "preference_pair" trajectory with the immediately-prior "bad"
#   one in the same session — chosen = recovery, rejected = original.

# 4. Run training.
ocode train run \
  --base-model qwen2.5-coder:1.5b \
  --sft-dataset transform/datasets/sft-<ts>.jsonl \
  --dpo-dataset transform/datasets/dpo-<ts>.jsonl \
  --epochs 3 \
  --lora-rank 16
#   Phase 1: LoRA SFT     → transform/output/<output-name>/lora_out
#   Phase 2: DPO          → transform/output/<output-name>-dpo/lora_out
#   Phase 3: GGUF + ollama create <output-name>
#
# Output name defaults to <base>-ocode-<n>; --output-name overrides.

# 5. Inspect the new model.
ocode model list
ocode model info <new-name>

# 6. Switch the default.
ocode model switch <new-name>
#   Writes model = "<new-name>" to ~/.ocode/config.toml.
#   New ocode sessions use it; running sessions are unaffected (they
#   bind to whichever model they started with).

# 7. Check what shipped.
ocode train status
```

## How labels work

The auto-classifier in `ocode/transform/classifier.py` suggests a label
for obvious cases:

| Heuristic                                              | Suggested label    |
|--------------------------------------------------------|--------------------|
| Final tool result starts with `Error:` / `Traceback`   | `bad`              |
| Next user message starts with `no` / `wrong` / `undo`  | `bad`              |
| Trajectory contains `[/steer]` AND tail finishes clean | `preference_pair`  |
| Next user message starts with `thanks` / `perfect` / 👍| `good`             |
| anything else                                          | `unreviewed`       |

Only `user_label != "unreviewed"` trajectories are included in the SFT
dataset by default. `--include-auto-labels` opts into auto-`good`
trajectories whose user_label is still `unreviewed` — handy for bulk
adoption of clear wins. A user label always overrides the auto label.

## Where things live

| Path                                            | Purpose                              |
|-------------------------------------------------|--------------------------------------|
| `~/.ocode/profiles/<profile>/labels/`           | Per-session label JSON              |
| `transform/datasets/sft-<ts>.jsonl`             | SFT examples (OpenAI fine-tuning fmt)|
| `transform/datasets/dpo-<ts>.jsonl`             | DPO pairs (trl convention)          |
| `transform/output/<output-name>/`               | LoRA SFT adapter + intermediate ckpts|
| `transform/output/<output-name>-dpo/`           | LoRA DPO adapter on top              |
| `transform/output/<output-name>/Modelfile`      | Generated Modelfile (FROM gguf)     |
| `~/.ocode/training_state.json`                  | History of every `ocode train run`  |
| `~/.ocode/config.toml` (`model = "..."`)        | Default model for new sessions      |

## Customization

- **Chat template**: `--chat-template chatml` or `openai` if your base
  model uses a different template. Default is `qwen-coder`. Templates
  are validated against `SUPPORTED_CHAT_TEMPLATES` in
  `ocode/transform/dataset.py`.
- **Lower hardware floor**: pass `--lora-rank 8` and `--epochs 1`
  with the 1.5 B base for an end-to-end smoke run in ~30 minutes on a
  4070 Ti Super.
- **Higher quality**: bump `--epochs` and `--lora-rank` (32 for 14 B is
  the sweet spot). DPO benefits more from epochs than from rank.

## Invariants

1. Training is always opt-in. No cron job, plugin, or background fork
   auto-runs `ocode train run`. The user must invoke it explicitly.
2. Each run creates a NEW Ollama model tag (`<base>-ocode-<n>`). The
   base model is never overwritten.
3. `ocode model switch` only affects new sessions. Sessions in flight
   keep using the model they started with.
4. Failed runs preserve partial state (LoRA dirs on disk, training_state.
   json updated with the failing exit code) so the user can inspect and
   restart.

## Failure-mode FAQ

**Q: `ocode train run` exits 17 with "LoRA training failed".**
Look at `transform/output/<output-name>/`. Unsloth and trl print to
stderr; the subprocess re-emits it. Common causes: OOM (lower `--seq-len`
or `--lora-rank`), missing CUDA, version skew between unsloth and
torch.

**Q: GGUF export fails but training succeeded.**
`ensure_ollama_on_path()` returned true but the export step itself
failed. The SFT/DPO adapters are still on disk; re-run
`python transform/scripts/export_to_ollama.py` manually with explicit
arguments to debug.

**Q: `ocode model list` shows nothing.**
Either `ollama` isn't on PATH, or `ollama list` exited non-zero. The
parser is defensive — it returns empty rather than raising. Check
`ollama list` directly first.

## What's intentionally NOT here

- RL (PPO / GRPO). The plan ships with SFT + DPO. RL is post-1.0.
- Multi-GPU / distributed training. Single 16 GB box is the target.
- Auto-restart-after-train. Sessions don't reload mid-run; `ocode
  model switch` only affects fresh sessions.
- Web UI for review. The TUI is the canonical surface; a web review
  page is a post-1.0 question.
