#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从四级行政区划表生成 SFT 样例（instruction / input / output）
示例输出（直辖市场景）：
{"instruction":"从以下地址文本中抽取要素，并按XML标签输出（只输出标签串）：",
 "input":"北京市北京市东城区东华门街道",
 "output":"<prov>北京市</prov><city>北京市</city><district>东城区</district><town>东华门街道</town>"}

用法：
  python lora/build_sft_from_adm.py \
    --xlsx lora/四级行政区划码表_20250901.xlsx \
    --out lora/sft_extend.jsonl
"""
import argparse, json
import pandas as pd

DEFAULT_INSTRUCTION = "从以下地址文本中抽取要素，并按XML标签输出（只输出标签串）："

def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", required=True, help="四级行政区划 Excel 文件路径")
    ap.add_argument("--sheet", default=None, help="工作表名（默认自动选择含有 p_name/c_name 等列的那个）")
    ap.add_argument("--out",   default="sft_extend.jsonl", help="输出 JSONL 路径")
    ap.add_argument("--instruction", default=DEFAULT_INSTRUCTION, help="instruction 文本")
    ap.add_argument("--limit", type=int, default=0, help="仅导出前 N 条（0=不限制）")
    ap.add_argument("--drop-dup", action="store_true", help="对生成的 input 去重（默认不过滤）")
    return ap.parse_args()

def norm(s):
    if pd.isna(s): return ""
    return str(s).strip().replace(" ", "").replace("　", "")

def pick_sheet(xlsx_path, prefer=None):
    xls = pd.ExcelFile(xlsx_path)
    if prefer and prefer in xls.sheet_names:
        return prefer
    # 自动选择包含目标列的 sheet
    need = {"p_name","c_name","d_name","street_name"}
    for sh in xls.sheet_names:
        cols = set(map(str, pd.read_excel(xlsx_path, sheet_name=sh, nrows=0).columns))
        if need.issubset(cols):
            return sh
    # 退而求其次：返回第一个
    return xls.sheet_names[0]

def build_sample_row(p, c, d, t, instruction):
    # 输入文本：按你要求，直接拼接（省 + 市 + 区/县 + 街道/乡镇），允许省市同名重复
    parts_in = [p, c, d, t]
    input_text = "".join([x for x in parts_in if x])

    # 输出标签：只输出存在的标签，顺序固定
    tags = []
    if p: tags.append(f"<prov>{p}</prov>")
    if c: tags.append(f"<city>{c}</city>")
    if d: tags.append(f"<district>{d}</district>")
    if t: tags.append(f"<town>{t}</town>")
    output_text = "".join(tags)

    return {
        "instruction": instruction,
        "input": input_text,
        "output": output_text
    }

def main():
    args = parse_args()

    sheet = pick_sheet(args.xlsx, args.sheet)
    df = pd.read_excel(args.xlsx, sheet_name=sheet)

    # 只取需要的四列，做基础清洗
    for col in ["p_name","c_name","d_name","street_name"]:
        if col not in df.columns:
            raise ValueError(f"工作表[{sheet}]缺少列：{col}")
    df = df[["p_name","c_name","d_name","street_name"]].copy()
    for col in df.columns:
        df[col] = df[col].map(norm)

    # 可选：限制条数
    if args.limit and args.limit > 0:
        df = df.head(args.limit)

    samples = []
    for _, row in df.iterrows():
        p = row["p_name"]; c = row["c_name"]; d = row["d_name"]; t = row["street_name"]
        # 若四级皆空则跳过
        if not (p or c or d or t):
            continue
        samples.append(build_sample_row(p, c, d, t, args.instruction))

    # 可选：对 input 去重（保留第一条）
    if args.drop_dup:
        seen = set()
        uniq = []
        for s in samples:
            if s["input"] in seen: 
                continue
            seen.add(s["input"])
            uniq.append(s)
        samples = uniq

    # 写出 JSONL（UTF-8, 不转义中文）
    n = 0
    with open(args.out, "w", encoding="utf-8") as f:
        for s in samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
            n += 1

    print(f"[DONE] 从工作表[{sheet}]读取 {len(df)} 行，生成 SFT 样例 {n} 条；输出文件：{args.out}")

if __name__ == "__main__":
    main()
