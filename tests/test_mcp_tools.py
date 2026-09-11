# -*- coding: utf-8 -*-
"""MCP 工具的业务逻辑测试。全部对纯函数测试，不启动真实 MCP server/协议层。"""
from pathlib import Path

import pytest

from mcp_server import tools as t
from src.ingest import ingest_csv

DATA = Path(__file__).parent.parent / "data"


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """每个测试用独立的临时 SQLite 库，不污染项目正式的 data/history.db。"""
    db_path = str(tmp_path / "history.db")
    monkeypatch.setattr(t, "DB_PATH", db_path)
    ingest_csv(str(DATA / "competitors_2026-09-10.csv"), "2026-09-10", db_path)
    ingest_csv(str(DATA / "competitors_2026-09-11.csv"), "2026-09-11", db_path)
    return db_path


def test_get_competitor_snapshot_found():
    result = t.get_competitor_snapshot("TT-8841", "2026-09-10")
    assert result["found"] is True
    assert result["price"] == 12.99


def test_get_competitor_snapshot_not_found_lists_available_dates():
    result = t.get_competitor_snapshot("NOT-EXIST", "2026-09-10")
    assert result["found"] is False
    assert "2026-09-10" in result["available_dates"]


def test_score_product_tool_returns_breakdown():
    result = t.score_product_tool("TRAVEL-001")
    assert result["sku"] == "TRAVEL-001"
    assert result["eliminated"] is False
    assert set(result["breakdown"].keys()) == {
        "需求稳定性", "竞争缺口", "贡献利润", "物流履约", "合规风险", "内容展示"}


def test_score_product_tool_unknown_sku_raises():
    with pytest.raises(ValueError):
        t.score_product_tool("NOT-A-REAL-SKU")


def test_calculate_unit_profit_tool_matches_cli_logic():
    result = t.calculate_unit_profit_tool("TRAVEL-003", scenario="standard")
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


def test_draft_listing_requires_human_review_and_does_not_invent_features():
    result = t.draft_listing("TRAVEL-003")
    assert result["requires_human_review"] is True
    # 不应该凭空编卖点，scaffold 里的 core_features 必须留空等人工填写
    assert result["scaffold"]["core_features"] == []


def test_create_price_change_never_executes_only_suggests():
    result = t.create_price_change("TRAVEL-001", new_price=90.0)
    assert result["status"] == "suggestion_only"
    assert result["approval"] == "禁止自动执行，仅供人工参考"
    assert result["proposed_price"] == 90.0
    # 涨价应该让贡献利润率变化为正
    assert result["margin_delta"] > 0
