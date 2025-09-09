# amap_call.py
import os
import time
import requests
from typing import Dict, List, Optional, Union

from config import logger, AMAP_KEY

def safe_str(val):
    """保证返回字符串；如果是数组就取第一个，否则返回空或原值"""
    if isinstance(val, (list, tuple)):
        return val[0] if len(val) > 0 else ""
    return val or ""

def amap_inputtips(city: str, keyword: str, type: str = "") -> List[Dict]:
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

    logger.info(f"    返回 {len(tips)} 个候选 Tip：")

    for i, tip in enumerate(tips, start=1):
        
        #print(tip)
        
        name = tip.get("name", "")

        address = safe_str(tip.get("address", ""))
        district = safe_str(tip.get("district", ""))

        address = district + address

        location = safe_str(tip.get("location", ""))
        logger.info(f"    {i:>2}. {name} | {address} | {location}")

    # 转为 POI 风格的结构，便于后续处理一致
    pois = [
        {
            "name": tip.get("name", ""),
            "address": safe_str(tip.get("district", "")) + safe_str(tip.get("address", "")),
            "location": safe_str(tip.get("location", "")),
            "id": tip.get("id", "")
        }
        for tip in tips if tip.get("location")  # 筛掉无位置信息的结果
    ]

    return pois


def amap_poi_search(city: str, keyword: str, type: str = "") -> Dict:
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

    return resp.get("pois", [])


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
    print(f"高德地理编码响应：{resp}")
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