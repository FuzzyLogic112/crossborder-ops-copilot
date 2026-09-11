# -*- coding: utf-8 -*-
"""每日自动化工作流（手册第 6.2 节的落地版本）：

  09:00 导入公开或授权导出的新数据      -> ingest
  09:05 数据清洗并写入 SQLite 历史快照   -> ingest（同上，写入即完成清洗校验）
  09:10 比较竞品价格/评价/促销/关键词变化 -> compare
  09:15 计算利润、库存和异常阈值         -> score-products（本版先做利润部分）
  09:20 Agent 生成日报与待审批建议       -> 写入 reports/daily_*.md
  09:25 人工审核，仅人工在平台后台执行    -> 本脚本到此为止，不做任何写操作

用法：
  python automation/daily_workflow.py --input data/competitors_2026-09-11.csv --date 2026-09-11 --prev-date 2026-09-10

本脚本只读写本地文件和本地 SQLite，不发起任何网络请求，不修改任何真实店铺数据。
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.ingest import ingest_csv, load_snapshot_from_db, query_snapshot_dates
from src.monitor import compare_snapshot_dicts, build_daily_digest
from src.calculator import load_products, load_yaml, score_all

BASE = Path(__file__).parent.parent
DATA = BASE / "data"
DB_PATH = str(DATA / "history.db")


def run(input_csv: str, date: str, prev_date: str) -> str:
    # 09:00 + 09:05
    count = ingest_csv(input_csv, date, DB_PATH)
    log = ["## 自动化日报 %s" % date, "", "- 导入竞品记录 %d 条（快照日期 %s）" % (count, date)]

    # 09:10
    before = load_snapshot_from_db(DB_PATH, prev_date)
    after = load_snapshot_from_db(DB_PATH, date)
    if before:
        changes = compare_snapshot_dicts(before, after)
        log.append("- 对比 %s -> %s，发现 %d 处变化" % (prev_date, date, len(changes)))
        log.append("")
        log.append(build_daily_digest(changes))
    else:
        log.append("- 上一个快照日期 %s 在历史库中不存在，跳过比对，仅记录本次快照" % prev_date)
        log.append("  当前历史库已有日期：%s" % ", ".join(query_snapshot_dates(DB_PATH)))

    # 09:15
    products = load_products(str(DATA / "products.csv"))
    platform_cfg = load_yaml(str(DATA / "platforms.yaml"))
    logistics_cfg = load_yaml(str(DATA / "logistics_rates.yaml"))
    results = score_all(products, platform_cfg, logistics_cfg)
    alive = [r for r in results if not r.eliminated]
    eliminated = [r for r in results if r.eliminated]
    log.append("")
    log.append("### 选品评分摘要")
    log.append("- 存活 %d 个，淘汰 %d 个" % (len(alive), len(eliminated)))
    if alive:
        top = alive[0]
        log.append("- 当前分数最高：%s（%s），总分 %.2f" % (top.sku, top.name, top.total_score))

    # 09:20：本脚本只负责拼装事实性摘要，不调用任何 LLM 生成解释性文字，
    # 如需更完整的自然语言周报，把这份摘要喂给 mcp_server 的 build_weekly_report
    # 工具结果，交给人工在 Claude/Codex 对话里生成解释段落。
    log.append("")
    log.append("### 09:25 人工审核")
    log.append("- 本脚本不执行任何改价、上架、投放或发消息操作，以上内容仅供人工决策参考")

    return "\n".join(log)


def main():
    parser = argparse.ArgumentParser(description="每日自动化工作流（本地离线，无网络请求）")
    parser.add_argument("--input", required=True, help="今天新的竞品快照 CSV")
    parser.add_argument("--date", required=True, help="今天的快照日期，如 2026-09-11")
    parser.add_argument("--prev-date", required=True, help="用于对比的上一个快照日期")
    parser.add_argument("--output", default=None, help="不填则自动存到 reports/daily_<date>.md")
    args = parser.parse_args()

    output = args.output or str(BASE / "reports" / ("daily_%s.md" % args.date))
    report = run(args.input, args.date, args.prev_date)

    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text(report, encoding="utf-8")
    print(report)
    print("\n已保存到：%s" % output)


if __name__ == "__main__":
    main()
