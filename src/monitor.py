# -*- coding: utf-8 -*-
"""竞品快照比对：只做标准化快照与变化解释，不做高频抓取。
数据来源边界：只读公开可见页面 / 官方 API / 已授权导出的 CSV。
遇到登录、验证码、访问限制或站点条款不允许的情况，停止自动访问，改用手工或授权导出。
"""
import csv
from dataclasses import dataclass
from typing import List, Dict


@dataclass
class SnapshotChange:
    item_id: str
    platform: str
    title: str
    change_type: str   # price_drop / price_rise / new_listing / delisted / promotion_change / rating_change
    detail: str


def load_snapshot(csv_path: str) -> Dict[str, dict]:
    rows = {}
    with open(csv_path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            rows[row["item_id"]] = row
    return rows


def compare_snapshots(from_path: str, to_path: str):
    """返回 (changes, warning)。warning 为 None 表示两份快照覆盖范围一致。"""
    before = load_snapshot(from_path)
    after = load_snapshot(to_path)
    return compare_snapshot_dicts(before, after), coverage_warning(before, after)


def rank_coverage(rows: Dict[str, dict]):
    """返回快照覆盖的榜单排名范围 (min, max)；没有 rank 字段时返回 None。"""
    ranks = []
    for r in rows.values():
        raw = r.get("rank")
        if raw in (None, ""):
            continue
        try:
            ranks.append(int(raw))
        except (TypeError, ValueError):
            continue
    return (min(ranks), max(ranks)) if ranks else None


def snapshot_categories(rows: Dict[str, dict]):
    """返回快照里出现过的类目集合；没有 category 字段时返回空集。"""
    return {str(r.get("category")).strip() for r in rows.values()
            if str(r.get("category") or "").strip()}


def category_warning(before: Dict[str, dict], after: Dict[str, dict]):
    """两份快照是**不同类目**时，对比结果全是垃圾——前一份的商品全被判成「下架」，
    后一份的全被判成「新品上榜」，而榜单名次范围却完全一致，覆盖度守卫抓不到。
    这是实跑踩到的坑：拿 kitchen(68条) 比 office-products(68条)，
    产出 68 条假 new_listing + 68 条假 delisted，且不触发任何告警。
    返回警告文本，或 None。
    """
    cb, ca = snapshot_categories(before), snapshot_categories(after)
    if not cb or not ca or cb == ca:
        return None
    return ("两份快照的类目不同（前：%s，后：%s）。不同类目之间没有可比性——"
            "前一份的商品会全部被判成「下架」，后一份会全部被判成「新品上榜」。"
            "请改用同一类目、不同日期的两份快照。"
            % ("/".join(sorted(cb)), "/".join(sorted(ca))))


def coverage_warning(before: Dict[str, dict], after: Dict[str, dict]):
    """两份快照抓取的页数不同时，多出来的商品会被误判成「新品上榜」。
    这是真实踩过的坑：拿 1 页(30条) 比 2 页(68条)，凭空多出 38 条假的 new_listing。
    类目不一致是另一种更隐蔽的情况（行数可能完全相同），一并在这里拦。
    返回警告文本，或 None。
    """
    # 类目不同优先报——它比页数不同更致命，且无法靠限制排名范围补救
    cat = category_warning(before, after)
    if cat:
        return cat
    cb, ca = rank_coverage(before), rank_coverage(after)
    if not cb or not ca:
        return None
    if cb[1] == ca[1]:
        return None
    return ("两份快照的榜单覆盖范围不同（前：第 %d-%d 名，后：第 %d-%d 名）。"
            "范围外的商品会被误判为「新品上榜」，请用相同页数、相同类目的快照对比。"
            % (cb[0], cb[1], ca[0], ca[1]))


def compare_snapshot_dicts(before: Dict[str, dict], after: Dict[str, dict],
                            restrict_to_common_coverage: bool = True) -> List[SnapshotChange]:
    """纯函数版本：直接传两份 {item_id: row} 字典。
    CLI 走 CSV 文件（see compare_snapshots），MCP 工具走 SQLite 历史库（see ingest.load_snapshot_from_db），
    比对逻辑只写一份，不重复维护。

    restrict_to_common_coverage：两份快照页数不同时，只在共同覆盖的排名区间内比对，
    避免把「对方那份多抓了一页」误判成几十条新品上榜。
    """
    if restrict_to_common_coverage:
        cb, ca = rank_coverage(before), rank_coverage(after)
        if cb and ca:
            cutoff = min(cb[1], ca[1])

            def within(rows):
                out = {}
                for k, v in rows.items():
                    raw = v.get("rank")
                    try:
                        if raw not in (None, "") and int(raw) <= cutoff:
                            out[k] = v
                    except (TypeError, ValueError):
                        continue
                return out

            before, after = within(before), within(after)

    changes: List[SnapshotChange] = []

    for item_id, new_row in after.items():
        old_row = before.get(item_id)
        if old_row is None:
            changes.append(SnapshotChange(
                item_id=item_id, platform=new_row["platform"], title=new_row["title"],
                change_type="new_listing",
                detail="新出现的竞品，售价 %s，促销：%s" % (new_row["price"], new_row.get("promotion", "none")),
            ))
            continue

        old_price = float(old_row["price"])
        new_price = float(new_row["price"])
        if abs(new_price - old_price) > 0.01:
            pct = (new_price - old_price) / old_price * 100
            changes.append(SnapshotChange(
                item_id=item_id, platform=new_row["platform"], title=new_row["title"],
                change_type="price_drop" if new_price < old_price else "price_rise",
                detail="价格 %.2f -> %.2f（%.1f%%），当前促销：%s"
                       % (old_price, new_price, pct, new_row.get("promotion", "none")),
            ))
        elif old_row.get("promotion") != new_row.get("promotion"):
            changes.append(SnapshotChange(
                item_id=item_id, platform=new_row["platform"], title=new_row["title"],
                change_type="promotion_change",
                detail="促销从「%s」变为「%s」，价格未变" % (old_row.get("promotion"), new_row.get("promotion")),
            ))

        old_rating = float(old_row.get("rating", 0) or 0)
        new_rating = float(new_row.get("rating", 0) or 0)
        if abs(new_rating - old_rating) >= 0.1:
            changes.append(SnapshotChange(
                item_id=item_id, platform=new_row["platform"], title=new_row["title"],
                change_type="rating_change",
                detail="评分 %.1f -> %.1f" % (old_rating, new_rating),
            ))

    for item_id, old_row in before.items():
        if item_id not in after:
            changes.append(SnapshotChange(
                item_id=item_id, platform=old_row["platform"], title=old_row["title"],
                change_type="delisted",
                detail="上一次快照中存在，本次未出现，可能已下架或链接失效",
            ))

    return changes


def build_daily_digest(changes: List[SnapshotChange]) -> str:
    """日报至少回答四个问题：谁变了/变了什么/可能原因是什么/建议观察还是立即处理。
    这里只做事实罗列和规则化建议，不替用户做最终判断——仅列价格评价数字不构成运营分析。
    """
    if not changes:
        return "本次快照对比未发现变化。"

    lines = ["# 竞品变化日报", ""]
    for c in changes:
        suggestion = {
            "price_drop": "建议：核算己方贡献利润后再决定是否跟价，参考场景 B 的三种测试方案",
            "price_rise": "建议：观察即可，通常不需要立即反应",
            "new_listing": "建议：观察 3-5 天流量与评价走势，判断是否需要纳入常规监控",
            "delisted": "建议：确认是否为自身产品的直接竞品消失，评估流量是否会转移",
            "promotion_change": "建议：观察对方转化率变化，暂不跟随",
            "rating_change": "建议：评分下滑较大时，检查同类目差评关键词是否值得借鉴",
        }.get(c.change_type, "建议：人工复核")
        lines.append("- 【%s】%s（%s）：%s\n  %s" % (c.change_type, c.title, c.platform, c.detail, suggestion))
    return "\n".join(lines)
