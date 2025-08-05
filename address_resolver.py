import requests
import json
import logging,time,os,sys
from dotenv import load_dotenv
from openai import OpenAI
from typing import Dict, List
from address_db import search_address
from similarity import score_main_tokens, core_keyword_overlap_ratio

# ------------------------
# 日志配置
# ------------------------

log_dir = "logs"
os.makedirs(log_dir, exist_ok=True)

logger = logging.getLogger("address")  # 命名 logger
logger.setLevel(logging.INFO)
logger.propagate = False  # 防止重复打印到 root logger

# 文件日志
file_handler = logging.FileHandler(f"{log_dir}/address_resolver.log", encoding="utf-8")
file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

# 控制台日志
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

# 添加 handler（注意：WebSocketHandler 在 app.py 中添加）
logger.addHandler(file_handler)
logger.addHandler(console_handler)

# ------------------------
# 配置加载与初始化
# ------------------------

# 加载 .env 文件
load_dotenv(".env")

# 获取配置值，优先使用环境变量，其次读取 .env
def get_config_value(env_key: str) -> str:
    value = os.getenv(env_key)
    if value is None:
        raise ValueError(f"缺少配置项：{env_key}")
    return value

# 配置项
AMAP_KEY = get_config_value("AMAP_KEY")
LLM_API_KEY = get_config_value("LLM_API_KEY")
QWEN_MODEL = get_config_value("QWEN_MODEL")

# ------------------------
# 工具函数
# ------------------------

# 读取提示词
def load_prompt(filename: str) -> str:
    with open(filename, "r", encoding="utf-8") as f:
        return f.read()

# Prompt 模板
STRUCT_PROMPT = load_prompt("struct_prompt.md")

# 初始化通义千问客户端（OpenAI 接口格式兼容）
client = OpenAI(
    api_key=LLM_API_KEY,
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
)

def call_qwen(prompt: str, model: str = QWEN_MODEL) -> str:
    """
    调用通义千问模型，获取结构化/标准化结果
    :param prompt: 输入的 prompt 内容
    :param model: 使用的模型名称
    :return: 模型返回的文本结果
    """
    try:
        start = time.time()
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是一个中文地理信息分析助手"},
                {"role": "user", "content": prompt}
            ],
            temperature=0,
            top_p=0.95,  # 避免极端值（推荐保留默认或略低）
            presence_penalty=0.1,  # 控制重复内容，适度增加稳定性
            frequency_penalty=0.1,  # 减少内容偏离
            extra_body={
                "enable_thinking": False
            }
        )
        end = time.time()
        duration = end - start
        logger.debug(f"模型响应耗时：{duration:.2f} 秒")

        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"通义千问调用失败：{e}")
        return ""

# ------------------------
# 高德输入提示 API 封装
# ------------------------

def amap_text_search(city: str, keyword: str, type: str = "") -> List[Dict]:
    """
    使用高德输入提示接口模糊搜索 POI
    :param city: 城市名称（地级市）
    :param keyword: 查询关键词
    :param type: 类型过滤（可选）
    :return: 包含位置数据的 POI 列表
    """
    """
    使用高德输入提示接口模糊搜索 POI, 并打印请求耗时
    """
    url = "https://restapi.amap.com/v3/assistant/inputtips"
    params = {
        "keywords": keyword,
        "city": city,
        "type": type,
        "key": AMAP_KEY,
        "datatype": "all",  # 返回全部类型（包括 POI、bus、地铁站等）
        "citylimit": True   # 限定在本城市返回结果
    }

    start = time.time()
    resp = requests.get(url, params=params, timeout=3).json()
    end = time.time()

    duration = end - start
    logger.debug(f"⏱️ 高德输入提示接口请求耗时：{duration:.2f} 秒")

    tips = resp.get("tips", [])

    logger.info(f"📋 返回 {len(tips)} 个候选 Tip：")
    for i, tip in enumerate(tips, start=1):
        name = tip.get("name", "")
        address = tip.get("address", "")
        location = tip.get("location", "")
        logger.info(f"{i:>2}. {name} | {address} | {location}")

    # 转为 POI 风格的结构，便于后续处理一致
    pois = [
        {
            "name": tip.get("name", ""),
            "address": tip.get("address", ""),
            "location": tip.get("location", ""),
            "id": tip.get("id", "")
        }
        for tip in tips if tip.get("location")  # 筛掉无位置信息的结果
    ]

    return pois


