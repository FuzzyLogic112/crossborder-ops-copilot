# -*- coding: utf-8 -*-
"""cbops：跨境电商运营智能副驾驶 CLI 入口
用法示例：
  python cli.py score-products --input data/products.csv --output reports/product_scores.xlsx
  python cli.py profit --sku TRAVEL-001 --platform tiktok_shop --market US --scenario conservative
  python cli.py monitor --from data/competitors_2026-09-10.csv --to data/competitors_2026-09-11.csv
"""
import argparse
import os
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from src.calculator import load_products, load_yaml, score_all, calculate_unit_profit
from src.monitor import compare_snapshots, build_daily_digest
from src.ingest import ingest_csv, query_snapshot_dates

BASE = Path(__file__).parent
DATA = BASE / "data"
DB_PATH = str(DATA / "history.db")


def cmd_import_amzrank(args):
    from adapters.amzrank_adapter import convert, latest_amzrank_output

    src = args.input or latest_amzrank_output(args.amzrank_out)
    count = convert(src, args.output, args.collected_date, platform=args.platform)
    print("已转换 %d 条真实竞品数据" % count)
    print("  来源文件：%s" % src)
    print("  输出快照：%s" % args.output)
    print("  采集日期：%s（真实公开数据，非训练用虚构数据）" % args.collected_date)
    print("\n下一步：python cli.py ingest --input %s --snapshot-date %s"
          % (args.output, args.collected_date))


def cmd_ingest(args):
    count = ingest_csv(args.input, args.snapshot_date, DB_PATH)
    print("已导入 %d 条竞品记录 -> %s（快照日期 %s）" % (count, DB_PATH, args.snapshot_date))
    dates = query_snapshot_dates(DB_PATH)
    print("当前数据库中已有快照日期：%s" % ", ".join(dates))


def cmd_score_products(args):
    products = load_products(args.input)
    platform_cfg = load_yaml(str(DATA / "platforms.yaml"))
    logistics_cfg = load_yaml(str(DATA / "logistics_rates.yaml"))
    results = score_all(products, platform_cfg, logistics_cfg,
                         platform=args.platform, market=args.market, scenario=args.scenario)

    rows = []
    for r in results:
        rows.append({
            "SKU": r.sku, "名称": r.name, "总分": r.total_score,
            "需求稳定性(25)": r.demand_score, "竞争缺口(20)": r.gap_score,
            "贡献利润(20)": r.profit_score, "物流履约(15)": r.logistics_score,
            "合规风险(10)": r.compliance_score, "内容展示(10)": r.content_score,
            "是否淘汰": "是" if r.eliminated else "否", "淘汰/备注原因": r.eliminate_reason,
        })
    df = pd.DataFrame(rows)

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    if args.output.endswith(".xlsx"):
        df.to_excel(args.output, index=False)
    else:
        df.to_csv(args.output, index=False, encoding="utf-8-sig")

    print("已生成选品评分报告：%s" % args.output)
    print(df.to_string(index=False))


def cmd_profit(args):
    products = {p.sku: p for p in load_products(str(DATA / "products.csv"))}
    if args.sku not in products:
        print("找不到 SKU：%s" % args.sku, file=sys.stderr)
        sys.exit(1)

    platform_cfg = load_yaml(str(DATA / "platforms.yaml"))
    logistics_cfg = load_yaml(str(DATA / "logistics_rates.yaml"))
    product = products[args.sku]

    result = calculate_unit_profit(
        product, platform_cfg, logistics_cfg,
        platform=args.platform, market=args.market,
        scenario=args.scenario, price=args.price,
    )

    print("SKU: %s (%s)" % (result.sku, product.name))
    print("平台: %s  市场: %s  场景: %s" % (result.platform, result.market, args.scenario))
    print("-" * 44)
    print("采购成本      %8.2f 元" % result.cost_price)
    print("包装成本      %8.2f 元" % result.packaging_cost)
    print("头程物流      %8.2f 元" % result.logistics_cost)
    print("保本价        %8.2f 元" % result.breakeven_price)
    print("建议/指定定价  %8.2f 元" % result.price)
    print("平台佣金      %8.2f 元" % result.commission_fee)
    print("支付手续费    %8.2f 元" % result.payment_fee)
    print("退款准备金    %8.2f 元" % result.return_reserve)
    print("贡献利润      %8.2f 元" % result.contribution_profit)
    print("贡献利润率    %8.1f %%" % (result.contribution_margin * 100))
    if result.breakeven_roas:
        print("广告 Broke-even ROAS  %.2f" % result.breakeven_roas)
    else:
        print("广告 Broke-even ROAS  不适用（贡献利润为负）")


def cmd_monitor(args):
    changes, warning = compare_snapshots(args.from_snap, args.to_snap)
    digest = build_daily_digest(changes)
    if warning:
        # 终端没有 UI 帮忙加图标，这里自己加。
        # 约定：后端警告文本不带图标，呈现由调用方负责（与 src/sourcing.py 一致）。
        digest = "⚠ " + warning + "\n\n" + digest
    print(digest)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(digest, encoding="utf-8")
        print("\n已保存到：%s" % args.output)


def main():
    parser = argparse.ArgumentParser(prog="cbops", description="跨境电商运营智能副驾驶 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    pa = sub.add_parser("import-amzrank",
                        help="把 amzrank 抓到的真实亚马逊榜单数据转成标准竞品快照 CSV")
    pa.add_argument("--input", default=None, help="amzrank 导出的 xlsx；不填则取 --amzrank-out 里最新的")
    pa.add_argument("--amzrank-out",
                    default=os.environ.get("AMZRANK_OUT", str(DATA / "inbox")),
                    help="amzrank 输出目录。默认读 data/inbox/，也可用环境变量 AMZRANK_OUT 指定")
    pa.add_argument("--output", default=str(DATA / "real" / "competitors_real.csv"))
    pa.add_argument("--collected-date", required=True, help="采集日期，如 2026-09-11")
    pa.add_argument("--platform", default="amazon")
    pa.set_defaults(func=cmd_import_amzrank)

    p0 = sub.add_parser("ingest", help="把竞品快照 CSV 导入本地 SQLite 历史库")
    p0.add_argument("--input", required=True)
    p0.add_argument("--snapshot-date", required=True)
    p0.set_defaults(func=cmd_ingest)

    p1 = sub.add_parser("score-products", help="对候选商品做六维度评分与硬性淘汰")
    p1.add_argument("--input", default=str(DATA / "products.csv"))
    p1.add_argument("--output", default=str(BASE / "reports" / "product_scores.xlsx"))
    p1.add_argument("--platform", default="tiktok_shop")
    p1.add_argument("--market", default="US")
    p1.add_argument("--scenario", default="standard", choices=["conservative", "standard", "aggressive"])
    p1.set_defaults(func=cmd_score_products)

    p2 = sub.add_parser("profit", help="计算单个 SKU 的贡献利润与建议定价")
    p2.add_argument("--sku", required=True)
    p2.add_argument("--platform", default="tiktok_shop")
    p2.add_argument("--market", default="US")
    p2.add_argument("--scenario", default="standard", choices=["conservative", "standard", "aggressive"])
    p2.add_argument("--price", type=float, default=None, help="指定实际售价；不填则按 scenario 反推建议定价")
    p2.set_defaults(func=cmd_profit)

    p3 = sub.add_parser("monitor", help="比较两次竞品快照，生成变化日报")
    p3.add_argument("--from", dest="from_snap", required=True)
    p3.add_argument("--to", dest="to_snap", required=True)
    p3.add_argument("--output", default=None)
    p3.set_defaults(func=cmd_monitor)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
