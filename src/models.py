# -*- coding: utf-8 -*-
"""数据模型：Product / ScoreResult / ProfitResult"""
from dataclasses import dataclass, field
from typing import Optional


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
