import sqlite3
import os

DB_PATH = "address.db"  # 默认数据库文件名

def build_database(db_path=DB_PATH):
    # ✅ 如果数据库已存在，则先删除旧文件，确保干净初始化
    if os.path.exists(db_path):
        os.remove(db_path)

    # ✅ 创建数据库连接
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # ✅ 创建主表 custom_address
    # 存储结构化地址信息，包括经纬度、行政区划、标签、备注等
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS custom_address (
        id TEXT PRIMARY KEY,           -- 地址唯一 ID
        name TEXT UNIQUE,              -- 地址简称，如`六道口西北角`
        address TEXT UNIQUE,           -- 详细地址文本
        lat REAL NOT NULL,             -- 纬度
        lng REAL NOT NULL,             -- 经度
        province TEXT,                 -- 所属省份
        district TEXT,                 -- 所属区县
        township TEXT,                 -- 所属乡镇街道
        tag TEXT,                      -- 自定义标签
        comment TEXT,                  -- 用户备注
        updated_at INTEGER             -- 更新时间（Unix 时间戳）
    )
    """)

    # ✅ 创建全文索引表 custom_address_fts（FTS5 引擎）
    # 针对 name 和 address 字段构建分词索引，用于支持模糊搜索
    # 使用 content_rowid 将其绑定到主表的 rowid，支持触发器同步
    cursor.execute("""
    CREATE VIRTUAL TABLE IF NOT EXISTS custom_address_fts USING fts5(
        name,
        address,
        content='custom_address',
        content_rowid='rowid'
    )
    """)

    # ✅ 创建触发器，实现主表与 FTS 索引表之间的自动同步

    # 插入时同步写入索引
    # 例：insert into custom_address(...) → 自动 insert into custom_address_fts
    cursor.executescript("""
    CREATE TRIGGER IF NOT EXISTS custom_address_ai AFTER INSERT ON custom_address BEGIN
      INSERT INTO custom_address_fts(rowid, name, address) VALUES (new.rowid, new.name, new.address);
    END;

    -- 更新时同步更新索引内容
    CREATE TRIGGER IF NOT EXISTS custom_address_au AFTER UPDATE ON custom_address BEGIN
      UPDATE custom_address_fts SET name = new.name, address = new.address WHERE rowid = old.rowid;
    END;

    -- 删除时同步删除索引记录
    CREATE TRIGGER IF NOT EXISTS custom_address_ad AFTER DELETE ON custom_address BEGIN
      DELETE FROM custom_address_fts WHERE rowid = old.rowid;
    END;
    """)

    # ✅ 提交并关闭连接
    conn.commit()
    conn.close()
    print(f"✅ 数据库已创建: {db_path}")

# ✅ 命令行执行入口
if __name__ == "__main__":
    build_database()
