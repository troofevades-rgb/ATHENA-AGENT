"""QLoRA fine-tune of a Qwen2.5-Coder model using Unsloth.

Hardware target: single GPU with 16GB VRAM (e.g. RTX 4070 Ti Super).
At 4-bit base + LoRA r=32 + seq_len=4096, peak VRAM lands around 11–13 GB
during training. Drop seq_len to 2048 or LoRA rank to 16 if you OOM.

Outputs:
  - ./outputs/checkpoint-*    : intermediate checkpoints
  - ./lora_out/               : final LoRA adapter (small, ~200MB)

Then run export_to_ollama.py to merge + GGUF + Ollama Modelfile.

Install (CUDA 12.x):
    pip install --upgrade --no-cache-dir \\
        "unsloth[cu121-ampere-torch240] @ git+https://github.com/unslothai/unsloth.git"
    pip install --no-deps trl peft accelerate bitsandbytes datasets

(The exact extras tag changes — check https://github.com/unslothai/unsloth
 for the current install string for your CUDA + GPU arch.)
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="Qwen/Qwen2.5-Coder-14B-Instruct",
                    help="HF model id or local path of base model. "
                         "Default is the regular Qwen2.5-Coder, NOT abliterated; "
                         "fine-tuning on domain content suppresses refusals more "
                         "surgically without the calibration tax.")
    ap.add_argument("--train", default="train.jsonl")
    ap.add_argument("--val", default="val.jsonl")
    ap.add_argument("--out", default="lora_out")
    ap.add_argument("--seq-len", type=int, default=4096)
    ap.add_argument("--rank", type=int, default=32, help="LoRA rank")
    ap.add_argument("--alpha", type=int, default=32, help="LoRA alpha")
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--batch", type=int, default=2,
                    help="Per-device batch size; bump to 4 on bigger GPUs")
    ap.add_argument("--grad-accum", type=int, default=4,
                    help="Effective batch = batch * grad_accum")
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--seed", type=int, default=3407)
    ap.add_argument("--max-steps", type=int, default=-1,
                    help="Cap steps for a quick smoke test (e.g. 50). -1 = full epochs.")
    ap.add_argument("--checkpoint-dir", default="outputs",
                    help="Where HF Trainer writes intermediate checkpoint-N "
                         "snapshots. Defaults to ./outputs for backward "
                         "compatibility; athena's runner now passes "
                         "<run_output>/checkpoints to isolate runs.")
    ap.add_argument("--resume-from-checkpoint", default=None,
                    help="Path to a specific checkpoint-N directory to "
                         "resume from. HF Trainer restores step / optimizer "
                         "/ scheduler / LR state. If omitted, training "
                         "starts from step 0.")
    args = ap.parse_args()

    # Imports deferred so --help works without unsloth installed
    import torch
    from unsloth import FastLanguageModel
    from datasets import load_dataset
    from trl import SFTTrainer
    from transformers import TrainingArguments

    print(f"Loading base model: {args.base}")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.base,
        max_seq_length=args.seq_len,
        dtype=None,            # auto: bf16 on Ampere+, fp16 on older
        load_in_4bit=True,     # QLoRA — 4-bit base
    )

    print(f"Attaching LoRA adapters (r={args.rank}, alpha={args.alpha})")
    model = FastLanguageModel.get_peft_model(
        model,
        r=args.rank,
        target_modules=[
            "q_proj", "k_proj", "v_proj", "o_proj",
            "gate_proj", "up_proj", "down_proj",
        ],
        lora_alpha=args.alpha,
        lora_dropout=0,           # 0 is unsloth-optimized
        bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=args.seed,
    )

    # Build chat-formatted dataset
    print(f"Loading training data: {args.train}")
    train_ds = load_dataset("json", data_files=args.train, split="train")
    val_ds = None
    if Path(args.val).exists():
        val_ds = load_dataset("json", data_files=args.val, split="train")

    def format_example(example):
        text = tokenizer.apply_chat_template(
            example["messages"], tokenize=False, add_generation_prompt=False,
        )
        return {"text": text}

    train_ds = train_ds.map(format_example, remove_columns=train_ds.column_names)
    if val_ds is not None:
        val_ds = val_ds.map(format_example, remove_columns=val_ds.column_names)

    bf16 = torch.cuda.is_available() and torch.cuda.is_bf16_supported()

    training_args = TrainingArguments(
        per_device_train_batch_size=args.batch,
        gradient_accumulation_steps=args.grad_accum,
        warmup_ratio=0.05,
        num_train_epochs=args.epochs,
        max_steps=args.max_steps,
        learning_rate=args.lr,
        fp16=not bf16,
        bf16=bf16,
        logging_steps=5,
        eval_strategy="steps" if val_ds is not None else "no",
        eval_steps=50,
        save_strategy="steps",
        save_steps=100,
        save_total_limit=2,
        optim="adamw_8bit",
        weight_decay=0.01,
        lr_scheduler_type="cosine",
        seed=args.seed,
        output_dir=args.checkpoint_dir,
        report_to="none",          # no W&B, no telemetry
    )

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=train_ds,
        eval_dataset=val_ds,
        dataset_text_field="text",
        max_seq_length=args.seq_len,
        args=training_args,
        packing=False,             # safer; turn on if you want throughput
    )

    print(f"Starting training. Checkpoints land in {args.checkpoint_dir}/")
    print(f"  effective batch size: {args.batch * args.grad_accum}")
    print(f"  bf16: {bf16}")
    if args.resume_from_checkpoint:
        print(f"  resuming from: {args.resume_from_checkpoint}")
        trainer.train(resume_from_checkpoint=args.resume_from_checkpoint)
    else:
        trainer.train()

    print(f"Saving LoRA adapter to {args.out}")
    Path(args.out).mkdir(parents=True, exist_ok=True)
    model.save_pretrained(args.out)
    tokenizer.save_pretrained(args.out)

    # Drop a small manifest for reproducibility
    (Path(args.out) / "training_meta.json").write_text(json.dumps({
        "base_model": args.base,
        "lora_rank": args.rank,
        "lora_alpha": args.alpha,
        "seq_len": args.seq_len,
        "epochs": args.epochs,
        "effective_batch": args.batch * args.grad_accum,
        "lr": args.lr,
        "seed": args.seed,
    }, indent=2), encoding="utf-8")

    print("Done. Next step: python export_to_ollama.py --adapter", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
