# -*- coding: utf-8 -*-
"""标题解析：从竞品标题里提取重量、件数、中文品类提示。

存在的理由是一个真实事故：
40 磅（18kg）的猫砂被「填入示例数值」按钮补成 0.5kg，
物流费从 ¥375 掉到 ¥25，评分显示「通过」——
而按真实重量它是必然亏损的。重量就写在标题里（`Cat Litter 40 lb`），
以前完全没被用上。
"""
import pytest

from src.titleparse import (HEAVY_KG, describe, guess_zh, parse_count,
                            parse_volume, parse_weight_kg)


# ── 重量解析 ──

def test_pounds_converted_to_kg():
    """事故原型：40 lb 必须被解析成 18kg 级别，不能漏掉。"""
    w = parse_weight_kg("Dr. Elsey's Ultra UnScented Clumping Clay Cat Litter 40 lb.")
    assert w is not None
    assert 18.0 < w < 18.2


def test_ounces_converted_to_kg():
    w = parse_weight_kg("Greenies Pill Pockets Large Size Dog Treats, 7.9 oz")
    assert w is not None
    assert 0.22 < w < 0.23


@pytest.mark.parametrize("title,low,high", [
    ("Protein Powder 2 kg", 1.99, 2.01),
    ("Coffee Beans 500 g", 0.49, 0.51),
    ("Dog Food 15 lbs", 6.7, 6.9),
    ("Snack Pack 12oz", 0.33, 0.35),          # 不带空格
    ("Rice 5-lb Bag", 2.2, 2.3),              # 连字符
    ("Bulk Sugar 1,000 g", 0.99, 1.01),       # 千分位逗号
])
def test_weight_formats(title, low, high):
    w = parse_weight_kg(title)
    assert w is not None and low < w < high


def test_takes_largest_weight_not_first():
    """标题里可能同时出现整件重量和分量。取大的——
    低估重量会让亏损品看起来能赚钱，宁可高估。"""
    w = parse_weight_kg("Cat Litter 40 lb, 16 oz per scoop")
    assert w > 18


def test_no_weight_returns_none():
    """解析不出就返回 None，不能编一个数出来。"""
    assert parse_weight_kg("Etekcity Food Kitchen Scale, Digital") is None
    assert parse_weight_kg("") is None
    assert parse_weight_kg(None) is None


def test_model_numbers_do_not_become_weights():
    """型号里的数字不能被当成重量。"""
    assert parse_weight_kg("Router AC1900 Dual Band") is None


# ── 件数解析 ──

@pytest.mark.parametrize("title,n", [
    ("Sharpie Permanent Markers, Fine Tip, 12 Count", 12),
    ("Earth Rated Dog Poop Bags, 270 Count", 270),
    ("Batteries AA 4-Pack", 4),
    ("Socks, Pack of 6", 6),
    ("Wipes 3 pk", 3),
])
def test_count_formats(title, n):
    assert parse_count(title) == n


def test_count_ignores_single():
    """「1 Pack」没有信息量，不显示。"""
    assert parse_count("Widget 1 Pack") is None


# ── 中文提示 ──

def test_zh_hint_from_dictionary():
    assert guess_zh("Dr. Elsey's Clumping Clay Cat Litter 40 lb") == "猫砂"
    assert guess_zh("Owala FreeSip Stainless Steel Water Bottle") == "水杯"


def test_zh_prefers_longest_match():
    """「cat litter」比「litter」更具体，必须优先。"""
    assert guess_zh("Premium Cat Litter Box Refill") in ("猫砂", "猫砂盆")


def test_zh_returns_none_when_unknown():
    """词典里没有就不显示，绝不瞎猜 —— 这是提示不是翻译。"""
    assert guess_zh("Quantum Flux Capacitor Mk II") is None


# ── 综合 ──

def test_describe_flags_heavy_item():
    """这是整个模块存在的理由：猫砂必须被标成重货。"""
    d = describe("Dr. Elsey's Ultra UnScented Clumping Clay Cat Litter 40 lb.")
    assert d["zh"] == "猫砂"
    assert d["heavy"] is True
    assert d["weight_kg"] > HEAVY_KG
    assert "kg" in d["spec"]


def test_describe_light_item_not_flagged():
    d = describe("Greenies Pill Pockets Dog Treats, 7.9 oz")
    assert d["heavy"] is False


def test_describe_handles_missing_everything():
    d = describe("Some Product With No Specs")
    assert d["weight_kg"] is None
    assert d["heavy"] is False
    assert d["spec"] is None


def test_volume_parsed_separately_from_weight():
    """液体体积不能被当成重量。"""
    assert parse_volume("Shampoo 16 fl oz") == (16.0, "fl oz")
    assert parse_volume("Juice 1.5 L") == (1.5, "l")
