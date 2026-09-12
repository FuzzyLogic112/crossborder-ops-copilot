# -*- coding: utf-8 -*-
from pathlib import Path

from src.monitor import (compare_snapshots, build_daily_digest, rank_coverage,
                        coverage_warning, category_warning, snapshot_categories)

DATA = Path(__file__).parent.parent / "data"


def test_compare_snapshots_detects_price_drop_and_new_listing():
    changes, _ = compare_snapshots(
        str(DATA / "competitors_2026-09-10.csv"),
        str(DATA / "competitors_2026-09-11.csv"),
    )
    types_by_item = {}
    for c in changes:
        types_by_item.setdefault(c.item_id, set()).add(c.change_type)

    # TT-8841 从 12.99 降到 10.99，应该被识别为降价
    assert "price_drop" in types_by_item.get("TT-8841", set())
    # TT-9188 是新出现的商品
    assert "new_listing" in types_by_item.get("TT-9188", set())
    # AZ-5599 同时发生了促销变化（lightning_deal -> none）和评分变化，两者都应该被记录
    assert "promotion_change" in types_by_item.get("AZ-5599", set())
    assert "rating_change" in types_by_item.get("AZ-5599", set())


def test_no_changes_when_snapshots_identical():
    changes, _ = compare_snapshots(
        str(DATA / "competitors_2026-09-10.csv"),
        str(DATA / "competitors_2026-09-10.csv"),
    )
    assert changes == []


def test_daily_digest_contains_price_drop_suggestion():
    changes, _ = compare_snapshots(
        str(DATA / "competitors_2026-09-10.csv"),
        str(DATA / "competitors_2026-09-11.csv"),
    )
    digest = build_daily_digest(changes)
    assert "price_drop" in digest
    assert "贡献利润" in digest  # 应该引用场景 B 的建议话术


# ---------------------------------------------------------------------------
# 榜单覆盖范围防护 —— 真实踩过的坑：
# 拿 1 页(30条) 的快照去比 2 页(68条) 的快照，页数外的商品会被误判成「新品上榜」，
# 一次凭空多出 38 条假的 new_listing。
# ---------------------------------------------------------------------------

def _rows(n_start, n_end, price=10.0):
    return {
        "A%d" % i: {"platform": "amazon", "item_id": "A%d" % i, "title": "item %d" % i,
                    "price": price, "rating": 4.5, "review_count": 100,
                    "promotion": "unknown", "url": "u", "rank": i}
        for i in range(n_start, n_end + 1)
    }


def test_rank_coverage_reads_min_max():
    assert rank_coverage(_rows(1, 30)) == (1, 30)


def test_rank_coverage_none_when_no_rank_field():
    rows = {"A1": {"item_id": "A1", "price": 10}}
    assert rank_coverage(rows) is None


def test_coverage_warning_fires_on_page_count_mismatch():
    w = coverage_warning(_rows(1, 30), _rows(1, 68))
    assert w is not None
    assert "覆盖范围不同" in w


def test_coverage_warning_silent_when_same_range():
    assert coverage_warning(_rows(1, 30), _rows(1, 30)) is None


def _cat_rows(n_start, n_end, category, price=10.0):
    rows = _rows(n_start, n_end, price)
    for r in rows.values():
        r["category"] = category
    return rows


def test_snapshot_categories_collects_distinct_values():
    assert snapshot_categories(_cat_rows(1, 5, "kitchen")) == {"kitchen"}


def test_snapshot_categories_empty_when_field_missing():
    assert snapshot_categories(_rows(1, 5)) == set()


def test_category_warning_fires_on_different_categories():
    """实跑踩到的坑：kitchen(68条) 比 office-products(68条)，
    排名范围完全相同，覆盖度守卫抓不到，却产出 136 条垃圾变化。"""
    w = category_warning(_cat_rows(1, 68, "kitchen"),
                         _cat_rows(1, 68, "office-products"))
    assert w is not None
    assert "类目不同" in w
    assert "kitchen" in w and "office-products" in w


def test_category_warning_silent_when_same_category():
    assert category_warning(_cat_rows(1, 68, "kitchen"),
                            _cat_rows(1, 68, "kitchen")) is None


def test_coverage_warning_catches_category_mismatch_at_same_coverage():
    """行数与排名范围都相同、只有类目不同时，coverage_warning 也必须报警。"""
    w = coverage_warning(_cat_rows(1, 68, "kitchen"),
                         _cat_rows(1, 68, "office-products"))
    assert w is not None
    assert "类目不同" in w


def test_category_mismatch_takes_priority_over_page_mismatch():
    """两个问题同时存在时，先报类目——它更致命且无法靠限制排名范围补救。"""
    w = coverage_warning(_cat_rows(1, 30, "kitchen"),
                         _cat_rows(1, 68, "office-products"))
    assert "类目不同" in w


def test_no_category_field_falls_back_to_coverage_check():
    """旧快照没有 category 列时，不能因此漏掉页数守卫。"""
    w = coverage_warning(_rows(1, 30), _rows(1, 68))
    assert w is not None and "覆盖范围不同" in w


def test_mismatched_pages_do_not_produce_fake_new_listings():
    """这是防护的核心断言：多抓的那一页不应该产生任何 new_listing。"""
    from src.monitor import compare_snapshot_dicts
    changes = compare_snapshot_dicts(_rows(1, 30), _rows(1, 68))
    fake = [c for c in changes if c.change_type == "new_listing"]
    assert fake == [], "页数不同的快照不应产生 new_listing，实际产生 %d 条" % len(fake)


def test_real_price_change_still_detected_within_common_range():
    """防护不能把真实变化一起屏蔽掉：共同区间内的降价必须照常识别。"""
    from src.monitor import compare_snapshot_dicts
    before = _rows(1, 30, price=21.99)
    after = _rows(1, 68, price=17.99)
    changes = compare_snapshot_dicts(before, after)
    drops = [c for c in changes if c.change_type == "price_drop"]
    assert len(drops) == 30, "共同区间内 30 个商品的降价都应被识别，实际 %d" % len(drops)
