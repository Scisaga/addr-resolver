#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, torch
from transformers import AutoTokenizer, BitsAndBytesConfig
from peft import AutoPeftModelForCausalLM

# 强制离线，只走本地缓存
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

ADAPTER_DIR = "outputs/qwen3_8b_addr_qlora/checkpoint-100"

bnb = BitsAndBytesConfig(
    load_in_4bit=True, bnb_4bit_quant_type="nf4",
    bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.bfloat16
)

# ✅ 用“适配器目录”里的 tokenizer（与训练一致）
tok = AutoTokenizer.from_pretrained(ADAPTER_DIR, use_fast=False, trust_remote_code=True, local_files_only=True)
if tok.pad_token_id is None:
    tok.pad_token = tok.eos_token
tok.padding_side = "right"

# ✅ 直接从适配器加载（AutoPeft 会自动找到基座），保持多卡分片
model = AutoPeftModelForCausalLM.from_pretrained(
    ADAPTER_DIR,
    quantization_config=bnb,
    device_map="auto",
    trust_remote_code=True,
    local_files_only=True,
).eval()

# —— 验证 LoRA 是否真的加载 —— #
try:
    print(">> active adapters:", getattr(model, "active_adapter", None))
    # 打印若干 lora 权重名以确认挂载成功
    lora_names = [n for n, _ in model.named_parameters() if "lora_" in n][:6]
    print(">> sample lora params:", lora_names)
except Exception as e:
    print(">> PEFT check failed:", e)

def infer(addr_text: str) -> str:
    # ✅ 在“### 输出：”后面加一个空格，避免 tokenizer 把句子看成完整序列
    prompt = (
        "从以下地址文本中抽取要素，并按XML标签输出（只输出标签串）：\n\n"
        f"### 输入：{addr_text}\n### 输出： "
    )

    # ✅ 不加 special tokens，避免无意引入 BOS/EOS
    inputs = tok(prompt, return_tensors="pt", add_special_tokens=False)
    # ✅ 把输入放到“嵌入层所在设备”，不要用 model.device（分片模型没这个概念）
    device = model.get_input_embeddings().weight.device
    inputs = {k: v.to(device) for k, v in inputs.items()}

    # （可选）观察末尾 token 是否已经是 eos
    # print(tok.convert_ids_to_tokens(inputs["input_ids"][0][-8:].tolist()))

    with torch.no_grad():
        out = model.generate(
            **inputs,
            max_new_tokens=256,
            do_sample=False,                 # 先用贪心；如仍空，可以改成 do_sample=True, temperature=0.7, top_p=0.9
            min_new_tokens=1,                # ✅ 至少生成一个 token，避免 step=0 就停
            eos_token_id=tok.eos_token_id,
            pad_token_id=tok.pad_token_id,
        )

    full = tok.decode(out[0], skip_special_tokens=True)
    ans = full.split("### 输出：", 1)[-1].strip()
    if not ans:
        print("[DEBUG] full text:\n", full)
    return ans

if __name__ == "__main__":
    print(infer("上海市徐汇区佳安公寓宛平南路000弄0号楼"))
