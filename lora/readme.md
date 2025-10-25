## LoRA 训练与推理指南

本目录包含地址解析模型的指令微调（SFT）流程，覆盖数据准备 → QLoRA 训练 → 适配器合并 → 推理部署。推荐在 Linux + CUDA 环境执行，GPU 至少 24GB 显存（两卡 A100 可直接按示例命令运行）。

### 1. 环境准备
```bash
pip install -U "trl>=0.8.6" "transformers>=4.41" "peft>=0.10.0" \
  "accelerate" "datasets" "bitsandbytes>=0.43.3" "pandas" "fastapi" "uvicorn"
python -c "import torch,trl,transformers,peft;print(torch.cuda.is_available(), trl.__version__)"
```
如需 4-bit QLoRA 训练，请确认 GPU 驱动与 CUDA 版本兼容 bitsandbytes；若未安装 4-bit 支持，可将 `train_hf_qlora.py` 中的量化配置改为全精度。

### 2. 数据构建
| 文件 | 说明 |
|------|------|
| `events.jsonl` | 原始事件/日志样本，可按需清洗生成训练数据 |
| `sft.jsonl` | 通过 `bio2sft.py` 从 BIO/BIES 标注语料转换的 Instruction Tuning 样本 |
| `sft_extend.jsonl` | 通过 `build_sft_from_adm.py` 基于四级行政区划补充的样本 |
| `四级行政区划*.*` | 行政区划码表，用于扩充样本 |

#### 2.1 BIO/BIES 标注转 SFT
```bash
python lora/bio2sft.py \
  -i data/bio_dev.txt \
  -o lora/sft.jsonl \
  --seed 42
```
- 输入：每行“字符 + BIO/BIES 标签”，空行分句；零串（如“0000”）会在 input/output 同步替换，防止模型记忆固定编号。
- 输出：包含 `instruction` / `input` / `output` 三列的 JSONL。标签顺序优先 `prov/city/district/town/community/poi/road/roadno`。

#### 2.2 行政区划补充样本
```bash
python lora/build_sft_from_adm.py \
  --xlsx lora/四级行政区划码表_20250901.xlsx \
  --out lora/sft_extend.jsonl \
  --drop-dup
```
该脚本读取 Excel（默认自动识别包含 `p_name` 等列的工作表），生成“省市区街”标签样本，可通过 `--limit` 控制条数。

#### 2.3 数据合并示例
```bash
cat lora/sft.jsonl lora/sft_extend.jsonl > lora/train.jsonl
```
如需按比例混合，可自行编写脚本或使用 `jq` 处理。`train_hf_qlora.py` 会按 `instruction/input/output` 字段加载数据。

### 3. QLoRA 指令微调
训练脚本：`train_hf_qlora.py`（默认基座 `Qwen/Qwen3-8B`，4-bit 量化 + LoRA）。核心参数：
```bash
CUDA_VISIBLE_DEVICES=0,1 torchrun --nproc_per_node=2 lora/train_hf_qlora.py \
  --model Qwen/Qwen3-8B \
  --data lora/train.jsonl \
  --out outputs/qwen3_8b_addr_qlora \
  --epochs 3 \
  --bsz 4 \
  --grad_accum 32 \
  --lr 2e-4 \
  --bf16
```
- `--val_ratio`：拆分验证集比例（默认 0.1）。
- `--max_len`：训练时的截断长度，建议 512~1024（视 GPU 显存调整）。
- `--lora_r/alpha/dropout`：LoRA 超参，可按需求修改。
- 日志输出默认写入 TensorBoard，可 `tensorboard --logdir outputs/...` 查看。

训练完成后，适配器保存在 `outputs/qwen3_8b_addr_qlora/`，并包含 tokenizer 配置，以便后续离线加载。

### 4. 合并适配器（可选）
若需部署整模型（无需 PEFT 加载）：
```bash
python lora/merge.py \
  --adapter outputs/qwen3_8b_addr_qlora/checkpoint-100 \
  --out outputs/qwen3_8b_addr_merged
```
脚本默认从指定 checkpoint 读取 LoRA，并写出整合后的权重与 tokenizer。合并过程在 CPU 上执行，需约 16GB 内存。

### 5. 推理与服务

#### 5.1 直接加载 LoRA 适配器
```bash
python lora/infer.py "上海市徐汇区佳安公寓宛平南路0001号楼"
```
`infer.py` 使用 4-bit 权重 + LoRA 适配器，通过 `AutoPeftModelForCausalLM` 自动挂载。可参考脚本中的 `infer()` 方法在项目中调用。

#### 5.2 部署 FastAPI 服务
```bash
uvicorn lora.infer_serv:app --host 0.0.0.0 --port 8000
```
服务默认加载合并后的整模型（`MERGED_DIR`），提供 `/infer` 接口，返回原始 XML 字符串及解析后的标签字典。`CONCURRENCY` 控制同时生成的请求数，可按显存调整。

### 6. 目录速览
| 文件 | 功能 |
|------|------|
| `bio2sft.py` | 将 BIO/BIES 地址标注转为 SFT JSONL |
| `build_sft_from_adm.py` | 根据行政区划码表生成 SFT 样本 |
| `events.jsonl` | 原始事件语料（示例） |
| `sft.jsonl` / `sft_extend.jsonl` | 已转换好的训练数据 |
| `train_hf_qlora.py` | QLoRA 指令微调脚本 |
| `merge.py` | 将 LoRA 适配器合并回整模型 |
| `infer.py` | 本地加载 LoRA 适配器推理示例 |
| `infer_serv.py` | FastAPI 推理服务 |
| `merged PDFs / Excel` | 数据来源及标注规范参考 |

按上面步骤即可重现实验流程，并灵活替换自身数据或基座模型。若需要在多机集群训练，可基于 `torchrun` 命令调整 `--nproc_per_node` / `--nnodes` 等参数。欢迎在此基础上扩展自动化数据清洗、评测脚本等能力。*** End Patch***
