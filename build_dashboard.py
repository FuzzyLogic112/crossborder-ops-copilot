# -*- coding: utf-8 -*-
"""把项目数据导出成面板用的单个 JSON，供 docs/index.html 读取。

用法：
  python build_dashboard.py                # 只用虚构演示数据（可公开推 GitHub Pages）
  python build_dashboard.py --with-real     # 额外嵌入真实抓取数据（仅本地/面试用，勿提交）

为什么分两种模式：真实抓取的第三方平台数据不进公开仓库（见 .gitignore），
但本地演示时用真实数据说服力更强。页面会显式标注当前是哪种模式。
"""
import argparse
import csv
import json
import sys
from pathlib import Path

BASE = Path(__file__).parent
DATA = BASE / "data"
DOCS = BASE / "docs"

sys.path.insert(0, str(BASE))
from src.calculator import load_products, load_yaml, score_all          # noqa: E402
from src.monitor import compare_snapshots                                # noqa: E402


def export_products():
    rows = []
    for p in load_products(str(DATA / "products.csv")):
        rows.append({
            "sku": p.sku, "name": p.name, "category": p.category,
            "cost_price": p.cost_price, "packaging_cost": p.packaging_cost,
            "weight_kg": p.weight_kg, "volume_l": p.volume_l,
            "compliance_flag": p.compliance_flag,
            "demand_score": p.demand_score, "gap_score": p.gap_score,
            "logistics_score": p.logistics_score, "content_score": p.content_score,
            "planned_price": p.planned_price,
        })
    return rows


def export_scores(platform_cfg, logistics_cfg):
    products = load_products(str(DATA / "products.csv"))
    out = {}
    for scenario in ("conservative", "standard", "aggressive"):
        results = score_all(products, platform_cfg, logistics_cfg,
                            platform="tiktok_shop", market="US", scenario=scenario)
        out[scenario] = [{
            "sku": r.sku, "name": r.name, "total": r.total_score,
            "demand": r.demand_score, "gap": r.gap_score, "profit": r.profit_score,
            "logistics": r.logistics_score, "compliance": r.compliance_score,
            "content": r.content_score,
            "eliminated": r.eliminated, "reason": r.eliminate_reason,
        } for r in results]
    return out


def read_csv_rows(path, limit=None):
    if not Path(path).exists():
        return []
    with open(path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    return rows[:limit] if limit else rows


def export_changes():
    """演示用的变化日报（虚构数据，两份快照覆盖范围一致）。"""
    changes, warning = compare_snapshots(
        str(DATA / "competitors_2026-09-10.csv"),
        str(DATA / "competitors_2026-09-11.csv"),
    )
    return {
        "warning": warning,
        "items": [{
            "item_id": c.item_id, "platform": c.platform,
            "title": c.title, "type": c.change_type, "detail": c.detail,
        } for c in changes],
    }


def export_real_changes():
    """真实数据的变化日报——保留覆盖范围警告，那是「发现并修正误判」的物证。"""
    a = DATA / "real" / "competitors_real_0308.csv"
    b = DATA / "real" / "competitors_real.csv"
    if not (a.exists() and b.exists()):
        return None
    changes, warning = compare_snapshots(str(a), str(b))
    return {
        "warning": warning,
        "items": [{
            "item_id": c.item_id, "platform": c.platform,
            "title": c.title, "type": c.change_type, "detail": c.detail,
        } for c in changes],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-real", action="store_true",
                    help="嵌入 data/real/ 下的真实抓取数据（仅本地用，不要提交）")
    args = ap.parse_args()

    platform_cfg = load_yaml(str(DATA / "platforms.yaml"))
    logistics_cfg = load_yaml(str(DATA / "logistics_rates.yaml"))

    payload = {
        "mode": "real" if args.with_real else "demo",
        "platforms": platform_cfg,
        "logistics": logistics_cfg,
        "margin_scenarios": {"conservative": 0.20, "standard": 0.30, "aggressive": 0.40},
        "products": export_products(),
        "scores": export_scores(platform_cfg, logistics_cfg),
        "competitors_demo": read_csv_rows(DATA / "competitors_2026-09-11.csv"),
        "changes_demo": export_changes(),
        "competitors_real": None,
        "changes_real": None,
    }

    if args.with_real:
        real = read_csv_rows(DATA / "real" / "competitors_real.csv")
        payload["competitors_real"] = real
        payload["changes_real"] = export_real_changes()
        if not real:
            print("⚠ 没找到 data/real/competitors_real.csv，真实数据部分为空")

    DOCS.mkdir(exist_ok=True)
    # 真实数据写 data.local.json（已 gitignore，不会进公开仓库）；
    # 演示数据写 data.json（可公开）。页面优先读 local，读不到自动回退到 data.json。
    # 这样本地看到真实数据、GitHub Pages 只有演示数据，不需要手动切换，也不会误提交。
    out = DOCS / ("data.local.json" if args.with_real else "data.json")
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    size_kb = out.stat().st_size / 1024
    print("已生成 %s（%.1f KB，模式：%s）" % (out.name, size_kb, payload["mode"]))
    if args.with_real:
        print("  ⚠ 本文件含真实抓取数据，已在 .gitignore 中，不会提交到公开仓库")
        if not (DOCS / "data.json").exists():
            print("  ⚠ 还没有可公开的 data.json —— 请另跑一次不带 --with-real 的命令")
    print("  商品 %d 个 | 演示竞品 %d 条 | 真实竞品 %d 条"
          % (len(payload["products"]), len(payload["competitors_demo"]),
             len(payload["competitors_real"] or [])))


if __name__ == "__main__":
    main()
