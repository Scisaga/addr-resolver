# address_resolver.py
import requests
import json
import logging,time,os,sys
import re
from dotenv import load_dotenv
from openai import OpenAI
from typing import Dict, List
from util.address_db import search_address
from util.similarity import score_main_tokens, core_keyword_overlap_ratio
from config import logger, STRUCT_PROMPT
from func.amap_call import amap_inputtips, amap_geocode, amap_around_search, amap_poi_search, regeo
from func.qwen_call import call_qwen


def get_best_poi(pois: List[Dict], keyword: str, threshold: float = 70.0) -> Dict | None:
    """
    从 POI 列表中找到与 keyword 相似度最高的 POI，若相似度 ≥ threshold，则返回该 POI，否则返回 None。
    :param pois: POI 列表
    :param keyword: 查询关键词
    :param threshold: 相似度阈值
    :return: 最佳匹配的 POI 或 None
    """
    best_poi = None
    best_score = 0.0

    for poi in pois:
        name = poi.get("name", "")
        address = poi.get("address", "")
        location = poi.get("location", "")
        if not location:
            continue

        name_score = score_main_tokens(keyword, name)
        address_score = score_main_tokens(keyword, address)
        score = max(name_score, address_score)

        if score > best_score:
            best_score = score
            best_poi = poi

    if best_poi and best_score >= threshold:
        logger.info(f"🎯 匹配成功：{best_poi['name']} | {best_poi['address']} | 相似度: {best_score}")
        return best_poi
    else:
        logger.info(f"❌ 无匹配结果或相似度低于阈值 {threshold}，最高为 {best_score:.2f}")
        return None


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
    anchor = fields.get("D")
    logger.info(f"{city} 搜索锚点（D）: {anchor}")

    loc = amap_geocode(city, anchor)
    print(f"锚点位置：{loc}")
    if not loc:
        logger.error("❌ AP锚点定位失败")
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


def similarity_score(addr: str, candidate: str) -> float:
    """
    综合计算地址字符串之间的相似度
    :param addr: 输入地址
    :param candidate: 候选地址
    :return: 0~100 的相似度分数
    """
    t = 100 * score_main_tokens(addr, candidate)

    k = core_keyword_overlap_ratio(addr, candidate)

    final_score = 1 * t + 0.0 * k

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

def merge_pois(*poi_lists) -> List:
    """
    合并多个搜索结果，去重（可根据 poi 名称或 id）
    :param poi_lists: 任意数量的 POI 列表
    :return: 合并去重后的 POI 列表
    """
    all_pois = {}
    for pois in poi_lists:          # 遍历每个数组
        for poi in pois:            # 遍历数组里的每个元素
            poi_id = normalize_poi_id(poi)
            if poi_id and poi_id not in all_pois:
                all_pois[poi_id] = poi

    return list(all_pois.values())


# 正则模式：匹配地级市或省直管县（非贪婪）
pattern = re.compile(r'([\u4e00-\u9fa5]{2,20}?(市|地区|自治州|盟|县|自治县|旗|自治旗|林区|特区|区))')

