# -*- coding: utf-8 -*-
"""数据模型：Product / ScoreResult / ProfitResult"""
from dataclasses import dataclass, field
from typing import Optional, List


# 硬性淘汰的合规标记 —— 出现即直接淘汰，不参与总分计算
HARD_ELIMINATE_FLAGS = {"banned"}
# 需要人工复核但不直接淘汰的标记
REVIEW_FLAGS = {"review_needed"}


@dataclass
class Product:
    sku: str
    name: str
    category: str
    cost_price: float
    packaging_cost: float
    weight_kg: float
    volume_l: float
    compliance_flag: str
    demand_score: float   # 需求稳定性原始分（满分25）
    gap_score: float       # 竞争缺口原始分（满分20）
    logistics_score: float  # 物流履约原始分（满分15）
    content_score: float   # 内容展示空间原始分（满分10）
    planned_price: Optional[float] = field(default=None)  # 计划售价（参考竞品定价），用于算真实利润分
    # 贡献利润分（满分20）由 ProfitCalculator 算出后回填，不在原始数据里
    profit_score: Optional[float] = field(default=None)
    # CSV 里留空的数字字段。**不能当成 0** —— 采购价留空当 0，商品会显示成
    # 「免费」从而利润爆表、评分通过，是假信号。所以记下来，评分时直接判无法测算。
    # 选品工作台的流程本来就要求采购价先留空（等第④步比价后回填），
    # 所以这是正常状态，不是坏数据。
    missing_fields: List[str] = field(default_factory=list)


@dataclass
class ScoreResult:
    sku: str
    name: str
    total_score: float
    demand_score: float
    gap_score: float
    profit_score: float
    logistics_score: float
    compliance_score: float
    content_score: float
    eliminated: bool
    eliminate_reason: str


@dataclass
class ProfitBreakdown:
    sku: str
    platform: str
    market: str
    price: float
    cost_price: float
    packaging_cost: float
    logistics_cost: float
    commission_fee: float
    payment_fee: float
    return_reserve: float
    contribution_profit: float
    contribution_margin: float  # 贡献利润率
    breakeven_price: float
    breakeven_roas: Optional[float]
