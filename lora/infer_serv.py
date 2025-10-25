# server.py
import os, asyncio, torch, re
from fastapi import FastAPI
from pydantic import BaseModel
from transformers import AutoTokenizer, AutoModelForCausalLM

# 离线 & 更稳的日志
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
torch.set_grad_enabled(False)
torch.backends.cuda.matmul.allow_tf32 = True  # 如果是 A100/H100 系列

MERGED_DIR = "outputs/qwen3_8b_addr_merged"
CONCURRENCY = 2  # 每次并发生成的最大请求数（按你的GPU能力调）

# ---------- 1) 进程启动时只加载一次 ----------
tok = AutoTokenizer.from_pretrained(MERGED_DIR, use_fast=False, trust_remote_code=True)
if tok.pad_token_id is None:
    tok.pad_token = tok.eos_token
tok.padding_side = "right"

model = AutoModelForCausalLM.from_pretrained(
    MERGED_DIR,
    torch_dtype=torch.bfloat16,
    device_map="auto",                 # 多卡分片也可；单卡就改成 {"": 0}
    trust_remote_code=True,
).eval()

# ---------- 2) API ----------
app = FastAPI()
sema = asyncio.Semaphore(CONCURRENCY)

class Req(BaseModel):
    text: str
    max_new_tokens: int = 256
    do_sample: bool = False
    temperature: float = 0.7
    top_p: float = 0.9

def build_prompt(addr_text: str) -> str:
    return (
        "从以下地址文本中抽取要素，并按XML标签输出（只输出标签串）：\n\n"
        f"### 输入：{addr_text}\n### 输出： "
    )

_TAG_RE = re.compile(r"<([a-zA-Z0-9_]+)>(.*?)</\1>", re.DOTALL)

def parse_xmlish_tags(tag_text: str) -> dict:
    """
    将形如 <prov>浙江</prov><city>杭州市</city> 的串解析为 dict。
    - 同一标签出现多次 → 合并为 list，保持去重与顺序稳定
    - 值做 strip()，其余原样保留
    """
    result = {}
    for m in _TAG_RE.finditer(tag_text or ""):
        k = m.group(1).strip()
        v = m.group(2).strip()
        if not k:
            continue
        if k not in result:
            result[k] = v
        else:
            # 已有同名键：升格为 list，并去重
            if isinstance(result[k], list):
                if v not in result[k]:
                    result[k].append(v)
            else:
                if v != result[k]:
                    result[k] = [result[k], v]
                # 若与已有完全相同，忽略
    return result

@app.post("/infer")
async def infer(req: Req):
    prompt = build_prompt(req.text)

    async with sema:  # 简单的并发限制
        inputs = tok(prompt, return_tensors="pt", add_special_tokens=False)
        # 关键：把输入送到嵌入层所在的设备（分片模型下不要用 model.device）
        device = model.get_input_embeddings().weight.device
        inputs = {k: v.to(device) for k, v in inputs.items()}

        with torch.inference_mode():
            out = model.generate(
                **inputs,
                max_new_tokens=req.max_new_tokens,
                do_sample=req.do_sample,
                temperature=req.temperature if req.do_sample else None,
                top_p=req.top_p if req.do_sample else None,
                min_new_tokens=1,
                eos_token_id=tok.eos_token_id,
                pad_token_id=tok.pad_token_id,
            )
        full = tok.decode(out[0], skip_special_tokens=True)
        ans = full.split("### 输出：", 1)[-1].strip()
        tags = parse_xmlish_tags(ans)
        return {"text": ans, "tags": tags, "tokens": len(out[0])}

# 运行：单进程单 worker（避免多进程重复占显存）
# uvicorn server:app --host 0.0.0.0 --port 8000
