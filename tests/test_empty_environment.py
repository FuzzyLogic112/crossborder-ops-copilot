# -*- coding: utf-8 -*-
"""全空环境（reset_data.py --all 之后）必须能正常启动。

实测踩到的坑：`--all` 把演示快照删掉后，build_dashboard.export_changes()
无条件去 compare 那两个文件，抛 FileNotFoundError；
serve.api_data() 把异常透传给面板，boot() 整个中断，
结果是**所有按钮都绑不上事件**——点抓取没反应、输入框没反应，
但界面看起来是正常的，非常难排查。

export_real_changes() 早就有 exists() 守卫，export_changes() 漏了。
"""
import csv

import pytest

import build_dashboard as bd
import serve


@pytest.fixture
def empty_data(tmp_path, monkeypatch):
    """把 DATA 指向一个只有配置、没有任何数据的空目录。"""
    data = tmp_path / "data"
    (data / "real").mkdir(parents=True)

    # 只留配置，不留任何快照/商品/数据库
    for name in ("platforms.yaml", "logistics_rates.yaml",
                 "sites.yaml", "category_aliases.yaml"):
        src = serve.DATA / name
        if src.exists():
            (data / name).write_bytes(src.read_bytes())

    # products.csv / suppliers.csv 只留表头，模拟 --all 之后的状态
    with (data / "products.csv").open("w", newline="", encoding="utf-8-sig") as f:
        csv.writer(f).writerow(serve.PRODUCT_COLUMNS)

    monkeypatch.setattr(serve, "DATA", data)
    monkeypatch.setattr(bd, "DATA", data)
    return data


def test_export_changes_returns_none_when_demo_snapshots_deleted(empty_data):
    """演示快照被删时必须返回 None，而不是抛 FileNotFoundError。"""
    assert bd.export_changes() is None


def test_api_data_survives_empty_environment(empty_data):
    """这是面板 boot() 的第一个请求 —— 它一抛异常，整个界面就废了。"""
    d = serve.api_data()
    assert d["mode"] == "local"
    assert d["products"] == []
    assert d["changes_demo"] is None
    assert d["competitors_real"] is None
    # 配置必须还在，否则定价和评分都没法用
    assert len(d["platforms"]) > 0
    assert len(d["logistics"]) > 0


def test_api_snapshots_empty_but_well_formed(empty_data):
    r = serve.api_snapshots()
    assert r["snapshots"] == []


def test_api_health_survives_empty_environment(empty_data):
    """health 是探测本地服务的接口，它挂了面板会退回只读演示模式。"""
    h = serve.api_health()
    assert h["ok"] is True
    assert len(h["category_choices"]) > 0      # 类目对照来自配置，不该被清掉


def test_api_products_empty_but_well_formed(empty_data):
    r = serve.api_products_get()
    assert r["rows"] == []
    assert r["columns"]                         # 列定义还在，否则前端渲染不出表头


# ── 候选品字段留空（选品工作台的正常中间状态）──

def _write_products(path, **overrides):
    import csv as _csv
    row = dict(sku="X1", name="Test Product", category="pet-supplies",
               cost_price="18", packaging_cost="2", weight_kg="0.4", volume_l="1",
               compliance_flag="ok", demand_score="20", gap_score="12",
               logistics_score="12", content_score="6", planned_price="120")
    row.update(overrides)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = _csv.DictWriter(f, fieldnames=serve.PRODUCT_COLUMNS)
        w.writeheader()
        w.writerow(row)


def test_load_products_tolerates_blank_numbers(tmp_path):
    """③ 选品工作台的流程就是「采购价先留空，等④比完价回填」。
    以前 float("") 直接抛 ValueError → api_data 500 → 面板 boot 中断，
    界面看着正常但所有按钮失灵。"""
    from src.calculator import load_products
    f = tmp_path / "products.csv"
    _write_products(f, cost_price="", weight_kg="")
    ps = load_products(str(f))
    assert len(ps) == 1
    assert set(ps[0].missing_fields) >= {"cost_price", "weight_kg"}


def test_blank_cost_is_not_treated_as_free(tmp_path):
    """采购价留空绝不能当 0 —— 那会让商品看起来免费、利润爆表、评分「通过」，
    比没有分数危险得多。必须判「无法测算」。"""
    from src.calculator import load_products, load_yaml, score_product
    f = tmp_path / "products.csv"
    _write_products(f, cost_price="")
    p = load_products(str(f))[0]
    pc = load_yaml(str(serve.DATA / "platforms.yaml"))
    lc = load_yaml(str(serve.DATA / "logistics_rates.yaml"))
    r = score_product(p, pc, lc)
    assert r.eliminated is True
    assert r.total_score == 0.0
    assert "无法测算" in r.eliminate_reason
    assert "采购价" in r.eliminate_reason


def test_complete_product_still_scores_normally(tmp_path):
    """补齐之后必须恢复正常打分，不能被上面的守卫误伤。"""
    from src.calculator import load_products, load_yaml, score_product
    f = tmp_path / "products.csv"
    _write_products(f)
    p = load_products(str(f))[0]
    pc = load_yaml(str(serve.DATA / "platforms.yaml"))
    lc = load_yaml(str(serve.DATA / "logistics_rates.yaml"))
    r = score_product(p, pc, lc)
    assert r.eliminated is False
    assert r.total_score > 0
