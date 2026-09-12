# -*- coding: utf-8 -*-
"""核心计算逻辑：选品评分 + 贡献利润测算。全部是纯函数，方便写单测，不依赖网络。"""
import csv
import yaml
from pathlib import Path
from typing import List, Optional

from .models import Product, ScoreResult, ProfitBreakdown, HARD_ELIMINATE_FLAGS, REVIEW_FLAGS

# 三档目标毛利率场景，对应手册里“保守/标准/激进”的说法
MARGIN_SCENARIOS = {
    "conservative": 0.20,
    "standard": 0.30,
    "aggressive": 0.40,
}

COMPLIANCE_SCORE_MAP = {
    "ok": 10.0,
    "review_needed": 5.0,
    "banned": 0.0,
}


# 留空时必须判「无法测算」而不是当 0 的字段。
# 采购价留空当 0 → 商品看起来免费 → 利润爆表 → 评分「通过」，是致命假信号。
COST_CRITICAL_FIELDS = ("cost_price", "packaging_cost", "weight_kg", "planned_price")


def load_products(csv_path: str) -> List[Product]:
    """读候选品。空的数字字段记进 missing_fields，不让它炸也不当成 0。

    为什么要容忍空值：选品工作台的流程就是「先加候选品，采购价留空，
    等第④步比完价再回填」。以前 float("") 直接抛 ValueError，
    会让 /api/data 返回 500，面板 boot() 整个中断——界面看着正常但按钮全失灵。
    """
    def num(row, key, missing):
        raw = (row.get(key) or "").strip() if isinstance(row.get(key), str) else row.get(key)
        if raw in (None, ""):
            missing.append(key)
            return 0.0
        try:
            return float(raw)
        except (TypeError, ValueError):
            missing.append(key)
            return 0.0

    products = []
    with open(csv_path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            missing = []
            planned_raw = (row.get("planned_price") or "")
            planned = None
            if str(planned_raw).strip():
                try:
                    planned = float(planned_raw)
                except (TypeError, ValueError):
                    missing.append("planned_price")
            else:
                missing.append("planned_price")
            products.append(Product(
                sku=row["sku"],
                name=row["name"],
                category=row["category"],
                cost_price=num(row, "cost_price", missing),
                packaging_cost=num(row, "packaging_cost", missing),
                weight_kg=num(row, "weight_kg", missing),
                volume_l=num(row, "volume_l", missing),
                compliance_flag=row["compliance_flag"],
                demand_score=num(row, "demand_score", missing),
                gap_score=num(row, "gap_score", missing),
                logistics_score=num(row, "logistics_score", missing),
                content_score=num(row, "content_score", missing),
                planned_price=planned,
                missing_fields=missing,
            ))
    return products


def load_yaml(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _fixed_costs(product: Product, logistics_cfg: dict, market: str) -> float:
    rates = logistics_cfg[market]
    logistics_cost = rates["base_fee"] + product.weight_kg * rates["rate_per_kg"]
    return product.cost_price + product.packaging_cost + logistics_cost, logistics_cost


def _rate_sum(product: Product, platform_cfg: dict, platform: str):
    cfg = platform_cfg[platform]
    return_rates = cfg.get("return_rate", {})
    return_rate = return_rates.get(product.category, return_rates.get("default", 0.0))
    commission_rate = cfg["commission_rate"]
    payment_fee_rate = cfg["payment_fee_rate"]
    return commission_rate, payment_fee_rate, return_rate


def calculate_unit_profit(
    product: Product,
    platform_cfg: dict,
    logistics_cfg: dict,
    platform: str,
    market: str,
    scenario: str = "standard",
    price: Optional[float] = None,
) -> ProfitBreakdown:
    """贡献利润 = 售价 - 采购 - 包装 - 头程物流 - 平台佣金 - 支付手续费 - 退款准备金
    未指定售价时，按 scenario 对应的目标毛利率反推建议定价。
    """
    if scenario not in MARGIN_SCENARIOS:
        raise ValueError("未知场景：%s，可选 %s" % (scenario, list(MARGIN_SCENARIOS)))

    fixed_costs, logistics_cost = _fixed_costs(product, logistics_cfg, market)
    commission_rate, payment_fee_rate, return_rate = _rate_sum(product, platform_cfg, platform)
    rate_sum = commission_rate + payment_fee_rate + return_rate

    if rate_sum >= 1:
        raise ValueError("平台费率总和超过 100%%，配置有误：%s" % platform)

    breakeven_price = fixed_costs / (1 - rate_sum)

    if price is None:
        target_margin = MARGIN_SCENARIOS[scenario]
        denom = 1 - rate_sum - target_margin
        if denom <= 0:
            raise ValueError("目标毛利率 %.0f%% 在当前费率结构下无法达成，费率合计已占 %.1f%%"
                              % (target_margin * 100, rate_sum * 100))
        price = fixed_costs / denom

    commission_fee = price * commission_rate
    payment_fee = price * payment_fee_rate
    return_reserve = price * return_rate
    contribution_profit = price - fixed_costs - commission_fee - payment_fee - return_reserve
    contribution_margin = contribution_profit / price if price else 0.0
    breakeven_roas = (1 / contribution_margin) if contribution_margin > 0 else None

    return ProfitBreakdown(
        sku=product.sku,
        platform=platform,
        market=market,
        price=round(price, 2),
        cost_price=product.cost_price,
        packaging_cost=product.packaging_cost,
        logistics_cost=round(logistics_cost, 2),
        commission_fee=round(commission_fee, 2),
        payment_fee=round(payment_fee, 2),
        return_reserve=round(return_reserve, 2),
        contribution_profit=round(contribution_profit, 2),
        contribution_margin=round(contribution_margin, 4),
        breakeven_price=round(breakeven_price, 2),
        breakeven_roas=round(breakeven_roas, 2) if breakeven_roas else None,
    )


def _profit_score(contribution_margin: float, target_margin: float = 0.30) -> float:
    """把贡献利润率映射到 0-20 分：达到 target_margin 记满分，超过或为负分别封顶/归零。"""
    if contribution_margin <= 0:
        return 0.0
    score = (contribution_margin / target_margin) * 20
    return round(min(20.0, max(0.0, score)), 2)


def score_product(
    product: Product,
    platform_cfg: dict,
    logistics_cfg: dict,
    platform: str = "tiktok_shop",
    market: str = "US",
    scenario: str = "standard",
) -> ScoreResult:
    """六维度评分 + 硬性淘汰规则。淘汰的商品总分记 0，理由写清楚，不参与排序竞争。"""
    if product.compliance_flag in HARD_ELIMINATE_FLAGS:
        return ScoreResult(
            sku=product.sku, name=product.name, total_score=0.0,
            demand_score=product.demand_score, gap_score=product.gap_score,
            profit_score=0.0, logistics_score=product.logistics_score,
            compliance_score=0.0, content_score=product.content_score,
            eliminated=True, eliminate_reason="合规标记为 banned：涉及禁限售或功效宣称风险，直接淘汰",
        )

    # 缺关键字段时判「无法测算」，不给分。
    # 绝不能把空值当 0 —— 采购价当 0 会让商品看起来免费、利润爆表、评分通过，
    # 那是比没有分数危险得多的假信号。
    blocking = [f for f in COST_CRITICAL_FIELDS if f in (product.missing_fields or [])]
    if blocking:
        names = {"cost_price": "采购价", "packaging_cost": "包装成本",
                 "weight_kg": "计费重量", "planned_price": "计划售价"}
        return ScoreResult(
            sku=product.sku, name=product.name, total_score=0.0,
            demand_score=product.demand_score, gap_score=product.gap_score,
            profit_score=0.0, logistics_score=product.logistics_score,
            compliance_score=0.0, content_score=product.content_score,
            eliminated=True,
            eliminate_reason="无法测算：缺少 %s。补齐后才会有真实分数（采购价可在「④ 供应商比价」比完后自动回填）"
                             % "、".join(names.get(f, f) for f in blocking),
        )

    try:
        # 评分要反映真实优劣，必须用计划售价（参考竞品定价）算利润，
        # 而不是自动反推的目标毛利定价——否则每个商品都会被反推成刚好达标，利润分永远满分，起不到区分作用。
        profit = calculate_unit_profit(product, platform_cfg, logistics_cfg, platform, market,
                                        scenario, price=product.planned_price)
    except ValueError as e:
        return ScoreResult(
            sku=product.sku, name=product.name, total_score=0.0,
            demand_score=product.demand_score, gap_score=product.gap_score,
            profit_score=0.0, logistics_score=product.logistics_score,
            compliance_score=COMPLIANCE_SCORE_MAP.get(product.compliance_flag, 0.0),
            content_score=product.content_score,
            eliminated=True, eliminate_reason="利润测算失败：%s" % e,
        )

    if profit.contribution_profit <= 0:
        return ScoreResult(
            sku=product.sku, name=product.name, total_score=0.0,
            demand_score=product.demand_score, gap_score=product.gap_score,
            profit_score=0.0, logistics_score=product.logistics_score,
            compliance_score=COMPLIANCE_SCORE_MAP.get(product.compliance_flag, 0.0),
            content_score=product.content_score,
            eliminated=True, eliminate_reason="贡献利润为负或为零，成本无法覆盖，直接淘汰",
        )

    profit_score = _profit_score(profit.contribution_margin)
    compliance_score = COMPLIANCE_SCORE_MAP.get(product.compliance_flag, 0.0)

    total = (product.demand_score + product.gap_score + profit_score
             + product.logistics_score + compliance_score + product.content_score)

    reason = ""
    if product.compliance_flag in REVIEW_FLAGS:
        reason = "合规标记为 review_needed：未淘汰，但需人工复核（如儿童/健康类目的功效表述）"

    return ScoreResult(
        sku=product.sku, name=product.name, total_score=round(total, 2),
        demand_score=product.demand_score, gap_score=product.gap_score,
        profit_score=profit_score, logistics_score=product.logistics_score,
        compliance_score=compliance_score, content_score=product.content_score,
        eliminated=False, eliminate_reason=reason,
    )


def score_all(products: List[Product], platform_cfg: dict, logistics_cfg: dict,
              platform: str = "tiktok_shop", market: str = "US",
              scenario: str = "standard") -> List[ScoreResult]:
    results = [score_product(p, platform_cfg, logistics_cfg, platform, market, scenario) for p in products]
    # 淘汰的排最后，其余按总分降序
    results.sort(key=lambda r: (r.eliminated, -r.total_score))
    return results
