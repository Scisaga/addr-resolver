import sqlite3
import time
import math
import re
from typing import List, Dict
import os

# ✅ SQLite 数据库文件路径（默认）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, ".."))
DB_PATH = os.path.join(PROJECT_ROOT, "address.db")

print(f"使用数据库路径：{DB_PATH}")

# ✅ 建立数据库连接
def connect():
    return sqlite3.connect(DB_PATH)

# ✅ 插入或更新地址记录
def insert_address(data: Dict):
    """
    插入一条地址记录。若 name 或 address 冲突则更新原记录。
    自动校验字段，设置 updated_at。
    """
    required = ["id", "name", "address", "lat", "lng"]
    for k in required:
        if not data.get(k):
            raise ValueError(f"字段 `{k}` 不能为空")

    with connect() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO custom_address (
                id, name, address, lat, lng,
                province, district, township,
                tag, comment, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                id=excluded.id,
                address=excluded.address,
                lat=excluded.lat,
                lng=excluded.lng,
                province=excluded.province,
                district=excluded.district,
                township=excluded.township,
                tag=excluded.tag,
                comment=excluded.comment,
                updated_at=excluded.updated_at
        """, (
            data["id"], data["name"], data["address"], data["lat"], data["lng"],
            data.get("province"), data.get("district"), data.get("township"),
            data.get("tag"), data.get("comment"), int(time.time())
        ))
        conn.commit()

# ✅ 局部更新地址字段（自动更新时间）
def update_address(id: str, fields: Dict):
    """
    更新指定 ID 的地址记录字段，自动更新 updated_at。
    """
    if not fields:
        return

    if any(k in ["name", "address", "lat", "lng"] and not fields.get(k) for k in fields):
        raise ValueError("不能将必要字段更新为空值")

    keys = ", ".join([f"{k}=?" for k in fields])
    values = list(fields.values())
    values.append(int(time.time()))
    values.append(id)

    with connect() as conn:
        cursor = conn.cursor()
        cursor.execute(f"""
            UPDATE custom_address SET {keys}, updated_at=? WHERE id=?
        """, values)
        conn.commit()

# ✅ 删除地址记录
def delete_address(id: str):
    """
    删除指定 ID 的地址记录。
    """
    with connect() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM custom_address WHERE id=?", (id,))
        conn.commit()

# ✅ 基于 name/address 执行 FTS5 模糊搜索（支持分页）
def search_address(
    query: str = "",
    start_ts: int = None,
    end_ts: int = None,
    page: int = 1,
    page_size: int = 10
) -> List[Dict]:
    """
    地址搜索（支持 FTS5 模糊查询 或 按更新时间区间过滤）分页返回结果。
    - 若 query 非空，则使用 FTS5 name/address 搜索；
    - 否则使用 updated_at 范围查询（start_ts 和 end_ts 必须传）；
    """
    offset = (page - 1) * page_size
    query = query.strip()
    query = re.sub(r"[^\u4e00-\u9fa5\w\s]", " ", query)

    with connect() as conn:
        cursor = conn.cursor()

        if query:
            fts_query = f'name:{query} OR address:{query}'
            cursor.execute("""
                SELECT a.* FROM custom_address_fts
                JOIN custom_address a ON custom_address_fts.rowid = a.rowid
                WHERE custom_address_fts MATCH ?
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
            """, (fts_query, page_size, offset))
        else:
            if start_ts is None or end_ts is None:
                raise ValueError("当 query 为空时，必须提供 start_ts 和 end_ts")
            cursor.execute("""
                SELECT * FROM custom_address
                WHERE updated_at BETWEEN ? AND ?
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
            """, (start_ts, end_ts, page_size, offset))

        cols = [desc[0] for desc in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]


# ✅ 经纬度逆地理匹配（基于球面距离计算 + 分页）
def find_nearby_addresses(lat: float, lng: float, radius: float = 200.0, page: int = 1, page_size: int = 10) -> List[Dict]:
    """
    查找在指定经纬度范围内（米级半径）的所有地址记录，并按距离升序分页返回。
    """
    def haversine(lat1, lng1, lat2, lng2):
        # Haversine 公式计算两点间球面距离
        R = 6371000
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = phi2 - phi1
        dlambda = math.radians(lng2 - lng1)
        a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2)**2
        return R * 2 * math.asin(math.sqrt(a))

    with connect() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM custom_address")
        cols = [desc[0] for desc in cursor.description]
        result = []
        for row in cursor.fetchall():
            record = dict(zip(cols, row))
            d = haversine(lat, lng, record["lat"], record["lng"])
            if d <= radius:
                record["distance"] = round(d, 2)
                result.append(record)

        # 按距离升序排序并分页
        result.sort(key=lambda x: x["distance"])
        offset = (page - 1) * page_size
        return result[offset:offset + page_size]

