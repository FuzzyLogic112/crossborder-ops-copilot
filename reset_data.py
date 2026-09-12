# -*- coding: utf-8 -*-
"""把项目重置成「干净可跑」状态 —— 清数据，不动配置。

清什么、留什么，是按「数据 vs 配置」分的：

清（采集与运行产物 + 你录入的业务数据）：
  data/history.db                 竞品快照数据库
  data/real/*.csv                 抓取到的真实快照
  reports/*                       日报、评分表
  docs/data.local.json            含真实数据的本地面板数据
  data/suppliers.csv              你录入的供应商报价（只留表头）
  data/products.csv               清掉你加的候选品，恢复成 10 个 TRAVEL 演示品
  data/*.backup-*                 历史备份

留（配置是设置，不是数据。清了工具就不能用了）：
  data/platforms.yaml             平台佣金与支付费率
  data/logistics_rates.yaml       各市场物流费率
  data/sites.yaml                 抓取站点
  data/competitors_2026-09-1*.csv 演示快照（git 跟踪，公开仓库的 demo 要靠它）

两种力度：
    默认      清采集数据，products.csv 恢复成 10 个 TRAVEL 演示品，保留演示快照
    --all     **连演示数据一起清**。products.csv 只留表头，演示快照也删。
              适合「我要一个完全空的环境，分得清哪些是我自己抓的」。

用法：
    python reset_data.py                  # 先看要删什么，不动手
    python reset_data.py --yes            # 执行（保留演示数据）
    python reset_data.py --all            # 预览「全清」会删什么
    python reset_data.py --all --yes --backup DIR   # 全清，并先备份
"""
import argparse
import csv
import shutil
import sqlite3
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
REPORTS = BASE / "reports"
DOCS = BASE / "docs"

PRODUCT_COLUMNS = ["sku", "name", "category", "cost_price", "packaging_cost",
                   "weight_kg", "volume_l", "compliance_flag", "demand_score",
                   "gap_score", "logistics_score", "content_score", "planned_price"]

# 重置后 products.csv 恢复成这 10 个演示品。
# 不留空是因为公开仓库的在线演示版要靠它，清空了 docs/data.json 就没内容。
DEMO_PRODUCTS = [
    ("TRAVEL-001", "旅行折叠收纳袋", "home_organization", 18, 2, 0.4, 3.5, "ok", 22, 16, 13, 8, 78),
    ("TRAVEL-002", "真空压缩收纳袋", "home_organization", 9, 1.5, 0.3, 2.8, "ok", 20, 10, 14, 6, 52),
    ("TRAVEL-003", "宠物伸缩牵引绳", "pet_supplies", 18, 2, 0.4, 1.2, "ok", 20, 15, 13, 7, 68),
    ("TRAVEL-004", "儿童安全座椅头枕", "baby_safety", 35, 3, 0.9, 6.0, "review_needed", 15, 12, 9, 5, 125),
    ("TRAVEL-005", "磁吸车载手机支架", "electronics_accessory", 12, 1, 0.2, 0.8, "ok", 18, 8, 14, 6, 55),
    ("TRAVEL-006", "美白牙贴", "beauty_health", 6, 0.8, 0.1, 0.3, "banned", 24, 18, 15, 9, 25),
    ("TRAVEL-007", "桌面收纳盒", "home_organization", 10, 1.2, 0.5, 4.0, "ok", 16, 9, 13, 7, 60),
    ("TRAVEL-008", "户外折叠椅", "outdoor", 28, 3.5, 2.1, 15.0, "ok", 17, 14, 7, 8, 72),
    ("TRAVEL-009", "防水手机袋", "electronics_accessory", 5, 0.6, 0.05, 0.2, "ok", 19, 11, 15, 5, 36),
    ("TRAVEL-010", "儿童退热贴", "baby_safety", 4, 0.5, 0.05, 0.15, "review_needed", 21, 10, 15, 4, 20),
]

SUPPLIER_COLUMNS = ["sku", "platform", "supplier", "unit_price", "moq",
                    "tier_qty", "tier_price", "tax_included", "freight_included",
                    "domestic_freight", "sample_fee", "mold_fee", "lead_days",
                    "quoted_date", "url", "notes"]


