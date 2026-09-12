# -*- coding: utf-8 -*-
"""对 MCP 协议层做一次真实调用验证，而不是只测底层函数。
确保 server.py 里的 @mcp.tool() 注册没有写错参数名、返回类型没有被协议层污染。
"""
import json
from pathlib import Path

import pytest

DATA = Path(__file__).parent.parent / "data"


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    from mcp_server import tools as t
    from src.ingest import ingest_csv
    db_path = str(tmp_path / "history.db")
    monkeypatch.setattr(t, "DB_PATH", db_path)
    ingest_csv(str(DATA / "competitors_2026-09-10.csv"), "2026-09-10", db_path)
    ingest_csv(str(DATA / "competitors_2026-09-11.csv"), "2026-09-11", db_path)
    return db_path


@pytest.mark.anyio
async def test_all_six_tools_are_registered():
    from mcp_server.server import mcp
    tools = await mcp.list_tools()
    names = {tl.name for tl in tools}
    assert names == {
        "get_competitor_snapshot", "score_product", "calculate_unit_profit",
        "build_weekly_report", "draft_listing", "create_price_change",
    }


@pytest.mark.anyio
async def test_call_tool_calculate_unit_profit_via_protocol_layer(any_sku):
    from mcp_server.server import mcp
    result = await mcp.call_tool("calculate_unit_profit", {"sku": any_sku, "scenario": "standard"})
    assert result.is_error is False
    payload = json.loads(result.content[0].text)
    assert payload["sku"] == any_sku
    assert payload["contribution_margin"] == pytest.approx(0.30, abs=0.01)


@pytest.mark.anyio
async def test_call_tool_create_price_change_never_marks_executed(any_sku):
    from mcp_server.server import mcp
    result = await mcp.call_tool("create_price_change", {"sku": any_sku, "new_price": 90.0})
    payload = json.loads(result.content[0].text)
    assert payload["status"] == "suggestion_only"
    assert "禁止自动执行" in payload["approval"]


@pytest.fixture
def anyio_backend():
    return "asyncio"
