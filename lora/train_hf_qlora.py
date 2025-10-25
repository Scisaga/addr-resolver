#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CUDA_VISIBLE_DEVICES=0,1 torchrun --nproc_per_node=2 tianchi-new/train_hf_qlora.py \
  --data tianchi-new/sft.jsonl --bf16
"""
import argparse, os, torch
from datasets import load_dataset
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from transformers.trainer_callback import TrainerCallback
from peft import LoraConfig, prepare_model_for_kbit_training
from trl import SFTTrainer, SFTConfig

def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Qwen/Qwen3-8B", help="基座模型或本地路径")
    ap.add_argument("--data", required=True, help="train.jsonl 路径（instruction/input/output 三列）")
    ap.add_argument("--out", default="outputs/qwen3_8b_addr_qlora")
    ap.add_argument("--val_ratio", type=float, default=0.1)
    ap.add_argument("--max_len", type=int, default=512)
    ap.add_argument("--epochs", type=int, default=3)
    ap.add_argument("--bsz", type=int, default=4)
    ap.add_argument("--grad_accum", type=int, default=32)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--lora_r", type=int, default=16)
    ap.add_argument("--lora_alpha", type=int, default=32)
    ap.add_argument("--lora_dropout", type=float, default=0.05)
    ap.add_argument("--bf16", action="store_true", help="开启 bfloat16 训练")
    return ap.parse_args()

def is_main_process() -> bool:
    return int(os.environ.get("RANK", "0")) == 0

def build_bnb_config():
    return BitsAndBytesConfig(
        load_in_4bit=True, bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.bfloat16
    )

def to_prompt_completion(example):
    instr = (example.get("instruction") or "").strip()
    inp   = (example.get("input") or "").strip()
    out   = (example.get("output") or "").strip()
    prompt     = f"{instr}\n\n### 输入：{inp}"
    completion = f"### 输出：{out}"
    return {"prompt": prompt, "completion": completion}

class ProgressPrinter(TrainerCallback):
    """在 on_log 钩子里打印关键信息；仅 rank0 输出。"""
    def on_log(self, args, state, control, logs=None, **kwargs):
        if not is_main_process() or logs is None:
            return
        step = state.global_step
        keys = ["loss", "learning_rate", "eval_loss"]
        parts = [f"{k}={logs[k]:.6f}" for k in keys if k in logs and isinstance(logs[k], (int, float))]
        if parts:
            print(f"[step {step}] " + " | ".join(parts), flush=True)

def main():
    args = parse_args()
    bnb_config = build_bnb_config()

    local_rank = int(os.environ.get("LOCAL_RANK", 0))
    torch.cuda.set_device(local_rank)

    tokenizer = AutoTokenizer.from_pretrained(args.model, use_fast=False, trust_remote_code=True)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    if is_main_process(): print(">> 加载基座模型（4-bit QLoRA）")
    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        quantization_config=bnb_config,
        trust_remote_code=True,
        low_cpu_mem_usage=True,
    )
    model.config.use_cache = False
    model = prepare_model_for_kbit_training(                  # ✅ 只在这里启用/配置 ckpt
        model,
        use_gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
    )

    if is_main_process(): print(">> 读取并转换数据为 prompt/completion")
    ds = load_dataset("json", data_files=args.data, split="train")
    if 0.0 < args.val_ratio < 1.0:
        ds = ds.train_test_split(test_size=args.val_ratio, seed=42)
        train_ds = ds["train"].map(to_prompt_completion, remove_columns=ds["train"].column_names)
        val_ds   = ds["test"].map(to_prompt_completion,  remove_columns=ds["test"].column_names)
    else:
        train_ds = ds.map(to_prompt_completion, remove_columns=ds.column_names)
        val_ds   = None

    if is_main_process(): print(">> 配置 LoRA")
    peft_cfg = LoraConfig(
        r=args.lora_r, lora_alpha=args.lora_alpha, lora_dropout=args.lora_dropout,
        bias="none", task_type="CAUSAL_LM",
        target_modules=["q_proj","k_proj","v_proj","o_proj","gate_proj","up_proj","down_proj"],
    )

    # === 计算总优化步 & 建议步频 ===
    world_size = int(os.environ.get("WORLD_SIZE", "1"))
    micro_bsz = args.bsz
    gbs = micro_bsz * world_size * args.grad_accum  # 全局 batch size
    steps_per_epoch = max(1, len(train_ds) // gbs)
    total_steps = steps_per_epoch * args.epochs
    interval = max(1, total_steps // 20)  # 约 20 个点

    if is_main_process():
        print(f">> gbs={gbs}, steps/epoch={steps_per_epoch}, total_steps={total_steps}, "
            f"log/eval/save every {interval} steps")
    
    sft_cfg = SFTConfig(
        output_dir=args.out,
        per_device_train_batch_size=args.bsz,
        gradient_accumulation_steps=args.grad_accum,
        num_train_epochs=args.epochs,
        learning_rate=args.lr,
        lr_scheduler_type="cosine",
        warmup_ratio=0.05,

        # —— 显式训练进度 —— #
        logging_strategy="steps",
        logging_steps=1,
        logging_first_step=True,
        disable_tqdm=False, # 保留 tqdm 进度条

        eval_strategy="steps" if val_ds is not None else "no",  # ✅ 别漏
        eval_steps=20 if val_ds is not None else None,

        save_strategy="steps",
        save_steps=20,
        save_total_limit=2,

        report_to=["tensorboard"],

        bf16=args.bf16,
        fp16=not args.bf16,
        max_length=args.max_len,
        packing=False,
        completion_only_loss=True,
        ddp_find_unused_parameters=False,  # ✅ 建议：LoRA 任务更稳
    )

    if is_main_process(): print(">> 构建 Trainer 并训练")
    trainer = SFTTrainer(
        model=model,
        args=sft_cfg,
        processing_class=tokenizer,
        peft_config=peft_cfg,
        train_dataset=train_ds,
        eval_dataset=val_ds,
    )
    trainer.add_callback(ProgressPrinter())  # ✅ 关键：显式打印 step/loss/lr

    trainer.train()
    if is_main_process():
        print(">> 保存 LoRA 适配器与分词器")
    trainer.save_model(args.out)
    tokenizer.save_pretrained(args.out)
    if is_main_process():
        print(">> 完成，权重已保存在：", args.out)

if __name__ == "__main__":
    main()
