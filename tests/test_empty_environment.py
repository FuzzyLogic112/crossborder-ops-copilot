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