def amap_poi_search(city: str, keyword: str, type: str = "", threshold: float = 70.0) -> Dict | None:
    """
    使用高德 place/text 接口进行 POI 搜索，并融合相似度判断。
    若候选项中存在与 keyword 相似度高的记录（≥threshold），则返回该 POI，否则返回 None。

    :param city: 城市名称，可传 "" 表示全国
    :param keyword: 查询关键词（通常为原始地址）
    :param type: 类型过滤（如写字楼、住宅）
    :param threshold: 匹配相似度分数阈值（0-100）
    :return: 匹配的 POI（包含得分字段）或 None
    """
    url = "https://restapi.amap.com/v3/place/text"

    params = {
        "keywords": keyword,
        "city": city,
        "types": type,
        "key": AMAP_KEY,
        "offset": 20,
        "page": 1,
        "extensions": "all"
    }

    start = time.time()
    resp = requests.get(url, params=params, timeout=3).json()
    end = time.time()
    logger.debug(f"⏱️ 高德 POI 搜索接口耗时：{end - start:.2f} 秒")

    pois = resp.get("pois", [])
    if not pois:
        logger.info("📭 未返回 POI 结果")
        return None

    # 计算最高相似度
    best_poi = None
    best_score = 0.0

    for poi in pois:
        name = poi.get("name", "")
        address = poi.get("address", "")
        location = poi.get("location", "")
        if not location:
            continue

        name_score = similarity_score(keyword, name)
        address_score = similarity_score(keyword, address)
        score = max(name_score, address_score)

        if score > best_score:
            best_score = score
            best_poi = poi

    if best_poi and best_score >= threshold:
        logger.info(f"🎯 POI 匹配成功：{best_poi['name']} | {best_poi['address']} | 相似度: {best_score}")
        return best_poi
    else:
        logger.info(f"❌ 所有 POI 相似度均低于阈值 {threshold}，最高为 {best_score:.2f}")
        return None


def regeo(location: str, radius: int = 100) -> Dict:
    """
    使用高德逆地址编码获取乡镇街道信息
    :param location: 121.594637,29.725989
    :param radius: 检索半径
    :return: 乡镇街道信息
    """
    url = "https://restapi.amap.com/v3/geocode/regeo"
    params = {
        "key": AMAP_KEY,
        "location": location,
        "poitype": "",
        "radius": radius,
        "extensions": "all",
        "roadlevel": 0
    }

    response = requests.get(url, params=params)
    data = response.json()

    if data.get("status") != "1":
        print("请求失败，返回状态:", data.get("info"))
        return {}

    address_component = data.get("regeocode", {}).get("addressComponent", {})

    # 保留第一层字符串字段 + 特殊保留 streetNumber 字段
    result = {}
    for k, v in address_component.items():
        if isinstance(v, (str, int, float)):
            result[k] = v
        elif k == "streetNumber":
            result[k] = v  # 保留 streetNumber 的完整嵌套结构

    return result

def amap_geocode(city: str, address: str) -> str:
    """
    调用高德地理编码接口，将地址转为经纬度坐标
    :param city: 城市名
    :param address: 地址文本
    :return: 坐标字符串（经度,纬度）或空字符串
    """
    url = "https://restapi.amap.com/v3/geocode/geo"
    params = {"address": address, "city": city, "key": AMAP_KEY}
    resp = requests.get(url, params=params).json()
    if resp.get("geocodes"):
        return resp["geocodes"][0]["location"]
    return ""

def amap_around_search(location: str, keyword: str, radius: int = 5000) -> List[Dict]:
    """
    调用高德周边搜索接口
    :param location: 中心坐标
    :param keyword: 搜索关键词
    :param radius: 搜索半径（单位：米）
    :return: POI 列表
    """
    url = "https://restapi.amap.com/v3/place/around"
    params = {"location": location, "keywords": keyword, "radius": radius, "key": AMAP_KEY}
    resp = requests.get(url, params=params).json()
    return resp.get("pois", [])

