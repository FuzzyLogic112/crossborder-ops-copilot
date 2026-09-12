# -*- coding: utf-8 -*-
"""供应商比价算法测试。不发任何网络请求。"""
import pytest

from src.sourcing import (
    SupplierQuote, applicable_tier_price, landed_cost, compare_quotes,
    compare_summary, load_quotes, save_quotes, _parse_tiers, _as_bool,
)


def q(**kw):
    base = dict(sku="SKU-1", platform="1688", supplier="A店", unit_price=40.0,
                quoted_date="2026-09-12")
    base.update(kw)
    return SupplierQuote(**base)


# ── 阶梯价 ──

def test_tier_price_picks_highest_eligible_break():
    quote = q(unit_price=45, tiers=[(100, 42.0), (500, 38.0), (1000, 35.0)])
    assert applicable_tier_price(quote, 50) == 42.0    # 不足最低档，用最低档
    assert applicable_tier_price(quote, 100) == 42.0
    assert applicable_tier_price(quote, 499) == 42.0
    assert applicable_tier_price(quote, 500) == 38.0
    assert applicable_tier_price(quote, 5000) == 35.0


def test_no_tiers_falls_back_to_unit_price():
    assert applicable_tier_price(q(unit_price=40), 999) == 40.0


def test_parse_tiers_accepts_mixed_separators():
    assert _parse_tiers("100:42.5;500:38") == [(100, 42.5), (500, 38.0)]
    assert _parse_tiers("100:42.5，500:38") == [(100, 42.5), (500, 38.0)]
    assert _parse_tiers("") == []
    assert _parse_tiers("垃圾数据") == []


# ── 到仓成本核心 ──

def test_landed_cost_amortizes_freight_and_oneoff_over_actual_qty():
    """运费和一次性费用要摊到实际采购量上，不是摊到 1 件上。"""
    r = landed_cost(q(unit_price=40, domestic_freight=200, mold_fee=300), order_qty=100)
    assert r.freight_per_unit == pytest.approx(2.0)      # 200/100
    assert r.oneoff_per_unit == pytest.approx(3.0)       # 300/100
    assert r.landed_unit_cost == pytest.approx(45.0)


def test_freight_included_means_zero_freight_per_unit():
    r = landed_cost(q(freight_included=True, domestic_freight=999), order_qty=10)
    assert r.freight_per_unit == 0.0


def test_moq_forces_larger_actual_qty_and_warns():
    r = landed_cost(q(moq=1000), order_qty=200)
    assert r.actual_qty == 1000
    assert r.moq_shortfall == 800
    assert any("MOQ" in w and "压货" in w for w in r.warnings)


def test_moq_satisfied_gives_no_shortfall():
    r = landed_cost(q(moq=100), order_qty=500)
    assert r.actual_qty == 500 and r.moq_shortfall == 0


def test_vat_added_only_when_invoice_needed_and_price_excludes_tax():
    excl = q(unit_price=100, tax_included=False)
    with_inv = landed_cost(excl, 10, need_invoice=True)
    no_inv = landed_cost(excl, 10, need_invoice=False)
    assert with_inv.taxed_price == pytest.approx(113.0)
    assert no_inv.taxed_price == pytest.approx(100.0)
    assert any("13%" in w for w in with_inv.warnings)
    assert any("出口退税" in w for w in no_inv.warnings)


def test_tax_included_price_never_gets_vat_added():
    incl = q(unit_price=100, tax_included=True)
    assert landed_cost(incl, 10, need_invoice=True).taxed_price == pytest.approx(100.0)


def test_missing_quote_date_warns():
    assert any("报价日期" in w for w in landed_cost(q(quoted_date=""), 10).warnings)


def test_long_lead_time_warns():
    assert any("交期" in w for w in landed_cost(q(lead_days=45), 10).warnings)


def test_freight_flagged_but_zero_warns():
    r = landed_cost(q(freight_included=False, domestic_freight=0), 10)
    assert any("低估" in w for w in r.warnings)