def collect(hard=False):
    """列出要删的东西。返回 (文件列表, 说明列表)。

    hard=True 时连演示快照也删 —— 混在一起时用户分不清哪份是自己抓的。
    """
    files, notes = [], []

    if hard:
        demo = sorted(DATA.glob("competitors_*.csv"))
        files += demo
        if demo:
            notes.append("演示快照：%d 个（--all 才删）" % len(demo))

    db = DATA / "history.db"
    if db.exists():
        try:
            c = sqlite3.connect(str(db))
            n = c.execute("SELECT COUNT(*) FROM competitor_snapshots").fetchone()[0]
            d = c.execute("SELECT COUNT(DISTINCT snapshot_date) "
                          "FROM competitor_snapshots").fetchone()[0]
            c.close()
            notes.append("history.db：%d 条记录 / %d 份快照" % (n, d))
        except sqlite3.Error:
            notes.append("history.db：存在（读不出统计）")
        files.append(db)

    real = sorted((DATA / "real").glob("*.csv")) if (DATA / "real").exists() else []
    files += real
    if real:
        notes.append("抓取快照：%d 个" % len(real))

    reps = [p for p in sorted(REPORTS.glob("*")) if p.is_file() and p.name != ".gitkeep"]
    files += reps
    if reps:
        notes.append("日报与报表：%d 个" % len(reps))

    local = DOCS / "data.local.json"
    if local.exists():
        files.append(local)
        notes.append("docs/data.local.json：含真实数据的本地面板数据")

    backups = (sorted(DATA.glob("*.backup-*")) + sorted(DATA.glob("*.backup-*.csv"))
               + sorted(DATA.glob("*.yaml.backup-*")))
    backups = sorted(set(backups))
    files += backups
    if backups:
        notes.append("历史备份文件：%d 个" % len(backups))

    return files, notes


def count_rows(path):
    if not path.exists():
        return 0
    with path.open(encoding="utf-8-sig") as f:
        return max(0, sum(1 for _ in f) - 1)


def reset_products(hard=False):
    """hard=True 时只留表头 —— 演示品混在自己抓的品里分不清，全清更省心。"""
    f = DATA / "products.csv"
    before = count_rows(f)
    rows = [] if hard else DEMO_PRODUCTS
    with f.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(PRODUCT_COLUMNS)
        w.writerows(rows)
    return before, len(rows)


def reset_suppliers():
    f = DATA / "suppliers.csv"
    before = count_rows(f)
    with f.open("w", newline="", encoding="utf-8-sig") as fh:
        csv.writer(fh).writerow(SUPPLIER_COLUMNS)
    return before, 0


def main():
    ap = argparse.ArgumentParser(description="重置项目数据（保留配置）")
    ap.add_argument("--yes", action="store_true", help="真的执行删除")
    ap.add_argument("--all", dest="hard", action="store_true",
                    help="连演示数据一起清，得到完全空的环境")
    ap.add_argument("--backup", metavar="DIR", help="执行前先把待删文件拷到 DIR")
    args = ap.parse_args()

    hard = args.hard
    files, notes = collect(hard)
    prod_rows = count_rows(DATA / "products.csv")
    supp_rows = count_rows(DATA / "suppliers.csv")

    print("模式：%s" % ("全清（--all）—— 演示数据也删，得到完全空的环境"
                        if hard else "常规 —— 保留演示数据"))
    print()
    print("将要清除：")
    for n in notes:
        print("  -", n)
    if hard:
        print("  - products.csv：%d 个候选品 → 只留表头" % prod_rows)
    else:
        print("  - products.csv：%d 个候选品 → 恢复成 %d 个 TRAVEL 演示品"
              % (prod_rows, len(DEMO_PRODUCTS)))
    print("  - suppliers.csv：%d 条报价 → 只留表头" % supp_rows)
    print()
    print("将要保留（配置是设置，不是数据）：")
    for name in ("platforms.yaml", "logistics_rates.yaml",
                 "sites.yaml", "category_aliases.yaml"):
        print("  -", "data/%s" % name)
    if not hard:
        for p in sorted(DATA.glob("competitors_2026-*.csv")):
            print("  - data/%s（演示快照；--all 会连它一起删）" % p.name)

    if not args.yes:
        print()
        print("这只是预览，什么都没动。真要执行加 --yes")
        if not hard:
            print("想要完全空的环境（演示数据也删）：加 --all")
        return 0

    if args.backup:
        bk = Path(args.backup)
        for p in files + [DATA / "products.csv", DATA / "suppliers.csv"]:
            if not p.exists():
                continue
            dest = bk / p.relative_to(BASE)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dest)
        print()
        print("已备份到 %s" % bk)

    print()
    removed = 0
    for p in files:
        try:
            p.unlink()
            removed += 1
        except OSError as e:
            print("删不掉 %s：%s" % (p.name, e), file=sys.stderr)
    print("已删除 %d 个文件" % removed)

    pb, pa = reset_products(hard)
    print("products.csv：%d → %d 行%s" % (pb, pa, "（只留表头）" if hard else "（演示品）"))
    sb, sa = reset_suppliers()
    print("suppliers.csv：%d → %d 行（只留表头）" % (sb, sa))

    print()
    print("重置完成。接下来：")
    print("  1. python build_dashboard.py     重建公开面板数据")
    print("  2. python serve.py --open        从「① 抓取数据」重新开始")
    if hard:
        print()
        print("现在环境是空的 —— 面板里出现的任何数据都是你自己抓的。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
