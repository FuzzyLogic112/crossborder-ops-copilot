# -*- coding: utf-8 -*-
"""MCP 工具的业务逻辑测试。全部对纯函数测试，不启动真实 MCP server/协议层。"""
from pathlib import Path

import pytest

from mcp_server import tools as t
from src.ingest import ingest_csv

DATA = Path(__file__).parent.parent / "data"
# 测试自带数据。不能用 data/ 下的文件——那是用户数据，
# `reset_data.py --all` 会清空它，清完跑测试会一片红。
FIXTURES = Path(__file__).parent / "fixtures"



@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """每个测试用独立的临时 SQLite 库，不污染项目正式的 data/history.db。"""
    db_path = str(tmp_path / "history.db")
    monkeypatch.setattr(t, "DB_PATH", db_path)
    ingest_csv(str(FIXTURES / "snapshot_day1.csv"), "2026-09-10", db_path)
    ingest_csv(str(FIXTURES / "snapshot_day2.csv"), "2026-09-11", db_path)
    return db_path


def test_get_competitor_snapshot_found():
    result = t.get_competitor_snapshot("TT-8841", "2026-09-10")
    assert result["found"] is True
    assert result["price"] == 12.99


def test_get_competitor_snapshot_not_found_lists_available_dates():
    result = t.get_competitor_snapshot("NOT-EXIST", "2026-09-10")
    assert result["found"] is False
    assert "2026-09-10" in result["available_dates"]


def test_score_product_tool_returns_breakdown(viable_sku):
    result = t.score_product_tool(viable_sku)
    assert result["sku"] == viable_sku
    assert result["eliminated"] is False
    assert set(result["breakdown"].keys()) == {
        "需求稳定性", "竞争缺口", "贡献利润", "物流履约", "合规风险", "内容展示"}


def test_score_product_tool_unknown_sku_raises():
    with pytest.raises(ValueError):
        t.score_product_tool("NOT-A-REAL-SKU")


def test_calculate_unit_profit_tool_matches_cli_logic(any_sku):
    result = t.calculate_unit_profit_tool(any_sku, scenario="standard")
    assert result["contribution_margin"] == pytest.approx(0.30, abs=0.01)
    assert result["breakeven_roas"] == pytest.approx(1 / 0.30, abs=0.05)


def test_build_weekly_report_detects_changes():
    report = t.build_weekly_report("2026-09-10", "2026-09-11")
    assert report["ok"] is True
    assert report["change_count"] > 0
    assert "price_drop" in report["digest_markdown"]


def test_build_weekly_report_missing_date_returns_ok_false():
    report = t.build_weekly_report("2099-01-01", "2099-01-02")
    assert report["ok"] is False
    assert "available_dates" in report


def test_draft_listing_requires_human_review_and_does_not_invent_features(any_sku):
    result = t.draft_listing(any_sku)
    assert result["requires_human_review"] is True
    # 不应该凭空编卖点，scaffold 里的 core_features 必须留空等人工填写
    assert result["scaffold"]["core_features"] == []


def test_create_price_change_never_executes_only_suggests(any_sku):
    # 用「当前计划售价 × 1.3」做涨价，而不是写死 90 ——
    # 90 对某些品是涨价、对另一些是降价，写死会让断言方向随数据翻转。
    current = t.calculate_unit_profit_tool(any_sku)["price"]
    higher = round(current * 1.3, 2)
    result = t.create_price_change(any_sku, new_price=higher)
    assert result["status"] == "suggestion_only"
    assert result["approval"] == "禁止自动执行，仅供人工参考"
    assert result["proposed_price"] == higher
    # 涨价必然提高贡献利润率（费率是按售价百分比收的，涨价后固定成本占比下降）
    assert result["margin_delta"] > 0
