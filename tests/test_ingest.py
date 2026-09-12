# -*- coding: utf-8 -*-
import sqlite3
from pathlib import Path

import pytest

from src.ingest import ingest_csv, query_snapshot_dates

DATA = Path(__file__).parent.parent / "data"
# 测试自带数据。不能用 data/ 下的文件——那是用户数据，
# `reset_data.py --all` 会清空它，清完跑测试会一片红。
FIXTURES = Path(__file__).parent / "fixtures"



def test_ingest_creates_expected_rows(tmp_path):
    db_path = str(tmp_path / "test_history.db")
    count = ingest_csv(str(FIXTURES / "snapshot_day1.csv"), "2026-09-10", db_path)
    assert count == 5

    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT item_id, price FROM competitor_snapshots WHERE snapshot_date=?",
                         ("2026-09-10",)).fetchall()
    conn.close()
    assert len(rows) == 5


def test_ingest_missing_column_raises(tmp_path):
    bad_csv = tmp_path / "bad.csv"
    bad_csv.write_text("platform,item_id,title\ntiktok_shop,X1,Test\n", encoding="utf-8")
    with pytest.raises(ValueError):
        ingest_csv(str(bad_csv), "2026-09-10", str(tmp_path / "db.sqlite"))


def test_reingest_same_date_replaces_not_duplicates(tmp_path):
    db_path = str(tmp_path / "test_history.db")
    ingest_csv(str(FIXTURES / "snapshot_day1.csv"), "2026-09-10", db_path)
    ingest_csv(str(FIXTURES / "snapshot_day1.csv"), "2026-09-10", db_path)  # 重复导入同一天

    conn = sqlite3.connect(db_path)
    total = conn.execute("SELECT COUNT(*) FROM competitor_snapshots WHERE snapshot_date=?",
                          ("2026-09-10",)).fetchone()[0]
    conn.close()
    assert total == 5  # 应该被覆盖，不是变成 10 条


def test_query_snapshot_dates_lists_all_ingested_dates(tmp_path):
    db_path = str(tmp_path / "test_history.db")
    ingest_csv(str(FIXTURES / "snapshot_day1.csv"), "2026-09-10", db_path)
    ingest_csv(str(FIXTURES / "snapshot_day2.csv"), "2026-09-11", db_path)
    assert query_snapshot_dates(db_path) == ["2026-09-10", "2026-09-11"]


def test_query_snapshot_dates_empty_when_no_db(tmp_path):
    assert query_snapshot_dates(str(tmp_path / "not_exist.db")) == []
