# -*- coding: utf-8 -*-
"""amzrank 适配层：把 amzrank 抓取的亚马逊榜单数据转成本项目的竞品快照 CSV 格式。

这一层的存在是整个项目「数据源与抓取逻辑解耦」的实现：
  - 抓取由外部工具负责（amzrank 用 Playwright 抓 Best Sellers 榜单页）
  - 本项目只认一种标准化的竞品快照格式
  - 换平台只需要再写一个 adapter，core 的评分/利润/比对逻辑一行都不用改

数据边界：
  - 只处理 amzrank 已经落盘的结果文件，本模块自身不发任何网络请求
  - 榜单页是平台公开浏览页面；抓取频率与礼貌性由 amzrank 侧控制（默认 3 秒间隔）
  - 抓到的是**真实公开数据**，与 data/competitors_*.csv 里的训练用虚构数据必须分开存放
"""
import csv
import glob
import re
from pathlib import Path
from typing import List, Optional

# 本项目竞品快照的标准字段（与 src/ingest.py 的 REQUIRED_COLUMNS 对齐）
SNAPSHOT_COLUMNS = ["platform", "item_id", "title", "price", "rating",
                    "review_count", "promotion", "url"]
# 额外保留的字段：ingest 会忽略它们，但出报告时有用
EXTRA_COLUMNS = ["rank", "category", "source", "collected_date"]

# amzrank 输出的 xlsx 表头（中文）→ 内部字段名
XLSX_HEADER_MAP = {
    "排名": "rank",
    "ASIN": "item_id",
    "商品标题（原文）": "title",
    "评分": "rating",
    "评论数": "review_count",
    "类目": "category",
    "商品链接": "url",
}


def _price_column(headers: List[str]) -> Optional[str]:
    """价格列名带币种，形如「价格(USD)」「价格(JPY)」，用正则匹配。"""
    for h in headers:
        if h and re.match(r"^价格", str(h)):
            return h
    return None


def load_amzrank_xlsx(path: str) -> List[dict]:
    """读 amzrank 导出的 xlsx（只读第一个 sheet，即单类目结果）。"""
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows_iter = ws.iter_rows(values_only=True)
    headers = [str(h) if h is not None else "" for h in next(rows_iter)]

    price_col = _price_column(headers)
    if price_col is None:
        raise ValueError("在表头里找不到价格列（应形如「价格(USD)」）：%s" % headers)

    idx = {h: i for i, h in enumerate(headers)}
    out = []
    for raw in rows_iter:
        if raw is None or all(c is None for c in raw):
            continue
        rec = {}
        for zh, field in XLSX_HEADER_MAP.items():
            if zh in idx:
                rec[field] = raw[idx[zh]]
        rec["price"] = raw[idx[price_col]]
        out.append(rec)
    wb.close()
    return out


def to_snapshot_rows(records: List[dict], collected_date: str,
                      platform: str = "amazon", source: str = "amzrank") -> List[dict]:
    """转成标准竞品快照行。跳过价格缺失的记录——没有价格无法参与利润与降价比对。"""
    rows = []
    for r in records:
        price = r.get("price")
        if price in (None, "", "-"):
            continue
        try:
            price = float(price)
        except (TypeError, ValueError):
            continue

        item_id = r.get("item_id")
        if not item_id:
            continue

        rows.append({
            "platform": platform,
            "item_id": str(item_id).strip(),
            "title": str(r.get("title") or "").strip(),
            "price": price,
            "rating": r.get("rating") if r.get("rating") not in (None, "") else 0,
            "review_count": int(r["review_count"]) if str(r.get("review_count") or "").strip().isdigit() else 0,
            # amzrank 不采集促销信息，明确写 unknown，不要留空冒充「无促销」
            "promotion": "unknown",
            "url": str(r.get("url") or "").strip(),
            "rank": r.get("rank"),
            "category": str(r.get("category") or "").strip(),
            "source": source,
            "collected_date": collected_date,
        })
    return rows


def write_snapshot_csv(rows: List[dict], out_path: str) -> int:
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=SNAPSHOT_COLUMNS + EXTRA_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def latest_amzrank_output(amzrank_out_dir: str) -> str:
    """找 amzrank_out 目录里最新的 xlsx。

    两个坑：
    1. Excel 打开 xlsx 时会在同目录生成 `~$开头` 的锁文件，并独占锁定它。
       波浪号的 ASCII(0x7E) 比所有字母都大，按文件名排序会把它排到最后当成「最新」，
       然后 openpyxl 去读就是 PermissionError。必须排除掉。
    2. 按文件名排序依赖命名里的时间戳格式，换个命名规则就失效；按修改时间取最新更可靠。
    """
    files = [
        f for f in glob.glob(str(Path(amzrank_out_dir) / "*.xlsx"))
        if not Path(f).name.startswith("~$")
    ]
    if not files:
        raise FileNotFoundError(
            "在 %s 下找不到 amzrank 导出的 xlsx（已排除 Excel 锁文件）" % amzrank_out_dir)
    return max(files, key=lambda f: Path(f).stat().st_mtime)


def convert(input_xlsx: str, out_csv: str, collected_date: str,
            platform: str = "amazon") -> int:
    records = load_amzrank_xlsx(input_xlsx)
    rows = to_snapshot_rows(records, collected_date, platform=platform)
    return write_snapshot_csv(rows, out_csv)
