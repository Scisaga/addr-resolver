import configparser
import json
import os
from datetime import date, timedelta
from flask import Flask, request, render_template, jsonify, send_from_directory

from resolver import resolve_address  # 地址智能解析主流程
from util.address_db import (
    insert_address, update_address, delete_address,
    search_address, find_nearby_addresses
)

# ✅ 读取配置
config = configparser.ConfigParser()
config.read("config.ini", encoding="utf-8")

def get_config_value(env_key: str, config_section: str, config_key: str) -> str:
    return os.environ.get(env_key) or config.get(config_section, config_key)

AMAP_KEY = get_config_value("AMAP_KEY", "key", "amap_key")
AMAP_WEB_KEY = get_config_value("AMAP_WEB_KEY", "key", "amap_web_key")

# ✅ 创建 Flask 实例
app = Flask(__name__)

def _safe_resolve_address(raw_address, max_retries=10):
    """
    调用 resolve_address，遇到 JSONDecodeError 就重试。
    :param raw_address: 输入原始地址
    :param max_retries: 最大重试次数
    :param wait_sec: 每次重试间隔
    """
    for i in range(max_retries):
        try:
            return resolve_address(raw_address)
        except json.JSONDecodeError as e:
            print(f"解析失败，重试 {i+1}/{max_retries}：{e}")
        except Exception as e:
            # 其他错误不重试，直接抛出
            print(f"调用 resolve_address 出错：{e}")
            raise
    raise RuntimeError(f"resolve_address 重试 {max_retries} 次后仍然失败: {raw_address}")


# ✅ 首页：地址输入与地图展示
@app.route("/", methods=["GET", "POST"])
def index():
    addr = ""
    result = None
    structured_json = ""
    submitted = False

    if request.method == "POST":
        submitted = True
        addr = request.form.get("address", "")
        if addr:
            result = resolve_address(addr)
            structured_json = json.dumps(result, ensure_ascii=False, indent=2) if result else ""

    return render_template("index.html", addr=addr, result=result,
                           structured_json=structured_json, submitted=submitted,
                           amap_key=AMAP_WEB_KEY)

# ✅ 私有化地址库管理
@app.route("/address")
def address_page():
    today = date.today()
    context = {
        "amap_key": AMAP_KEY,
        "today": (today + timedelta(days=1)).isoformat(),
        "today_minus_7": (today - timedelta(days=7)).isoformat()
    }
    return render_template("address.html", **context)

# ✅ 地址解析 API 接口
@app.route("/api/resolve")
def api_resolve():
    addr = request.args.get("addr", "")
    if not addr:
        return jsonify({"error": "缺少参数 addr"}), 400
    result = _safe_resolve_address(addr)
    return jsonify(result or {})

# ✅ 插入地址（POST JSON）
@app.route("/api/custom_address", methods=["POST"])
def api_insert_address():
    data = request.json
    if not data or "id" not in data:
        return jsonify({"error": "缺少字段 id"}), 400
    insert_address(data)
    return jsonify({"message": "地址已插入/更新"})

# ✅ 更新地址（部分字段）
@app.route("/api/custom_address/<string:id>", methods=["PUT"])
def api_update_address(id):
    fields = request.json
    update_address(id, fields)
    return jsonify({"message": "地址已更新"})

# ✅ 删除地址
@app.route("/api/custom_address/<string:id>", methods=["DELETE"])
def api_delete_address(id):
    delete_address(id)
    return jsonify({"message": "地址已删除"})

# ✅ 地址模糊搜索（分页）
@app.route("/api/custom_address/search")
def api_search_address():
    query = request.args.get("q", "").strip()
    page = int(request.args.get("page", 1))
    page_size = int(request.args.get("page_size", 10))

    if query:
        # 模糊搜索
        results = search_address(query=query, page=page, page_size=page_size)
    else:
        # 按时间范围筛选（必须提供 start 和 end）
        try:
            start_ts = int(request.args.get("start"))
            end_ts = int(request.args.get("end"))
        except (TypeError, ValueError):
            return jsonify({"error": "缺少参数 start/end 或格式错误"}), 400
        results = search_address(start_ts=start_ts, end_ts=end_ts, page=page, page_size=page_size)

    return jsonify(results)


# ✅ 位置逆查找
@app.route("/api/custom_address/nearby")
def api_nearby():
    location = request.args.get("location", "")
    try:
        lng, lat = map(float, location.split(","))
    except:
        return jsonify({"error": "参数格式错误，应为 location=lng,lat"}), 400
    radius = float(request.args.get("radius", 200))
    page = int(request.args.get("page", 1))
    page_size = int(request.args.get("page_size", 10))
    results = find_nearby_addresses(lat, lng, radius, page, page_size)
    return jsonify(results)

# ✅ Swagger UI 页面（加载 openapi.yaml）
@app.route("/docs")
def swagger_ui():
    return send_from_directory("static/swagger", "index.html")

# ✅ Swagger 配置文件
@app.route("/docs/openapi.yaml")
def swagger_spec():
    return send_from_directory("static/swagger", "openapi.yaml")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)