#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
调用 Hugging Face TGI /generate 接口，对地址做抽取，并解析为 KV 结构。

先启动 TGI（示例，按你的机器调整 shard/端口）：
docker run --gpus all --shm-size 1g -p 8080:80 \
  -v $PWD/outputs/qwen3_8b_addr_merged:/data \
  ghcr.io/huggingface/text-generation-inference:latest \
  --model-id /data \
  --dtype bfloat16 \
  --num-shard 2 \
  --max-input-tokens 2048 --max-total-tokens 2304

需要：pip install requests
"""

import os, re, requests
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # 当前文件所在目录

##
ENV_PATH = os.path.join(BASE_DIR, "../.env")
load_dotenv(str(ENV_PATH))

STRUCT_LLM_URL = os.environ.get("STRUCT_LLM_URL", "http://127.0.0.1:8080")  # 可用环境变量覆盖
STRUCT_LLM_TOKEN = os.environ.get("STRUCT_LLM_TOKEN", None)                 # 若服务启用鉴权，填 Bearer token

def build_prompt(addr_text: str) -> str:
    return (
        "从以下地址文本中抽取要素，并按XML标签输出（只输出标签串）：\n\n"
        f"### 输入：{addr_text}\n### 输出： "
    )

# 解析 <key>value</key>，同名标签合并为 list
_TAG_RE = re.compile(r"<([a-zA-Z0-9_]+)>(.*?)</\1>", re.DOTALL)

def parse_xmlish_tags(tag_text: str) -> dict:
    result = {}
    for m in _TAG_RE.finditer(tag_text or ""):
        k = m.group(1).strip()
        v = m.group(2).strip()
        if not k:
            continue
        if k not in result:
            result[k] = v
        else:
            if isinstance(result[k], list):
                if v not in result[k]:
                    result[k].append(v)
            else:
                if v != result[k]:
                    result[k] = [result[k], v]
    return result

def call_tgi_generate(prompt: str, max_new_tokens: int = 256) -> str:
    url = f"{STRUCT_LLM_URL}/generate"
    headers = {"Content-Type": "application/json"}
    if STRUCT_LLM_TOKEN:
        headers["Authorization"] = f"Bearer {STRUCT_LLM_TOKEN}"

    payload = {
        "inputs": prompt,
        "parameters": {
            "max_new_tokens": max_new_tokens,
            "do_sample": False,          # 结构化抽取 → 确定性
            "temperature": 0.0,
            "top_p": 1.0,
            "return_full_text": False,   # 只要新生成部分
            # 如需强约束可设置停止序列：
            # "stop": ["\n###", "</town>"]
        }
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    # TGI 返回 {"generated_text": "..."}
    return data.get("generated_text", "")

def infer(addr_text: str, max_new_tokens: int = 256):
    prompt = build_prompt(addr_text)
    gen = call_tgi_generate(prompt, max_new_tokens=max_new_tokens)
    text = gen.strip()
    tags = parse_xmlish_tags(text)
    return {"text": text, "tags": tags}  # TGI /generate 不直接回 token 数

if __name__ == "__main__":
    q = "上海市徐汇区佳安公寓宛平南路000弄0号楼"
    res = infer(q, max_new_tokens=256)
    print(res)