def extract_first_region(text: str) -> str:
    match = pattern.search(text)
    if match:
        return match.group(1)
    return ""


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
        best["location"] = f"{best['lng']},{best['lat']}"  # 补充 location 字段
        best["source"] = "custom"
        best["score"] = 100.0
        best["similarity"] = 100.0
        best["auxiliary"] = 0.0
        best["duration"] = round(time.time() - start_time, 2)
        logger.info(f"✅ 命中私有地址库：{best['name']} | {best['address']}")
        return best

    # 快速 POI 搜索匹配（使用高德 POI 搜索 + 相似度）
    logger.info("2. 快速搜索匹配（amap_poi_search）")
    pois = amap_poi_search("", raw_address)
    best_fast = get_best_poi(pois, raw_address)

    if best_fast:
        best_fast["regeo"] = regeo(best_fast["location"])
        best_fast["duration"] = round(time.time() - start_time, 2)
        return best_fast

    # 地址结构化
    logger.info("3. 地址结构化")
    struct_prompt = STRUCT_PROMPT + raw_address
    structured = call_qwen(struct_prompt)
    structured_compact = json.dumps(json.loads(structured), ensure_ascii=False)
    logger.info(f"大模型返回结构化结果：{structured_compact}")

    fields = json.loads(structured)
    city = fields.get('C', '')
    d = fields.get('D', '')
    ap = fields.get('AP', '')
    t = fields.get('T', '')
    i = fields.get('I', '')
    normalize_address = d + ap + i

    logger.info("4. POI推荐")
    search_keyword = f"{d}{ap}"
    logger.info(f"搜索关键词：{city} {search_keyword} {t}")

    # 第一次搜索：使用 D + AP
    pois = amap_inputtips(city, search_keyword, t)

    # 如果结果少于 3 个，去掉城市搜
    if len(pois) < 3:
        logger.info(f"结果较少，去掉城市搜索：{search_keyword}")
        extra_pois = amap_inputtips('', search_keyword, '')
        pois = merge_pois(pois, extra_pois)
    
    
    city_1 = extract_first_region(d)
    if len(city_1) == 0:
        city_1 = city


    # 如果结果少于 3 个
    if len(pois) < 3:

        # 去掉修饰词
        search_keyword = re.sub(r'宿舍|\d+号?(楼|栋|座)|(东|西)城', '', search_keyword)
        search_keyword = re.sub(r'(?<=区).+?镇', '', search_keyword)
        search_keyword = re.sub(r'公租房', '', search_keyword)
        logger.info(f"去掉修饰词：{search_keyword}")
        extra_pois_1 = amap_inputtips('', search_keyword, '')

        # 可能是地级市直管县，尝试用修改城市名搜索
        extra_pois_2 = []
        if len(city_1) > 0 and city_1 != city:
            logger.info(f"可能是地级市直管县（{city_1}）：{ap}")
            extra_pois_2 = amap_inputtips(city_1, ap, '')

        extra_pois_3 = []
        search_keyword = re.sub(r'宿舍|\d+号?(楼|栋|座)', '', ap, count=0, flags=0)
        logger.info(f"疑似近音字误用，只搜搜索AP：{search_keyword}")
        extra_pois_3 = amap_inputtips(city, search_keyword, '')

        pois = merge_pois(pois, extra_pois_1, extra_pois_2, extra_pois_3)

    # 如果结果少于 3 个，再用 AP 单独搜索一次
    # if len(pois) < 4:
    #     logger.info(f"结果较少，去掉城市只搜原始AP：{ap}")
    #     extra_pois = amap_inputtips('', ap, '')
    #     pois = merge_pois(pois, extra_pois)

    logger.info(f"兜底行政区搜索：{city_1}")
    extra_pois = amap_inputtips('', city_1, '')
    extra_pois = extra_pois[:1] if extra_pois else []
    pois = merge_pois(pois, extra_pois)

    # 无匹配 兜底策略 + 激进策略
    if not pois:
        logger.info("5. POI未命中，尝试周边搜索")
        pois = search_nearby_by_fields(city, fields)

    if not pois:
        logger.error("❌ POI 搜索无结果，返回空")
        return {}

    def best_score(p: Dict, target: str, fields: Dict) -> float:
        """
        计算最终匹配分数：融合文本相似度和辅助空间分数
        :param p: POI 字典
        :param target: 标准化地址字符串
        :return: 融合后的匹配得分（0~100）
        """

        name_score = similarity_score(target, p['name'])
        address_score = similarity_score(target, p['address'])
        text_score = max(name_score, address_score)

        print(f"初始文本相似度得分: {text_score}")

        c = fields.get('C', '')

        if len(c) > 0 and c not in p["address"]:
            text_score = text_score * 0.8
        if len(city_1) > 0 and city_1 not in p["address"]:
            text_score = text_score * 0.8
        if len(c) > 0 and c not in p["address"] and len(city_1) > 0 and city_1 not in p["address"]:
            text_score = 0.0

        print(f"调整后文本相似度得分: {text_score}")

        # 辅助评分（空间判断得分）
        aux_score = p.get("auxiliary_score", 0)

        # 融合打分：70% 文本相似度 + 30% 空间得分（可根据需要调整权重）
        final_score = 0.7 * text_score + 0.3 * aux_score

        #print(f"融合后最终得分: {final_score}")

        # 保存到 poi 中便于打印
        p['similarity'] = round(text_score, 2)
        p['auxiliary'] = round(aux_score, 2)
        p['score'] = round(final_score, 2)

        # logger.info(f"名称: {p.get('name', '')} | 地址: {p.get('address', '')} --> text: {text_score:.2f} | aux: {aux_score:.2f} | final: {final_score:.2f}")

        return final_score

    best = max(pois, key=lambda p: best_score(p, normalize_address, fields))

    if len(best["location"].split(",")) != 2:
        logger.error(f"❌ POI 位置信息异常：{best['location']}")
        return {}
    
    if best["score"] == 0:
        logger.error(f"❌ POI 不匹配：{best['score']}")
        return {}

    # 补充 经纬度字段
    best["lat"] = float(best["location"].split(",")[1])
    best["lng"] = float(best["location"].split(",")[0])

    # 补充逆地理编码乡镇街道信息
    best["regeo"] = regeo(best["location"])
    best["ap"] = ap

    duration = round(time.time() - start_time, 2)  # ✅ 计算耗时
    logger.info(f"✅ 匹配结果：{best['name']} | {best['address']} | 最终得分: {best['score']} | 文本: {best['similarity']} | 空间: {best['auxiliary']}")
    best["duration"] = duration

    return best

# 示例调用
if __name__ == "__main__":
    resolve_address("北京市海淀区六道口西北角的羊肉汤馆")
