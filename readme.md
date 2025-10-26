# 地址解析引擎 (AddrResolver)

[![HF Model Card](https://img.shields.io/badge/%F0%9F%A4%97%20HuggingFace-Model%20Card-blue)](https://huggingface.co/scisaga/qwen3-8b-instruct-lora-address-struct-cn) [![License: CC BY 4.0](https://img.shields.io/badge/License-CC%20BY%204.0-lightgrey.svg)](https://creativecommons.org/licenses/by/4.0/)

![地址解析引擎业务逻辑架构](img/addr.svg)

结合高德地图API和通义千问大语言模型，能够将自然语言地址智能解析为结构化数据，并提供地图定位功能。

## 🌟 主要功能

- **智能地址解析**: 将自然语言地址解析为结构化字段（城市、区县、兴趣点、门牌号等）
- **多源数据融合**: 结合高德地图API和通义千问模型，提供高精度的地址匹配
- **Web界面**: 提供友好的Web界面进行地址解析和结果展示
- **RESTful API**: 支持API调用，便于集成到
- **地图定位**: 集成高德地图，可视化显示解析结果
- **私有化地址库**：支持私有化地址库功能，支持地图点选地址录入，支持多标签管理，召回时优选选取
- **Docker部署**: 支持Docker容器化部署

## 📁 文件一览

```
AddrResolver/
├── app.py                        # Flask Web 入口
├── resolver.py                   # 地址解析主流程
├── config.py                     # 环境变量与日志配置
├── requirements.txt              # Python 依赖
├── Dockerfile
├── docker-compose.yml
├── address.db                    # 示例地址库
├── .env                          # 环境变量示例
├── docs/
│   └── address_resolver.md
├── func/
│   ├── amap_call.py              # 高德 API 封装
│   ├── qwen_call.py              # 通义千问调用
│   └── struct_llm_call.py        # 结构化 LLM 调用
├── lora/
│   ├── bio2sft.py
│   ├── build_sft_from_adm.py
│   └── …                         # SFT 训练脚本与数据
├── prompts/
│   └── struct_prompt.md          # LLM 提示词
├── static/
│   └── swagger/                  # OpenAPI 文档
├── templates/
│   ├── index.html
│   └── address.html
├── test/
│   ├── test_address_db.py
│   ├── test_address_resolver.py
│   └── test_address_resolver_real.py
├── util/
│   ├── address_db.py
│   ├── geo.py
│   └── similarity.py
└── tcl/
    ├── address.db
    └── data_validation_1.ipynb
```

## 🔍 核心处理逻辑

```mermaid
flowchart TD
    %% ----------- 阶段1：优先召回 -----------
    subgraph Phase1[阶段1：优先召回]
        direction LR
        A[📥 输入自然语言地址]:::input --> LDB[📚 本地地址库召回]:::proc
        LDB -- 命中 --> OUT1[📤 返回结构化结果]:::output

        %% 召回失败 → 高德查询
        LDB -- 未命中 --> AMAP[🗺️ 调用高德接口查询]:::api
        AMAP --> TOP1[四级行政区划相同 + POI高度相似]:::proc
        TOP1 -- 是 --> OUT1[📤 返回结果]:::output
    end
    
    Phase1 -- 未命中 --> Phase2

    %% ----------- 阶段2：地址大模型结解析 -----------
    subgraph Phase2[阶段2：地址大模型结构化解析]
        B[Qwen3 LORA + HF TGI]:::llm -->|结构化字段| B1[行政区划]:::field
        B --> B2[道路 + 功能区]:::field
        B --> B3[POI]:::field
        B --> B4[建筑层级]:::field
        B --> B5[辅助信息]:::field
        B --> B6[杂项]:::field
    end

    Phase2 -.-> Phase3

    %% ----------- 阶段3：高德API精确搜索 -----------
    subgraph Phase3[阶段3：高德API精确搜索]
        direction LR
        D1[D+AP 组合搜索]:::proc
        D1 --> G1[高德输入提示API<br>/v3/assistant/inputtips]:::api
        G1 --> C1{结果≥3个?}:::cond
        C1 -- 是 --> RES[📤 返回候选POI]:::output
        C1 -- 否 --> D2[仅AP字段搜索]:::proc
        D2 --> G1
    end

    Phase3 -- 没有候选结果 --> Phase4
    
    Phase3 -.-> Phase5

    %% ----------- 阶段4：周边搜索 Fallback -----------
    subgraph Phase4[阶段4：周边搜索 Fallback]
        direction LR
        P1[锚点定位]:::proc
        P1 --> G2[高德地理编码API<br>/v3/geocode/geo]:::api
        P2[关键词提取 U+AP+I]:::proc
        G2 --> G3[高德周边搜索API<br>/v3/place/around]:::api
        P2 --> G3
        G3 -- 存在I字段 --> L1[通义千问匹配候选POI]:::llm
        G3 -- 无I字段 --> R2[候选POI结果]:::output
        L1 --> R2
    end
    
    Phase4 -.-> Phase5

    %% ----------- 阶段5：智能匹配算法 -----------
    subgraph Phase5[阶段5：智能匹配算法]
        SIM[重点语义单元相似度]:::algo --> CALC[最终得分]:::calc
        LOC[空间辅助得分]:::algo --> CALC
    end

    Phase5 -.-> Phase6

    %% ----------- 阶段6：结果优化 -----------
    subgraph Phase6[阶段6：结果优化]
        direction LR
        DEDUP[POI ID去重]:::proc --> REGEOCODE[高德逆地理编码API<br>/v3/geocode/regeo]:::api
        REGEOCODE --> PERF[性能监控&耗时记录]:::proc
        PERF --> OUT2[📤 输出最终结构化结果]:::output
    end

    %% ----------- 样式定义 -----------
    classDef input fill:#e3f2fd,stroke:#2196f3,stroke-width:2px,color:#222;
    classDef llm fill:#e8f5e9,stroke:#388e3c,stroke-width:2px,color:#222;
    classDef field fill:#fffde7,stroke:#fbc02d,stroke-width:1.5px,color:#555;
    classDef proc fill:#f1f8e9,stroke:#689f38,stroke-width:1.5px,color:#222;
    classDef api fill:#fff3e0,stroke:#ff9800,stroke-width:1.5px,color:#222;
    classDef cond fill:#ffe0b2,stroke:#fb8c00,stroke-width:1.5px,color:#a67404;
    classDef output fill:#ede7f6,stroke:#7e57c2,stroke-width:2px,color:#2d1457;
    classDef algo fill:#fce4ec,stroke:#e91e63,stroke-width:1.5px,color:#c2185b;
    classDef calc fill:#ede7f6,stroke:#8e24aa,stroke-width:2px,color:#222;

```

### 1. 地址结构化处理

#### 标签体系

本项目使用了[CCKS2021中文地址要素解析数据集](https://tianchi.aliyun.com/dataset/109339)的《中文地址要素解析标注规范》，具体如下：

- 行政区划层级
  * `prov`：省级行政区（省/自治区/直辖市）。
   * `city`：地级行政区（地级市/地区/自治州）。
   * `district`：县级行政区（市辖区/县级市/县）。
   * `town`：乡级行政区（镇/街道/乡）。
   * `community`：社区/行政村/自然村。
   * `village_group`：村内的“组/队/社”（数字编号）。
- 功能区与道路体系
   * `devzone`：各类开发区/产业园/度假区等功能区。
   * `road`：有正式名称的道路（路/街/巷/弄/隧道/高架等；步行街/商业街默认按 road）。
   * `roadno`：路号（道路门牌号）。
   * `intersection`：道路路口/出入口（与 `road` 必同时出现）。
- POI 层级
   * `poi`：兴趣点（小区/园区/大厦/商铺等）。
   * `subpoi`：子兴趣点/分区/期/门/苑等。
- 建筑层级（自上而下）
   * `houseno`：楼栋/幢/号楼；农村门牌也归此。
   * `cellno`：单元（含“甲乙丙丁/东西/一单元”等）。
   * `floorno`：楼层/层。
   * `roomno`：房号/户号/商铺号等。
   * `detail`：楼栋/单元/楼层/房间层级不明的整体串（如 `12-3-1001`）。
- 辅助定位信息
   * `assist`：普通辅助词（如“附近”等定性描述/提示词）。
   * `distance`：带数量单位的距离（米/千米/“几十米”等）。
   * `direction`：方位词（如“东/东北”等，文档在示例中使用）。
- 杂项
   * `redundant`：非地址要素/冗余内容（人名、电话、邮编、配送提示、连接词“与”等；标点也归此）。
   * `others`：规范未覆盖但确属地址元素的内容（如山/岛等；港澳台地址可整体记为 `others`）。


#### 模型微调

- **LoRA 训练**  
  参见 `lora/readme.md`，按照数据准备（`bio2sft.py` / `build_sft_from_adm.py`）→ 合并生成 `train.jsonl` → 运行 `train_hf_qlora.py` 的流程完成指令微调。默认脚本针对 Qwen3-8B，建议使用两张 24GB GPU（或更高配置），训练产物保存在 `outputs/qwen3_8b_addr_qlora/`，核心训练语料来自 [CCKS2021中文地址要素解析数据集](https://tianchi.aliyun.com/dataset/109339)。

- **模型下载**
   - [scisaga/qwen3-8b-instruct-lora-address-struct-cn](https://huggingface.co/scisaga/qwen3-8b-instruct-lora-address-struct-cn) 
   - [![HF Model Card](https://img.shields.io/badge/%F0%9F%A4%97%20HuggingFace-Model%20Card-blue)](https://huggingface.co/scisaga/qwen3-8b-instruct-lora-address-struct-cn>)

- **构建结构化推理容器**  
  `func/struct_llm_call.py` 对接 HuggingFace TGI 的 `/generate` 接口，可将合并后的模型挂载到官方镜像：
  ```bash
  docker run --gpus all --shm-size 1g -p 8080:80 \
    -v $(pwd)/outputs/qwen3_8b_addr_merged:/data \
    ghcr.io/huggingface/text-generation-inference:latest \
    --model-id /data \
    --dtype bfloat16 \
    --num-shard 2 \
    --max-input-tokens 2048 --max-total-tokens 2304
  ```
  服务启动后可通过 `curl http://127.0.0.1:8080/health` 或运行 `python lora/infer.py "上海市徐汇区佳安公寓宛平南路0001号楼"` 验证 XML 标签输出是否正常。

- **更新环境变量**  
  修改根目录 `.env`，保证键名与代码一致：
  ```env
  AMAP_KEY=高德Web服务密钥
  AMAP_WEB_KEY=高德JS SDK密钥
  LLM_API_KEY=阿里云百炼API密钥
  QWEN_MODEL=qwen3-8b
  STRUCT_LLM_URL=http://127.0.0.1:8080
  STRUCT_LLM_TOKEN=如需鉴权则填写Bearer Token，否则留空
  ```
  若旧环境中使用了 `STRUCT_LLM` 等变量名，请同步改为 `STRUCT_LLM_URL`，避免推理阶段读取失败。

### 2. 高德地图API集成

系统集成了以下4个高德地图API接口：

| API接口 | 接口地址 | 主要功能 | 使用场景 |
|---------|----------|----------|----------|
| **输入提示API** | `/v3/assistant/inputtips` | 模糊搜索POI，支持城市限定 | 精确搜索阶段，使用D+AP字段组合搜索 |
| **地理编码API** | `/v3/geocode/geo` | 将地址文本转换为经纬度坐标 | 周边搜索的锚点定位 |
| **逆地理编码API** | `/v3/geocode/regeo` | 将经纬度坐标转换为详细地址信息 | 补充POI的乡镇街道等详细信息 |
| **周边搜索API** | `/v3/place/around` | 以指定坐标为中心搜索周边POI | Fallback阶段，当精确搜索无结果时使用 |

### 3. 多阶段POI搜索策略

#### 阶段1：精确搜索
- 使用 `D + AP` 字段组合作为搜索关键词
- 调用**高德输入提示API**进行精确匹配
- 如果结果少于3个，则使用 `AP` 字段单独搜索

#### 阶段2：周边搜索（Fallback）
当精确搜索无结果时，系统启动周边搜索：
1. **锚点定位**: 使用**高德地理编码API**，优先使用 `AP` 字段，失败则使用 `D` 字段
2. **关键词提取**: 从 `U`、`AP`、`I` 字段中提取搜索关键词
3. **周边搜索**: 调用**高德周边搜索API**，以锚点为中心，使用提取的关键词搜索周边POI
4. **大模型辅助**: 当存在辅助信息（`I`字段）时，调用通义千问判断各候选POI的匹配程度

### 4. 智能匹配算法

#### 相似度计算
系统使用多维度相似度计算：
- **文本相似度** (70%权重): 基于分词和关键词重叠率
- **空间辅助得分** (30%权重): 基于大模型对辅助信息的理解

#### 最终评分公式
```
最终得分 = 0.7 × 文本相似度 + 0.3 × 空间辅助得分
```

### 5. 结果优化
- 自动去重：基于POI ID合并搜索结果
- 逆地理编码：使用**高德逆地理编码API**补充乡镇街道等详细信息
- 性能监控：记录处理耗时

## 📋 API返回字段说明

系统返回的JSON对象包含以下字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | POI的唯一标识符 |
| `name` | string | POI名称 |
| `address` | string | POI详细地址 |
| `location` | string | 经纬度坐标（经度,纬度） |
| `regeo` | object | 逆地理编码信息（乡镇街道等） |
| `similarity` | float | 文本相似度得分（0-100） |
| `auxiliary` | float | 空间辅助得分（0-100） |
| `score` | float | 最终匹配得分（0-100） |
| `duration` | float | 处理耗时（秒） |

## 🚀 快速开始

### 环境要求

- Python 3.10+
- Docker (可选，用于容器化部署)

### 1. 克隆项目

```bash
git clone <repository-url>
cd AddrResolver
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置API密钥

复制配置文件模板并填入您的API密钥：

```bash
cp config.ini.sample config.ini
```

编辑 `config.ini` 文件：

```ini
[key]
amap_key = 您的高德地图API密钥
llm_api_key = 您的阿里云百炼API密钥
qwen_model = qwen-turbo-2025-04-28
```

**获取API密钥：**
- [高德地图开放平台](https://lbs.amap.com/) - 获取高德API密钥
- [阿里云百炼](https://bailian.console.aliyun.com/) - 获取通义千问API密钥

### 4. 运行应用

```bash
python app.py
```

访问 http://localhost:5000 即可使用Web界面。

## 🐳 Docker部署

### 构建镜像

```bash
docker build -t scisaga/addr-resolver:latest .
```

### 推送镜像（可选）

```bash
docker push scisaga/addr-resolver:latest
```

### 使用Docker Compose部署

1. 设置环境变量（创建 `.env` 文件）：

```env
AMAP_KEY=高德地图API密钥
LLM_API_KEY=阿里云百炼API密钥
QWEN_MODEL=qwen-turbo-2025-04-28
```

2. 启动服务：

```bash
docker compose up -d --pull always
```

3. 访问应用：

打开浏览器访问 http://localhost:5000

## 📖 使用说明

### Web界面使用

1. 在输入框中输入需要解析的地址
2. 点击"解析"按钮
3. 系统将返回结构化的解析结果和地图定位

### API调用

#### 解析地址

```bash
GET /api/resolve?addr=地址文本
```

**示例：**

```bash
curl "http://localhost:5000/api/resolve?addr=浙江宁波市慈溪市长河镇长河镇云海村陆家路南3号"
```

**响应示例：**

```json
{
  "id": "B0FFJQXXXX",
  "name": "云海村南3号",
  "address": "浙江省宁波市慈溪市长河镇云海村陆家路南3号",
  "location": "121.594637,29.725989",
  "regeo": {
    "country": "中国",
    "province": "浙江省",
    "city": "宁波市",
    "district": "慈溪市",
    "township": "长河镇"
  },
  "similarity": 85.6,
  "auxiliary": 0.0,
  "score": 59.9,
  "duration": 2.34
}
```

## 🔧 配置说明

### 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `AMAP_KEY` | 高德地图API密钥 | 从config.ini读取 |
| `LLM_API_KEY` | 阿里云百炼API密钥 | 从config.ini读取 |
| `QWEN_MODEL` | 通义千问模型名称 | qwen-turbo-2025-04-28 |

### 日志配置

日志文件保存在 `logs/` 目录下：
- `address_resolver.log` - 地址解析相关日志

## 🧪 测试

项目包含测试文件：

```bash
# 运行单元测试
python test_address_resolver.py

# 运行真实场景测试
python test_address_resolver_real.py
```

## 🤝 贡献

欢迎提交Issue和Pull Request来改进这个项目。

## 📄 许可证

本项目采用MIT许可证。

## 🔗 相关链接

- [高德地图开放平台](https://lbs.amap.com/)
  - [Web服务 搜索POI](https://lbs.amap.com/api/webservice/guide/api-advanced/search)
  - [Web服务 输入提示](https://lbs.amap.com/api/webservice/guide/api-advanced/inputtips)
  - [快速接入高德地图 MCP Server](https://lbs.amap.com/api/mcp-server/gettingstarted)
- [阿里云百炼](https://bailian.console.aliyun.com/)
- [Flask框架](https://flask.palletsprojects.com/)
- [通义千问](https://qianwen.aliyun.com/)
