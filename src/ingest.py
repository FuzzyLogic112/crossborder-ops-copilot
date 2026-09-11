# -*- coding: utf-8 -*-
"""数据导入：把竞品 CSV 清洗校验后写入本地 SQLite 历史快照表。
这是 Day 3 自动化工作流（导入 -> 清洗 -> 写入快照 -> 比较 -> 计算 -> 生成日报 -> 人工审核）的地基。
只接受公开可见、已授权导出的 CSV，不做任何联网抓取。
"""
import csv
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

REQUIRED_COLUMNS = {"platform", "item_id", "title", "price", "rating", "review_count", "promotion", "url"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS competitor_snapshots (
    snapshot_date TEXT NOT NULL,
    platform TEXT NOT NULL,
    item_id TEXT NOT NULL,
    title TEXT,
    price REAL,
    rating REAL,
    review_count INTEGER,
    promotion TEXT,
    url TEXT,
    ingested_at TEXT NOT NULL,
    PRIMARY KEY (snapshot_date, platform, item_id)
);
"""


def ingest_csv(csv_path: str, snapshot_date: str, db_path: str) -> int:
    """校验并导入一份竞品快照 CSV。返回成功导入的行数。
    重复导入同一个 snapshot_date + platform + item_id 会被覆盖（INSERT OR REPLACE），
    方便同一天多次跑脚本纠错，不会产生重复历史记录。
    """
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ValueError("CSV 缺少必需字段：%s" % ", ".join(sorted(missing)))
        rows = list(reader)

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(SCHEMA)
        now = datetime.now(timezone.utc).isoformat()
        for row in rows:
            conn.execute(
                """INSERT OR REPLACE INTO competitor_snapshots
                   (snapshot_date, platform, item_id, title, price, rating, review_count, promotion, url, ingested_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (snapshot_date, row["platform"], row["item_id"], row["title"],
                 float(row["price"]), float(row["rating"] or 0), int(row["review_count"] or 0),
                 row.get("promotion", ""), row.get("url", ""), now),
            )
        conn.commit()
        return len(rows)
    finally:
        conn.close()


def load_snapshot_from_db(db_path: str, snapshot_date: str) -> dict:
    """从 SQLite 历史库读出某一天的快照，格式对齐 monitor.load_snapshot 的 CSV 输出，
    方便 compare_snapshot_dicts 不用关心数据来自文件还是数据库。
    """
    if not Path(db_path).exists():
        return {}
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            "SELECT platform, item_id, title, price, rating, review_count, promotion, url "
            "FROM competitor_snapshots WHERE snapshot_date = ?",
            (snapshot_date,),
        )
        return {row["item_id"]: dict(row) for row in cur.fetchall()}
    finally:
        conn.close()


def query_snapshot_dates(db_path: str):
    """列出数据库里已有哪些快照日期，方便决定 compare-snapshots 该比较哪两天。"""
    if not Path(db_path).exists():
        return []
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute("SELECT DISTINCT snapshot_date FROM competitor_snapshots ORDER BY snapshot_date")
        return [row[0] for row in cur.fetchall()]
    finally:
        conn.close()
