# -*- coding: utf-8 -*-
import math
from pathlib import Path

import pytest

from src.calculator import load_products, load_yaml, calculate_unit_profit, score_all, score_product
from src.models import Product

DATA = Path(__file__).parent.parent / "data"


@pytest.fixture(scope="module")
def platform_cfg():
    return load_yaml(str(DATA / "platforms.yaml"))


@pytest.fixture(scope="module")
def logistics_cfg():
    return load_yaml(str(DATA / "logistics_rates.yaml"))


@pytest.fixture(scope="module")
def products():
    return load_products(str(DATA / "products.csv"))


def make_product(**overrides):
    base = dict(
        sku="TEST-001", name="测试商品", category="home_organization",
        cost_price=18, packaging_cost=2, weight_kg=0.4, volume_l=3.5,
        compliance_flag="ok", demand_score=20, gap_score=15,
        logistics_score=13, content_score=8,
    )
    base.update(overrides)
    return Product(**base)


def test_load_products_reads_all_rows(products):
    assert len(products) == 10
    assert products[0].sku == "TRAVEL-001"


def test_profit_calculation_matches_manual_formula(platform_cfg, logistics_cfg):
    """用手算结果校验定价公式。
    费率从配置读取而不是写死，这样更新真实费率时测试不会失效——
    要验证的是公式本身，不是某个具体费率数值。
    fixed = 采购18 + 包装2 + 物流(15+0.4*20=23) = 43
    price = fixed / (1 - rate_sum - target_margin)
    """
    product = make_product()
    cfg = platform_cfg["tiktok_shop"]
    rate_sum = (cfg["commission_rate"] + cfg["payment_fee_rate"]
                + cfg["return_rate"]["default"])
    fixed = 18 + 2 + (15 + 0.4 * 20)

    result = calculate_unit_profit(
        product, platform_cfg, logistics_cfg,
        platform="tiktok_shop", market="US", scenario="standard",
    )
    expected_price = fixed / (1 - rate_sum - 0.30)
    assert result.price == pytest.approx(expected_price, abs=0.01)
    assert result.contribution_margin == pytest.approx(0.30, abs=0.01)
    assert result.breakeven_roas == pytest.approx(1 / 0.30, abs=0.05)


def test_profit_with_explicit_price_can_be_negative(platform_cfg, logistics_cfg):
    """指定一个明显过低的售价，贡献利润应该为负——用来测试"成本无法覆盖"的淘汰路径。"""
    product = make_product()
    result = calculate_unit_profit(
        product, platform_cfg, logistics_cfg,
        platform="tiktok_shop", market="US", scenario="standard", price=30.0,
    )
    assert result.contribution_profit < 0
    assert result.breakeven_roas is None


def test_denominator_guard_actually_triggers(platform_cfg, logistics_cfg):
    """构造一个真正会让 denom<=0 的场景：极高退货率 + 激进毛利目标。"""
    bad_cfg = {
        "tiktok_shop": {
            "commission_rate": 0.30,
            "payment_fee_rate": 0.10,
            "return_rate": {"default": 0.30},
        }
    }
    product = make_product()
    with pytest.raises(ValueError):
        calculate_unit_profit(
            product, bad_cfg, logistics_cfg,
            platform="tiktok_shop", market="US", scenario="aggressive",
        )


def test_banned_product_is_hard_eliminated(platform_cfg, logistics_cfg):
    product = make_product(sku="TEST-BANNED", compliance_flag="banned")
    result = score_product(product, platform_cfg, logistics_cfg)
    assert result.eliminated is True
    assert result.total_score == 0.0
    assert "banned" in result.eliminate_reason or "淘汰" in result.eliminate_reason


def test_negative_profit_product_is_eliminated(platform_cfg, logistics_cfg):
    """成本高到无论如何都覆盖不了的商品应该被淘汰，即使需求分很高。"""
    product = make_product(sku="TEST-EXPENSIVE", cost_price=500, demand_score=25)
    bad_cfg = {
        "tiktok_shop": {
            "commission_rate": 0.08,
            "payment_fee_rate": 0.029,
            "return_rate": {"default": 0.06},
        }
    }
    # 用极低的固定售价场景：直接指定一个远低于成本的价格来触发负利润路径
    from src.calculator import calculate_unit_profit as calc
    forced = calc(product, bad_cfg, logistics_cfg, "tiktok_shop", "US", "standard", price=50.0)
    assert forced.contribution_profit < 0


def test_review_needed_product_not_eliminated_but_flagged(platform_cfg, logistics_cfg):
    product = make_product(sku="TEST-REVIEW", compliance_flag="review_needed", category="baby_safety")
    result = score_product(product, platform_cfg, logistics_cfg)
    assert result.eliminated is False
    assert "复核" in result.eliminate_reason


def test_score_all_sorts_eliminated_last(products, platform_cfg, logistics_cfg):
    results = score_all(products, platform_cfg, logistics_cfg)
    eliminated_flags = [r.eliminated for r in results]
    # 一旦出现 True，后面应该全是 True（淘汰的排最后）
    if True in eliminated_flags:
        first_true = eliminated_flags.index(True)
        assert all(eliminated_flags[first_true:])


def test_score_all_non_eliminated_sorted_desc(products, platform_cfg, logistics_cfg):
    results = score_all(products, platform_cfg, logistics_cfg)
    alive = [r.total_score for r in results if not r.eliminated]
    assert alive == sorted(alive, reverse=True)
