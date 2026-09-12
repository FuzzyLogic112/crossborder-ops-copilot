# -*- coding: utf-8 -*-
"""类目中文名 → slug 解析。

为什么需要这一层：Amazon 的榜单 slug 是固定标识符，不是英文译名，
所以不能靠机器翻译生成，只能查实测确认过的对照表。
下面几个都是实跑验证出来的反例，翻译一定会做错：
    家居厨房 = kitchen        （不是 home-kitchen）
    运动户外 = sporting-goods （sports 实测是空的）
    电脑     = pc             （computers 实测是空的）
    工具家装 = hi             （tools 实测是空的）
"""
import pytest

import serve


def test_chinese_name_resolves_to_slug():
    slug, info = serve.resolve_category("家居厨房", "us")
    assert slug == "kitchen"
    assert info["zh"] == "家居厨房"
    assert info["matched_by"] == "alias"


def test_translation_would_get_these_wrong():
    """翻译派一定做错的几个 —— 表里必须是实测值。"""
    assert serve.resolve_category("运动户外", "us")[0] == "sporting-goods"
    assert serve.resolve_category("电脑", "us")[0] == "pc"
    assert serve.resolve_category("工具家装", "us")[0] == "hi"
    assert serve.resolve_category("玩具", "us")[0] == "toys-and-games"


def test_synonym_normalises_to_canonical_name():
    slug, info = serve.resolve_category("厨房", "us")
    assert slug == "kitchen"
    assert info["matched_by"] == "synonym"
    assert info["zh"] == "家居厨房"


def test_plain_slug_passes_through_untouched():
    """本来就填 slug 的，不能被改写。"""
    slug, info = serve.resolve_category("office-products", "us")
    assert slug == "office-products"
    assert info["matched_by"] == "slug"
    assert info["zh"] is None


def test_slug_input_is_lowercased():
    assert serve.resolve_category("Office-Products", "us")[0] == "office-products"


def test_verified_flag_reflects_real_测试结果():
    assert serve.resolve_category("kitchen", "us")[1]["verified"] is True


def test_known_bad_slug_warns_before_scraping():
    """toys 在美国站实测是空的 —— 抓之前就该警告，别让用户白等一轮。"""
    slug, info = serve.resolve_category("toys", "us")
    assert slug == "toys"
    assert info["known_bad"] is True
    assert info["warning"] and "抓不到" in info["warning"]


def test_same_chinese_name_can_be_bad_on_another_site():
    """玩具在美国站可用、英国站实测抓不到 —— 验证状态必须按站点算。"""
    _, us = serve.resolve_category("玩具", "us")
    _, uk = serve.resolve_category("玩具", "uk")
    assert us["verified"] is True and us["known_bad"] is False
    assert uk["known_bad"] is True


def test_unverified_slug_still_allowed_but_warned():
    """没验过不等于不能用，只是要提醒。"""
    slug, info = serve.resolve_category("some-new-category", "us")
    assert slug == "some-new-category"
    assert info["verified"] is False
    assert info["known_bad"] is False
    assert "没有实测验证过" in info["warning"]


def test_unknown_chinese_name_raises_actionable_error():
    with pytest.raises(ValueError) as e:
        serve.resolve_category("蹦极绳", "us")
    msg = str(e.value)
    assert "category_aliases.yaml" in msg      # 告诉用户去哪加
    assert "gp/bestsellers" in msg             # 告诉用户怎么查真实 slug
    assert "家居厨房" in msg                    # 列出已有的中文名


def test_empty_input_rejected():
    with pytest.raises(ValueError):
        serve.resolve_category("   ", "us")


def test_whitespace_is_trimmed():
    assert serve.resolve_category("  家居厨房  ", "us")[0] == "kitchen"


def test_category_choices_are_sorted_verified_first():
    choices = serve.category_choices("us")
    assert choices, "美国站应该有对照项"
    verified_flags = [c["verified"] for c in choices]
    # 已验证的必须排在前面
    assert verified_flags == sorted(verified_flags, reverse=True)
    assert all("zh" in c and "slug" in c for c in choices)


def test_scrape_rejects_unknown_chinese_before_launching_job():
    """解析失败必须在起任务之前就拦住，不能白开一个抓取进程。"""
    with pytest.raises(ValueError):
        serve.api_scrape({"site": "us", "category": "不存在的类目xyz", "pages": 1})


def test_resolve_endpoint_reports_failure_without_error_field():
    """失败时不能用 error 字段 —— 前端 api() 见到 error 会抛异常，
    消息被吞掉，界面只剩一片空白（实测踩到过）。"""
    r = serve.api_resolve_category({"site": "us", "category": "蹦极绳"})
    assert r["ok"] is False
    assert "error" not in r
    assert "category_aliases.yaml" in r["reason"]


def test_resolve_endpoint_success_shape():
    r = serve.api_resolve_category({"site": "us", "category": "家居厨房"})
    assert r["ok"] is True
    assert r["slug"] == "kitchen"
    assert r["zh"] == "家居厨房"
    assert r["verified"] is True
