# -*- coding: utf-8 -*-
"""MCP 工具的业务逻辑，全部是纯函数，不依赖 MCP 协议层，方便直接单测。
server.py 只负责把这些函数注册成 MCP tool，不写业务逻辑。

审批边界（与 README / 手册第 6 章一致）：
- get_competitor_snapshot / score_product / calculate_unit_profit / build_weekly_report：只读
- draft_listing：产出需人工审核的草稿骨架，不产出可直接发布的最终文案
- create_price_change：只生成变更建议，禁止自动执行、不接入任何真实店铺
"""
from pathlib import Path
from typing import Optional

from src.calculator import load_products, load_yaml, score_product, calculate_unit_profit
from src.ingest import load_snapshot_from_db, query_snapshot_dates
from src.monitor import compare_snapshot_dicts, build_daily_digest, coverage_warning

BASE = Path(__file__).parent.parent
DATA = BASE / "data"
DB_PATH = str(DATA / "history.db")


def _load_configs():
    platform_cfg = load_yaml(str(DATA / "platforms.yaml"))
    logistics_cfg = load_yaml(str(DATA / "logistics_rates.yaml"))
    return platform_cfg, logistics_cfg


def _find_product(sku: str):
    products = {p.sku: p for p in load_products(str(DATA / "products.csv"))}
    if sku not in products:
        raise ValueError("找不到 SKU：%s（可用列表见 data/products.csv）" % sku)
    return products[sku]


# ---------------------------------------------------------------------------
# 只读工具
# ---------------------------------------------------------------------------

def get_competitor_snapshot(item_id: str, snapshot_date: str) -> dict:
    """读取某个竞品在某个快照日期的标准化记录。审批级别：只读。"""
    snapshot = load_snapshot_from_db(DB_PATH, snapshot_date)
    if item_id not in snapshot:
        return {"found": False, "item_id": item_id, "snapshot_date": snapshot_date,
                "available_dates": query_snapshot_dates(DB_PATH)}
    row = dict(snapshot[item_id])
    row["found"] = True
    return row


def score_product_tool(sku: str, platform: str = "tiktok_shop", market: str = "US",
                        scenario: str = "standard") -> dict:
    """对单个 SKU 跑六维度评分。审批级别：只读。"""
    product = _find_product(sku)
    platform_cfg, logistics_cfg = _load_configs()
    result = score_product(product, platform_cfg, logistics_cfg, platform, market, scenario)
    return {
        "sku": result.sku, "name": result.name, "total_score": result.total_score,
        "breakdown": {
            "需求稳定性": result.demand_score, "竞争缺口": result.gap_score,
            "贡献利润": result.profit_score, "物流履约": result.logistics_score,
            "合规风险": result.compliance_score, "内容展示": result.content_score,
        },
        "eliminated": result.eliminated, "eliminate_reason": result.eliminate_reason,
    }


def calculate_unit_profit_tool(sku: str, platform: str = "tiktok_shop", market: str = "US",
                                scenario: str = "standard", price: Optional[float] = None) -> dict:
    """计算单个 SKU 的贡献利润明细。审批级别：只读。"""
    product = _find_product(sku)
    platform_cfg, logistics_cfg = _load_configs()
    result = calculate_unit_profit(product, platform_cfg, logistics_cfg, platform, market, scenario, price)
    return {
        "sku": result.sku, "platform": result.platform, "market": result.market,
        "price": result.price, "breakeven_price": result.breakeven_price,
        "cost_breakdown": {
            "采购成本": result.cost_price, "包装成本": result.packaging_cost,
            "头程物流": result.logistics_cost, "平台佣金": result.commission_fee,
            "支付手续费": result.payment_fee, "退款准备金": result.return_reserve,
        },
        "contribution_profit": result.contribution_profit,
        "contribution_margin": result.contribution_margin,
        "breakeven_roas": result.breakeven_roas,
    }


def build_weekly_report(from_date: str, to_date: str) -> dict:
    """比较两个日期的竞品快照，生成周报事实摘要。
    Agent 只能引用这里返回的事实做解释和排版，不能自己编数字。审批级别：只读。
    """
    before = load_snapshot_from_db(DB_PATH, from_date)
    after = load_snapshot_from_db(DB_PATH, to_date)
    if not before or not after:
        return {
            "ok": False,
            "reason": "指定日期在历史库中不存在数据，请先用 cbops ingest 导入",
            "available_dates": query_snapshot_dates(DB_PATH),
        }
    changes = compare_snapshot_dicts(before, after)
    digest_markdown = build_daily_digest(changes)
    warning = coverage_warning(before, after)
    return {
        "ok": True,
        "from_date": from_date, "to_date": to_date,
        "coverage_warning": warning,
        "change_count": len(changes),
        "changes": [c.__dict__ for c in changes],
        "digest_markdown": digest_markdown,
    }


# ---------------------------------------------------------------------------
# 需人工审核 / 禁止自动执行的工具
# ---------------------------------------------------------------------------

def draft_listing(sku: str) -> dict:
    """产出 Listing 的策略骨架（卖点、关键词占位），不是最终文案。
    真正的文案需要把这份骨架喂给 skills/listing/ 下的 Prompt，由人工在 Claude/Codex
    对话里生成并审核，这里不直接调用任何 LLM API，保持本工具离线可跑。
    审批级别：人工审核后才可使用。
    """
    product = _find_product(sku)
    return {
        "sku": sku,
        "product_name": product.name,
        "category": product.category,
        "requires_human_review": True,
        "next_step": "把下面的 scaffold 填入 skills/listing/planning_layer.md 的输入模板，"
                     "交给 LLM 依次跑决策层 -> 执行层 -> 质检层，产出真正的文案草稿",
        "scaffold": {
            "product_name": product.name,
            "category": product.category,
            "core_features": [],  # 需要人工补充真实卖点，不在这里编造
            "target_platform": ["amazon", "independent_site", "tiktok_shop"],
            "target_market": "US",
            "tone": "待人工确定",
        },
    }


def create_price_change(sku: str, new_price: float, platform: str = "tiktok_shop",
                         market: str = "US", scenario: str = "standard") -> dict:
    """只生成改价建议和利润影响对比，绝不实际修改任何店铺数据。
    真实改价永远只能由人工登录平台后台手动执行。审批级别：禁止自动执行。
    """
    product = _find_product(sku)
    platform_cfg, logistics_cfg = _load_configs()

    current = calculate_unit_profit(product, platform_cfg, logistics_cfg, platform, market, scenario,
                                     price=product.planned_price)
    proposed = calculate_unit_profit(product, platform_cfg, logistics_cfg, platform, market, scenario,
                                      price=new_price)

    return {
        "status": "suggestion_only",
        "approval": "禁止自动执行，仅供人工参考",
        "sku": sku,
        "current_price": current.price,
        "current_contribution_margin": current.contribution_margin,
        "proposed_price": proposed.price,
        "proposed_contribution_margin": proposed.contribution_margin,
        "margin_delta": round(proposed.contribution_margin - current.contribution_margin, 4),
        "note": "本工具不接入任何真实店铺后台，实际改价请人工登录平台手动操作",
    }