def judge_best_by_auxiliary(anchor_location: str, candidates: List[Dict], auxiliary: str) -> List[Dict]:
    """
    使用大模型判断每个候选 POI 与辅助描述的匹配程度，为每个候选添加 auxiliary_score 字段（0~100）。
    :param anchor_location: 锚点坐标 (lng, lat)
    :param candidates: 候选 POI 列表，要求每个含有 location 字段
    :param auxiliary: 用户输入中的辅助字段，如“西北角”“往东走100米”“对面”等
    :return: 更新后的 candidates，每个包含 auxiliary_score 字段
    """
    poi_list = [{c["name"]: c["location"]} for c in candidates]
    prompt = f"""已知参考点坐标为 {anchor_location}，用户描述为“{auxiliary}”，
下列是候选 POI 的名称和经纬度，请你判断哪个最可能是用户所指的目标，并为每个候选项打一个匹配分数（0-100）。
输出格式如下（JSON）：
{{
  "名称1": 85,
  "名称2": 20,
  ...
}}
候选列表：
{json.dumps(poi_list, ensure_ascii=False, indent=2)}
请严格按照 JSON 格式返回：
"""

    response = call_qwen(prompt)

    try:
        score_map = json.loads(response)
        logger.info(f"🎯 大模型辅助打分结果：{score_map}")
    except Exception as e:
        logger.warning(f"⚠️ 大模型返回非标准 JSON，fallback 所有分数为 0。原始返回：{response}")
        score_map = {}

    for poi in candidates:
        name = poi.get("name", "")
        poi["auxiliary_score"] = round(score_map.get(name, 0.0), 2)

    return candidates

def search_nearby_by_fields(city: str, fields: Dict) -> List[Dict]:
    """
    根据结构化字段执行周边搜索（Fallback）
    优先使用 AP 字段作为定位锚点，结合 U/AP/I 字段提取关键词搜索周边，
    并结合 I 字段辅助位置信息调用大模型判断各个 POI 的匹配程度。
    :param city: 城市名
    :param fields: 包含结构字段的字典（AP, U, I等）
    :return: POI 列表，每个 POI 包含 auxiliary_score 字段（0~100）
    """
    anchor = fields.get("AP")
    logger.info(f"📍 周边搜索锚点（AP）: {anchor}")

    loc = amap_geocode(city, anchor)
    if not loc:
        logger.error("❌ AP锚点定位失败")

        anchor = fields.get("D")
        logger.info(f"📍 周边搜索锚点（D）: {anchor}")
        loc = amap_geocode(city, anchor)

        if not loc:
            logger.error("❌ D锚点定位失败")
            return []

    unit = fields.get("U", "")
    ap = fields.get("AP", "")
    auxiliary = fields.get("I", "")

    keywords = []

    # Step 0: 从 AP 中提取关键词（如 教学楼）
    if not keywords and ap:
        for token in ["教学楼", "写字楼", "广场", "大厦", "中心", "门诊", "公寓", "养殖塘", "机电厂"]:
            if token in ap:
                keywords.append(token)
                break

    # Step 1: 从 U 提取关键词（如 6号楼）
    if unit:
        for token in ["号楼", "栋", "单元", "宿舍", "楼", "门", "楼层", "部"]:
            if token in unit:
                keywords.append(unit)
                break


    # Step 3: 辅助字段触发模糊词
    if auxiliary:
        keywords.append("楼")

    # Step 4: fallback 默认关键词
    if not keywords:
        keywords.append("楼")

    logger.info(f"🔍 周边搜索关键词候选: {keywords}")

    # 多关键词尝试
    pois = []
    for kw in set(keywords):
        pois += amap_around_search(loc, kw)

    if not pois:
        return []

    # Step 5: 辅助字段辅助判断（调用大模型打分）
    if auxiliary:
        logger.info(f"🧭 使用辅助字段“{auxiliary}”调用大模型辅助打分")
        pois = judge_best_by_auxiliary(anchor_location=loc, candidates=pois, auxiliary=auxiliary)

        # 排序：按辅助评分降序排列
        pois.sort(key=lambda p: p.get("auxiliary_score", 0), reverse=True)

    return pois

# 相似度融合打分
def similarity_score(addr: str, candidate: str) -> float:
    """
    综合计算地址字符串之间的相似度
    :param addr: 输入地址
    :param candidate: 候选地址
    :return: 0~100 的相似度分数
    """
    t = 100 * score_main_tokens(addr, candidate)

    k = core_keyword_overlap_ratio(addr, candidate)

    final_score = 0.7 * t + 0.3 * k

    logger.info(f"相似度比较：{addr} --> {candidate}, token: {t:.2f}, keyword: {k:.2f}, " +
          f"相似度得分: {final_score:.2f}")

    return final_score

def normalize_poi_id(poi: Dict) -> str | None:
    """
    提取并规整 POI 的 id 字段为字符串形式，支持 str/int/list 类型。
    - 如果为 list，则返回第一个元素的字符串；
    - 如果为空或格式非法，则返回 None。
    """
    poi_id = poi.get("id")

    if isinstance(poi_id, list):
        if poi_id:
            return str(poi_id[0])
        else:
            logger.warning(f"⚠️ POI id 是空列表，跳过：{poi}")
            return None
    elif isinstance(poi_id, (str, int)):
        return str(poi_id)
    else:
        logger.warning(f"⚠️ POI id 类型非法（{type(poi_id)}），跳过：{poi}")
        return None

