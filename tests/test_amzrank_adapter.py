# -*- coding: utf-8 -*-
"""amzrank 适配层测试。不发任何网络请求，用内存构造的表格数据。"""
import csv
from pathlib import Path

import openpyxl
import pytest

from adapters.amzrank_adapter import (
    _price_column, load_amzrank_xlsx, to_snapshot_rows, write_snapshot_csv,
    SNAPSHOT_COLUMNS, EXTRA_COLUMNS,
)
from src.ingest import REQUIRED_COLUMNS


def make_amzrank_xlsx(path, rows, currency="USD"):
    """造一个和 amzrank 真实输出同构的 xlsx。"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["排名", "ASIN", "商品标题（原文）", "评分", "评论数",
               "价格(%s)" % currency, "类目", "商品链接"])
    for r in rows:
        ws.append(r)
    wb.save(path)
    return path


def test_price_column_matches_any_currency():
    assert _price_column(["排名", "价格(USD)"]) == "价格(USD)"
    assert _price_column(["排名", "价格(JPY)"]) == "价格(JPY)"
    assert _price_column(["排名", "评分"]) is None


def test_missing_price_column_raises(tmp_path):
    wb = openpyxl.Workbook()
    wb.active.append(["排名", "ASIN", "商品标题（原文）"])
    p = tmp_path / "no_price.xlsx"
    wb.save(p)
    with pytest.raises(ValueError):
        load_amzrank_xlsx(str(p))


def test_load_and_convert_roundtrip(tmp_path):
    src = make_amzrank_xlsx(tmp_path / "a.xlsx", [
        [1, "B0009X29WK", "Cat Litter 40 lb", 4.4, 69927, 22.99, "pet-supplies",
         "https://www.amazon.com/dp/B0009X29WK"],
        [2, "B00MW8G62E", "Puppy Pee Pads", 4.4, 220841, 18.99, "pet-supplies",
         "https://www.amazon.com/dp/B00MW8G62E"],
    ])
    records = load_amzrank_xlsx(str(src))
    assert len(records) == 2
    assert records[0]["item_id"] == "B0009X29WK"
    assert records[0]["price"] == 22.99

    rows = to_snapshot_rows(records, "2026-09-11")
    assert rows[0]["platform"] == "amazon"
    assert rows[0]["review_count"] == 69927
    assert rows[0]["collected_date"] == "2026-09-11"
    # amzrank 不采集促销，必须显式写 unknown，不能留空冒充「无促销」
    assert rows[0]["promotion"] == "unknown"


def test_rows_without_price_are_skipped(tmp_path):
    """没有价格的记录必须跳过——无价格无法参与利润测算和降价比对。"""
    src = make_amzrank_xlsx(tmp_path / "b.xlsx", [
        [1, "B001", "Has price", 4.5, 100, 19.99, "pet-supplies", "u1"],
        [2, "B002", "No price", 4.5, 100, None, "pet-supplies", "u2"],
        [3, "B003", "Empty price", 4.5, 100, "", "pet-supplies", "u3"],
    ])
    rows = to_snapshot_rows(load_amzrank_xlsx(str(src)), "2026-09-11")
    assert [r["item_id"] for r in rows] == ["B001"]


def test_rows_without_asin_are_skipped(tmp_path):
    src = make_amzrank_xlsx(tmp_path / "c.xlsx", [
        [1, None, "No ASIN", 4.5, 100, 19.99, "pet-supplies", "u1"],
        [2, "B002", "Has ASIN", 4.5, 100, 19.99, "pet-supplies", "u2"],
    ])
    rows = to_snapshot_rows(load_amzrank_xlsx(str(src)), "2026-09-11")
    assert [r["item_id"] for r in rows] == ["B002"]


def test_non_numeric_review_count_defaults_to_zero(tmp_path):
    src = make_amzrank_xlsx(tmp_path / "d.xlsx", [
        [1, "B001", "Weird reviews", 4.5, "1,234", 19.99, "pet-supplies", "u1"],
    ])
    rows = to_snapshot_rows(load_amzrank_xlsx(str(src)), "2026-09-11")
    assert rows[0]["review_count"] == 0  # 带逗号的字符串不硬转，降级为 0 而不是抛错


def test_output_csv_satisfies_ingest_required_columns(tmp_path):
    """适配层产出的 CSV 必须能被 src/ingest.py 直接吃下去——这是解耦架构的契约。"""
    src = make_amzrank_xlsx(tmp_path / "e.xlsx", [
        [1, "B001", "Item", 4.5, 100, 19.99, "pet-supplies", "https://x/1"],
    ])
    out = tmp_path / "snap.csv"
    n = write_snapshot_csv(to_snapshot_rows(load_amzrank_xlsx(str(src)), "2026-09-11"), str(out))
    assert n == 1

    with open(out, encoding="utf-8-sig") as f:
        headers = set(next(csv.reader(f)))
    missing = REQUIRED_COLUMNS - headers
    assert not missing, "适配层输出缺少 ingest 必需字段：%s" % missing


def test_snapshot_csv_keeps_rank_and_provenance(tmp_path):
    """rank 和来源信息要保留（ingest 会忽略，但出报告和标注数据来源时需要）。"""
    src = make_amzrank_xlsx(tmp_path / "f.xlsx", [
        [7, "B001", "Item", 4.5, 100, 19.99, "pet-supplies", "https://x/1"],
    ])
    out = tmp_path / "snap.csv"
    write_snapshot_csv(to_snapshot_rows(load_amzrank_xlsx(str(src)), "2026-09-11"), str(out))
    with open(out, encoding="utf-8-sig") as f:
        row = next(csv.DictReader(f))
    assert row["rank"] == "7"
    assert row["source"] == "amzrank"
    assert row["collected_date"] == "2026-09-11"


# ---------------------------------------------------------------------------
# latest_amzrank_output 的两个真实踩坑
# ---------------------------------------------------------------------------

def test_latest_output_ignores_excel_lock_files(tmp_path):
    """Excel 打开 xlsx 时会生成 `~$开头` 的锁文件。
    波浪号 ASCII(0x7E) 比字母大，按文件名排序会把它当成「最新」，
    然后 openpyxl 读它就是 PermissionError。必须排除。
    """
    from adapters.amzrank_adapter import latest_amzrank_output
    import os, time

    real = tmp_path / "us_bestsellers_pet-supplies_20260911-0418.xlsx"
    make_amzrank_xlsx(real, [[1, "B001", "Item", 4.5, 100, 19.99, "pet", "u"]])
    # 造一个锁文件，且让它的修改时间更新（模拟刚用 Excel 打开）
    lock = tmp_path / "~$us_bestsellers_pet-supplies_20260911-0733.xlsx"
    lock.write_bytes(b"not a real xlsx")
    os.utime(lock, (time.time() + 10, time.time() + 10))

    picked = latest_amzrank_output(str(tmp_path))
    assert Path(picked).name == real.name, "不应选中 Excel 锁文件，实际选了 %s" % picked


def test_latest_output_picks_newest_by_mtime(tmp_path):
    """按修改时间取最新，不依赖文件名里的时间戳格式。"""
    from adapters.amzrank_adapter import latest_amzrank_output
    import os, time

    older = tmp_path / "zzz_looks_last_alphabetically.xlsx"
    newer = tmp_path / "aaa_actually_newest.xlsx"
    make_amzrank_xlsx(older, [[1, "B001", "Old", 4.5, 100, 19.99, "pet", "u"]])
    make_amzrank_xlsx(newer, [[1, "B002", "New", 4.5, 100, 19.99, "pet", "u"]])
    os.utime(older, (time.time() - 100, time.time() - 100))

    assert Path(latest_amzrank_output(str(tmp_path))).name == newer.name


def test_latest_output_raises_when_only_lock_files(tmp_path):
    from adapters.amzrank_adapter import latest_amzrank_output
    (tmp_path / "~$only_a_lock.xlsx").write_bytes(b"x")
    with pytest.raises(FileNotFoundError):
        latest_amzrank_output(str(tmp_path))
