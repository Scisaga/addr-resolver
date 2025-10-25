#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从 BIO/BIES 地址标注文本 一步到位 生成 SFT JSONL（instruction / input / output）
------------------------------------------------------------------------------------
输入：逐行“字符 与 BIO/BIES 标签”，空行分句。例如：
    江 B-prov
    苏 I-prov
    省 E-prov
    杭 B-city
    州 E-city

    西 B-road
    湖 I-road
    路 E-road
    0 O
    0 O
    0 O
    号 O

用法：
    python lora/bio2sft.py -i tianchi/dev.txt -o lora/sft.jsonl --seed 42
可选参数：
    --instruction  自定义SFT指令文本（默认已给出）
    --seed         随机种子（保证“0 串替换”可复现）
    --no-strip     不去除input/output首尾空白（默认strip）
说明：
    1) 实体类型输出顺序：["prov","city","district","town","community","poi","road","roadno"]；
       未知类型按首次出现顺序追加在末尾。
    2) 同一类型多段默认直接拼接（与原脚本保持一致）。
    3) “0 串替换”仅替换不与其他数字相连的连续 0（正则：(?<!\\d)0+(?!\\d)），
       且同一条样本内 input 与 output 对应长度一致替换。
"""

import argparse
import json
import re
import sys
import random
from collections import OrderedDict
from typing import List, Tuple, Dict, Optional

# === 可配置的默认为空 ===
ENTITY_ORDER = ["prov", "city", "district", "town", "community", "poi", "road", "roadno"]

ZERO_RUN_RE = re.compile(r'(?<!\d)0+(?!\d)')  # 仅匹配不与其他数字相连的 0 串
TAG_RE = re.compile(r"^([BIES])\-(.+)$")      # 兼容 B/I/E/S-<type>

# -------------------- 读取与解析 --------------------
def parse_sentences(path: str) -> List[List[Tuple[str, str]]]:
    """读取文件，按空行分句，返回 [ [(char, tag), ...], ... ]"""
    sentences: List[List[Tuple[str, str]]] = []
    cur: List[Tuple[str, str]] = []
    with open(path, "r", encoding="utf-8") as f:
        for raw in f.read().splitlines():
            line = raw.strip()
            if not line:
                if cur:
                    sentences.append(cur)
                    cur = []
                continue
            parts = line.split()
            if len(parts) < 2:
                # 异常行直接跳过
                continue
            ch, tag = parts[0], parts[1]
            cur.append((ch, tag))
    if cur:
        sentences.append(cur)
    return sentences

# -------------------- BIO/BIES → 实体块 --------------------
def bio_to_entities(tokens: List[Tuple[str, str]]) -> Tuple[Dict[str, str], List[str]]:
    """
    将一条句子的 (char, BIO/BIES-tag) 序列解析为 {type: text}，并返回类型出现顺序。
    - 支持 B/I/E-<type> 与 S-<type>；遇到 O 或类型切换时 flush
    - 同一类型若出现多段，默认直接拼接
    """
    entities_list: Dict[str, List[str]] = {}
    appear_order: List[str] = []

    cur_type: Optional[str] = None
    buf: List[str] = []

    def flush():
        nonlocal cur_type, buf
        if cur_type and buf:
            seg = "".join(buf)
            if seg:
                if cur_type not in entities_list:
                    entities_list[cur_type] = []
                    appear_order.append(cur_type)
                entities_list[cur_type].append(seg)
        cur_type, buf = None, []

    for ch, tag in tokens:
        if tag == "O":
            flush()
            continue
        m = TAG_RE.match(tag)
        if not m:
            # 非法/未知标注，直接视作分隔
            flush()
            continue
        bio, t = m.group(1), m.group(2)

        if bio == "B":
            flush()
            cur_type = t
            buf = [ch]
        elif bio == "I":
            if cur_type == t and buf:
                buf.append(ch)
            else:
                # 容错：孤立 I，当作 B 重启
                flush()
                cur_type = t
                buf = [ch]
        elif bio == "E":
            if cur_type == t and buf:
                buf.append(ch)
                flush()
            else:
                # 容错：孤立 E，当作单字实体
                flush()
                cur_type = t
                buf = [ch]
                flush()
        elif bio == "S":
            flush()
            cur_type = t
            buf = [ch]
            flush()

    flush()

    # 将多段合并（默认直接拼接）
    entities = OrderedDict()
    for t in appear_order:
        entities[t] = "".join(entities_list.get(t, []))

    return entities, appear_order

# -------------------- 构建全地址 & 标签串 --------------------
def build_addr_and_tags(entities: Dict[str, str], appear_order: List[str]) -> Tuple[str, str, List[str]]:
    """
    返回：
      full_addr:  "按顺序拼接后的全地址"
      tag_str:    "<t>...</t><t2>...</t2>..."
      ordered:    实际输出次序（known 后接 unknown）
    """
    known = [t for t in ENTITY_ORDER if t in entities]
    unknown = [t for t in appear_order if t not in ENTITY_ORDER]
    ordered_types = known + unknown

    full_addr = "".join(entities[t] for t in ordered_types if entities[t])
    tag_str = "".join(f"<{t}>{entities[t]}</{t}>" for t in ordered_types if entities[t])
    return full_addr, tag_str, ordered_types

# -------------------- “0 串一致替换” --------------------
def _rand_ndigits(n: int, rng: random.Random) -> str:
    """生成 n 位随机数字串，首位不为 0。"""
    if n <= 0:
        return ""
    first = rng.choice("123456789")
    if n == 1:
        return first
    rest = "".join(rng.choice("0123456789") for _ in range(n - 1))
    return first + rest

def _build_zero_plan(text_a: str, text_b: str, rng: random.Random) -> Dict[int, str]:
    """
    扫描两段文本，找出所有“0 串长度”，为每一种长度分配样本内一致的随机替换值。
    """
    lengths = set()
    for t in (text_a, text_b):
        if not t:
            continue
        for m in ZERO_RUN_RE.finditer(t):
            lengths.add(len(m.group(0)))
    return {n: _rand_ndigits(n, rng) for n in lengths}

def _replace_zero_runs(text: str, plan: Dict[int, str]) -> str:
    """按 plan 将 text 中的 0 串替换为同长度随机数；同长度共享同一替换值。"""
    if not text or not plan:
        return text
    def _repl(m: re.Match) -> str:
        n = len(m.group(0))
        return plan.get(n, m.group(0))
    return ZERO_RUN_RE.sub(_repl, text)

# -------------------- 主流程：BIO/BIES → SFT --------------------
def convert_bio_to_sft(in_path: str,
                       out_path: str,
                       sft_instruction: str,
                       keep_ws: bool,
                       seed: Optional[int]) -> None:
    rng = random.Random(seed) if seed is not None else random.Random()

    sents = parse_sentences(in_path)
    total, ok = 0, 0

    with open(out_path, "w", encoding="utf-8") as fout:
        for sent in sents:
            total += 1
            entities, appear_order = bio_to_entities(sent)
            if not entities:
                # 跳过无实体样本
                continue

            full_addr, tag_str, _ordered = build_addr_and_tags(entities, appear_order)

            inp = full_addr if keep_ws else full_addr.strip()
            out = tag_str if keep_ws else tag_str.strip()
            if not inp or not out:
                # 缺必要字段则跳过
                continue

            # 为该样本生成 0 串替换计划（保证 input/output 一致）
            plan = _build_zero_plan(inp, out, rng)
            inp2 = _replace_zero_runs(inp, plan)
            out2 = _replace_zero_runs(out, plan)

            sample = {
                "instruction": sft_instruction,
                "input": inp2,
                "output": out2,
            }
            fout.write(json.dumps(sample, ensure_ascii=False) + "\n")
            ok += 1

    print(f"[DONE] 读取 {total} 句，成功转换 {ok} 句；输出文件：{out_path}", file=sys.stderr)

# -------------------- CLI --------------------
def parse_args():
    ap = argparse.ArgumentParser(description="从 BIO/BIES 地址标注文本一步到位转换为 SFT JSONL")
    ap.add_argument("-i", "--input", required=True, help="输入 BIO/BIES 标注文本路径（空行分句）")
    ap.add_argument("-o", "--output", required=True, help="输出 SFT JSONL 文件路径")
    ap.add_argument("--instruction",
                    default="从以下地址文本中抽取要素，并按XML标签输出（只输出标签串）：",
                    help="SFT 的 instruction 文本")
    ap.add_argument("--no-strip", action="store_true",
                    help="不去除 input/output 首尾空白（默认会 strip）")
    ap.add_argument("--seed", type=int, default=None,
                    help="随机种子（设置后使“0 串替换”可复现）")
    return ap.parse_args()

def main():
    args = parse_args()
    convert_bio_to_sft(
        in_path=args.input,
        out_path=args.output,
        sft_instruction=args.instruction,
        keep_ws=args.no_strip,
        seed=args.seed
    )

if __name__ == "__main__":
    main()
