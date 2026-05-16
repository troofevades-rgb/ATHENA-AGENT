"""DPO fine-tune on top of an SFT LoRA.

Reads a JSONL dataset of preference pairs in the trl convention
(``{"prompt", "chosen", "rejected"}`` per line) and runs
``trl.DPOTrainer`` to nudge the SFT-tuned model toward the chosen
branch on each pair. The output is a *new* LoRA adapter on top of the
SFT LoRA — meant to be merged in the same way (export_to_ollama.py).

Hardware target matches ``train_lora.py``: a single 16GB GPU. Drop
``--seq-len`` or ``--rank`` if you OOM.

Companion to ``train_lora.py``; expects you've already produced an SFT
LoRA via that script. Pass its path via ``--sft-lora``.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--base",
        default="Qwen/Qwen2.5-Coder-14B-Instruct",
        help="HF model id or local path of the base model.",
    )
    ap.add_argument(
        "--sft-lora",
        required=True,
        help="Path to the SFT LoRA adapter produced by train_lora.py.",
    )
    ap.add_argument("--train", default="dpo.jsonl",
                    help="JSONL with {prompt, chosen, rejected} per line.")
    ap.add_argument("--out", default="lora_out_dpo")
    ap.add_argument("--seq-len", type=int, default=4096)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--alpha", type=int, default=16)
    ap.add_argument("--epochs", type=int, default=2,
                    help="DPO converges faster than SFT; 1-3 is typical.")
    ap.add_argument("--batch", type=int, default=2)
    ap.add_argument("--grad-accum", type=int, default=4)
    ap.add_argument("--lr", type=float, default=5e-6,
                    help="DPO wants a much smaller LR than SFT — 1e-6..5e-6.")
    ap.add_argument("--beta", type=float, default=0.1,
                    help="DPO beta — preference sharpness. Default 0.1.")
    ap.add_argument("--seed", type=int, default=3407)
    ap.add_argument("--max-steps", type=int, default=-1)
    args = ap.parse_args()

    # Imports deferred so --help works without trl / unsloth installed.
    import torch
    from datasets import load_dataset
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from trl import DPOConfig, DPOTrainer

    print(f"Loading base model: {args.base}")
    base = AutoModelForCausalLM.from_pretrained(
        args.base, torch_dtype=torch.bfloat16, device_map="auto",
    )
    tokenizer = AutoTokenizer.from_pretrained(args.base)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    print(f"Attaching SFT LoRA: {args.sft_lora}")
    model = PeftModel.from_pretrained(base, args.sft_lora, is_trainable=True)

    print(f"Loading DPO dataset: {args.train}")
    ds = load_dataset("json", data_files=args.train, split="train")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    config = DPOConfig(
        output_dir=str(out_dir),
        per_device_train_batch_size=args.batch,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        num_train_epochs=args.epochs,
        max_steps=args.max_steps,
        beta=args.beta,
        max_length=args.seq_len,
        seed=args.seed,
        bf16=True,
        logging_steps=10,
        save_strategy="epoch",
    )

    trainer = DPOTrainer(
        model=model,
        ref_model=None,  # peft handles reference via the adapter delta
        args=config,
        train_dataset=ds,
        processing_class=tokenizer,
    )
    trainer.train()
    trainer.save_model(str(out_dir / "lora_out"))
    tokenizer.save_pretrained(str(out_dir / "lora_out"))
    print(f"DPO LoRA written to {out_dir / 'lora_out'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