# 主流程封装
def resolve_address(raw_address: str) -> Dict:
    """
    地址智能解析主流程：结构化、搜索、匹配
    :param raw_address: 原始地址字符串
    :return: 匹配到的最佳 POI 信息（字典）
    """
    start_time = time.time()  # ✅ 启动计时
    logger.info(f"0. 输入地址：{raw_address}")

    # 先查私有地址库
    logger.info("1. 私有地址库匹配")
    private_matches = search_address(query=raw_address, page=1, page_size=3)
    if private_matches:
        best = private_matches[0]
        best["source"] = "custom"
        best["score"] = 100.0
        best["similarity"] = 100.0
        best["auxiliary"] = 0.0
        best["duration"] = round(time.time() - start_time, 2)
        logger.info(f"✅ 命中私有地址库：{best['name']} | {best['address']}")
        return best

    # 快速 POI 搜索匹配（使用高德 POI 搜索 + 相似度）
    logger.info("2. 快速搜索匹配（amap_poi_search）")
    best_fast = amap_poi_search("", raw_address, threshold=70.0)

    if best_fast:
        best_fast["regeo"] = regeo(best_fast["location"])
        best_fast["duration"] = round(time.time() - start_time, 2)
        return best_fast

    logger.info("3. 地址结构化")
    struct_prompt = STRUCT_PROMPT + raw_address
    structured = call_qwen(struct_prompt)
    structured_compact = json.dumps(json.loads(structured), ensure_ascii=False)
    logger.info(f"大模型返回结构化结果：{structured_compact}")

    fields = json.loads(structured)
    city = fields.get('C', '天津市')
    d = fields.get('D', '')
    ap = fields.get('AP', '')
    t = fields.get('T', '')
    i = fields.get('I', '')
    normalize_address = d + ap + i

    logger.info("4. POI搜索")
    search_keyword = f"{fields.get('D', '')}{fields.get('AP', '')}"
    logger.info(f"搜索关键词：{city} {search_keyword} {t}")

    # 第一次搜索：使用 D + AP
    pois = amap_text_search(city, search_keyword, t)

    # 如果结果少于 3 个，再用 AP 单独搜索一次
    if len(pois) < 3:
        logger.info(f"结果较少，再搜索：{fields.get('D', '')}")
        extra_pois = amap_text_search('', fields.get('D', ''), t)

        # 合并两个搜索结果，去重（可根据 poi 名称或 id）
        all_pois = {}
        for poi in pois + extra_pois:
            poi_id = normalize_poi_id(poi)
            if poi_id and poi_id not in all_pois:
                all_pois[poi_id] = poi

        pois = list(all_pois.values())
        logger.info(f"合并后 POI 数量：{len(pois)}")

    if not pois:
        logger.info("5. POI未命中，尝试周边搜索")
        pois = search_nearby_by_fields(city, fields)

    if not pois:
        logger.info("❌ 无结果")
        return {}

    def best_score(p: Dict, target: str) -> float:
        """
        计算最终匹配分数：融合文本相似度和辅助空间分数
        :param p: POI 字典
        :param target: 标准化地址字符串
        :return: 融合后的匹配得分（0~100）
        """
        name_score = similarity_score(target, p['name'])
        address_score = similarity_score(target, p['address'])
        text_score = max(name_score, address_score)

        # 辅助评分（空间判断得分）
        aux_score = p.get("auxiliary_score", 0)

        # 融合打分：70% 文本相似度 + 30% 空间得分（可根据需要调整权重）
        final_score = 0.7 * text_score + 0.3 * aux_score

        # 保存到 poi 中便于打印
        p['similarity'] = round(text_score, 2)
        p['auxiliary'] = round(aux_score, 2)
        p['score'] = round(final_score, 2)

        # logger.info(f"名称: {p.get('name', '')} | 地址: {p.get('address', '')} --> text: {text_score:.2f} | aux: {aux_score:.2f} | final: {final_score:.2f}")

        return final_score

    best = max(pois, key=lambda p: best_score(p, normalize_address))

    # 补充逆地理编码乡镇街道信息
    best["regeo"] = regeo(best["location"])

    duration = round(time.time() - start_time, 2)  # ✅ 计算耗时
    logger.info(f"✅ 匹配结果：{best['name']} | {best['address']} | 最终得分: {best['score']} | 文本: {best['similarity']} | 空间: {best['auxiliary']}")
    best["duration"] = duration

    return best

# 示例调用
if __name__ == "__main__":
    resolve_address("北京市海淀区六道口西北角的羊肉汤馆")