def test_invalid_inputs_raise():
    with pytest.raises(ValueError):
        landed_cost(q(), order_qty=0)
    with pytest.raises(ValueError):
        landed_cost(q(unit_price=-1), order_qty=10)
    with pytest.raises(ValueError):
        landed_cost(q(moq=0), order_qty=10)


# ── 比价与「标价陷阱」 ──

def test_cheapest_sticker_is_not_always_cheapest_landed():
    """这是整个模块存在的理由：标价最低的报价，到仓成本可能反而更高。
    A：¥38 不含税不含运，运费 3000，MOQ 1000
    B：¥42 含税含运，MOQ 100
    采购 200 件时，A 被迫买 1000 件且要加税加运费。
    """
    a = q(supplier="A店", unit_price=38, moq=1000, tax_included=False,
          freight_included=False, domestic_freight=3000)
    b = q(supplier="B店", platform="义乌购", unit_price=42, moq=100,
          tax_included=True, freight_included=True)

    results = compare_quotes([a, b], order_qty=200, need_invoice=True)
    assert results[0].quote.supplier == "B店", "到仓成本更低的应该胜出"

    s = compare_summary(results)
    assert s["winner"]["supplier"] == "B店"
    assert "sticker_trap" in s, "应该指出标价最低者不是最优"
    assert "38" in s["sticker_trap"] and "42" in s["sticker_trap"]


def test_compare_sorts_ascending_by_landed_cost():
    quotes = [q(supplier="贵", unit_price=60), q(supplier="便宜", unit_price=30),
              q(supplier="中", unit_price=45)]
    r = compare_quotes(quotes, order_qty=100)
    assert [x.quote.supplier for x in r] == ["便宜", "中", "贵"]


def test_compare_keeps_moq_unmet_quotes_rather_than_dropping_them():
    """MOQ 不满足的报价不能被工具悄悄剔除——它可能仍是最优选择，
    只是要压货，这个取舍应该留给人做。"""
    cheap_big_moq = q(supplier="大批量", unit_price=20, moq=5000)
    pricey_small = q(supplier="小批量", unit_price=50, moq=10)
    r = compare_quotes([cheap_big_moq, pricey_small], order_qty=100)
    assert len(r) == 2
    assert r[0].quote.supplier == "大批量"
    assert r[0].moq_shortfall == 4900


def test_summary_reports_gap_to_second():
    r = compare_quotes([q(supplier="A", unit_price=40), q(supplier="B", unit_price=44)], 100)
    s = compare_summary(r)
    assert s["gap_to_second"] == pytest.approx(4.0)
    assert s["gap_pct"] == pytest.approx(10.0)


def test_summary_on_empty_list():
    assert compare_summary([])["ok"] is False


# ── 读写 ──

def test_save_and_load_roundtrip(tmp_path):
    quotes = [q(supplier="A店", tiers=[(100, 42.0), (500, 38.0)], lead_days=15,
                tax_included=False, notes="打样7天")]
    f = tmp_path / "suppliers.csv"
    assert save_quotes(quotes, str(f)) == 1

    back = load_quotes(str(f))
    assert len(back) == 1
    got = back[0]
    assert got.supplier == "A店"
    assert got.tiers == [(100, 42.0), (500, 38.0)]
    assert got.lead_days == 15
    assert got.tax_included is False
    assert got.notes == "打样7天"


def test_load_missing_file_returns_empty(tmp_path):
    assert load_quotes(str(tmp_path / "nope.csv")) == []


def test_load_skips_rows_without_sku(tmp_path):
    f = tmp_path / "s.csv"
    f.write_text("sku,platform,supplier,unit_price\n,1688,X,10\nSKU-2,1688,Y,20\n",
                 encoding="utf-8")
    got = load_quotes(str(f))
    assert [g.sku for g in got] == ["SKU-2"]


def test_bool_parsing_accepts_chinese():
    assert _as_bool("含税") is True
    assert _as_bool("否") is False
    assert _as_bool("1") is True
    assert _as_bool("乱码", default=True) is True
