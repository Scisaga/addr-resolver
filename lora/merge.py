#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, torch
from transformers import AutoTokenizer
from peft import AutoPeftModelForCausalLM

# 彻底离线
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

ADAPTER = "outputs/qwen3_8b_addr_qlora/checkpoint-100"   # ← 用你要合并的 ckpt（100/117 二选一）
SAVE_DIR = "outputs/qwen3_8b_addr_merged"

# 1) 用“适配器目录”里的 tokenizer（训练时已保存，避免去拉 base 的 tokenizer）
tok = AutoTokenizer.from_pretrained(
    ADAPTER, use_fast=False, trust_remote_code=True, local_files_only=True
)

# 2) 直接从适配器加载基座+LoRA（AutoPeft 会读取 adapter_config.json 的 base_model_name_or_path）
#    local_files_only=True 会只用本地缓存，不做任何网络请求
model = AutoPeftModelForCausalLM.from_pretrained(
    ADAPTER,
    device_map="cpu",                 # 合并在 CPU，内存需 ~16GB（8B-bf16）
    dtype=torch.bfloat16,
    trust_remote_code=True,
    local_files_only=True,
)

# 3) 合并 LoRA 回基座并保存为“纯整模型”
model = model.merge_and_unload()
model.save_pretrained(SAVE_DIR, safe_serialization=True, max_shard_size="4GB")
tok.save_pretrained(SAVE_DIR)

print("Merged to:", SAVE_DIR)
