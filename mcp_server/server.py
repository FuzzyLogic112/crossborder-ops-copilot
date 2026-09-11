# -*- coding: utf-8 -*-
"""跨境电商运营智能副驾驶 —— 本地只读 MCP Server

只是把 mcp_server/tools.py 里已经测试过的纯函数注册成 MCP tool，不在这里写业务逻辑。
本地 stdio 运行，不监听网络端口，不需要任何 API Key。

启动方式：
  python mcp_server/server.py
在 Claude Desktop / Claude Code 的 MCP 配置里指向这个文件即可接入。
"""
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.server.mcpserver import MCPServer
from mcp_server import tools as t

mcp = MCPServer(
    name="crossborder-ops-copilot",
    instructions=(
        "跨境电商运营只读数据工具集。除 draft_listing / create_price_change 外均为只读，"
        "不接入任何真实店铺、不执行任何自动改价/上架/投放/发消息操作。"
        "所有数字必须来自工具返回结果，禁止在此基础上编造未出现的数据。"
    ),
)


@mcp.tool()
def get_competitor_snapshot(item_id: str, snapshot_date: str) -> dict:
    """读取某个竞品在某个快照日期的标准化记录（价格/评分/评价数/促销）。只读工具。"""
    return t.get_competitor_snapshot(item_id, snapshot_date)


@mcp.tool()
def score_product(sku: str, platform: str = "tiktok_shop", market: str = "US",
                   scenario: str = "standard") -> dict:
    """对指定 SKU 跑六维度选品评分，返回分项得分和是否被硬性淘汰。只读工具。"""
    return t.score_product_tool(sku, platform, market, scenario)


@mcp.tool()
def calculate_unit_profit(sku: str, platform: str = "tiktok_shop", market: str = "US",
                           scenario: str = "standard", price: Optional[float] = None) -> dict:
    """计算指定 SKU 的贡献利润明细、保本价、贡献利润率与广告 Broke-even ROAS。只读工具。"""
    return t.calculate_unit_profit_tool(sku, platform, market, scenario, price)


@mcp.tool()
def build_weekly_report(from_date: str, to_date: str) -> dict:
    """比较两个快照日期，生成竞品变化周报事实摘要。Agent 编排周报时只能引用这里返回的事实，
    不得自行编造未出现的数据。只读工具。"""
    return t.build_weekly_report(from_date, to_date)


@mcp.tool()
def draft_listing(sku: str) -> dict:
    """产出 Listing 内容策略骨架（非最终文案），标记 requires_human_review=True。
    需人工审核后才可用于后续生成流程。"""
    return t.draft_listing(sku)


@mcp.tool()
def create_price_change(sku: str, new_price: float, platform: str = "tiktok_shop",
                         market: str = "US", scenario: str = "standard") -> dict:
    """生成改价建议与利润影响对比，绝不实际修改任何店铺数据。禁止自动执行，仅供人工参考。"""
    return t.create_price_change(sku, new_price, platform, market, scenario)


if __name__ == "__main__":
    mcp.run(transport="stdio")
