# -*- coding: utf-8 -*-
"""从竞品标题里解析出规格与中文提示。

为什么需要这个：抓到的标题是英文的，看着费劲；更要命的是**重量藏在标题里**
（`Cat Litter 40 lb`），而重量是跨境成本模型里权重最大的变量之一。

实际踩过的坑：40 磅（18 公斤）的猫砂，用「填入示例数值」按钮补重量时被填成
0.5 公斤，物流费从 ¥375 掉到 ¥25，于是评分显示「通过」——
但这个品按真实重量算是**必然亏损**的。标题里明明写着 40 lb。

所以这里做两件事：
1. 把标题里的重量/数量解析出来，用真实值代替瞎填
2. 给一个中文品类提示，方便快速扫一眼知道是什么

**这不是翻译。** 完整翻译需要 LLM，而本项目的边界是不调用任何 LLM
（见 README「不调用 LLM、不需要 API Key」）。要完整中文标题，
用面板里的「生成翻译 Prompt」按钮，粘到你自己的 AI 对话框跑。
"""
import re
from pathlib import Path
from typing import Optional

BASE = Path(__file__).parent.parent
DATA = BASE / "data"

# 单位换算到公斤。跨境物流按公斤计费，标题里却常写磅/盎司。
UNIT_TO_KG = {
    "lb": 0.45359237, "lbs": 0.45359237, "pound": 0.45359237, "pounds": 0.45359237,
    "oz": 0.028349523, "ounce": 0.028349523, "ounces": 0.028349523,
    "kg": 1.0, "kgs": 1.0, "kilogram": 1.0, "kilograms": 1.0,
    "g": 0.001, "gram": 0.001, "grams": 0.001,
}

# 匹配「数字 + 单位」。允许 40lb / 40 lb / 40-lb / 4.5 kg / 1,000 g
_WEIGHT_RE = re.compile(
    r"(?<![\w.])(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*[-\s]?\s*"
    r"(lbs?|pounds?|oz|ounces?|kgs?|kilograms?|grams?|g)(?![\w])",
    re.I,
)

# 「12 Count」「3 Pack」「Pack of 6」「2-Pack」
_COUNT_RE = re.compile(
    r"(?:(\d{1,4})\s*[-\s]?\s*(?:count|ct|pack|pk|pcs|pieces)"
    r"|pack\s+of\s+(\d{1,4}))",
    re.I,
)

# 液体体积，不换算成重量但值得提示（跨境液体多数受限）
_VOLUME_RE = re.compile(
    r"(?<![\w.])(\d{1,4}(?:\.\d+)?)\s*[-\s]?\s*(fl\s*oz|ml|l|liter|litre)(?![\w])",
    re.I,
)


def _load_terms():
    """品类词典从 data/title_terms.yaml 读，用户可自由增删。"""
    f = DATA / "title_terms.yaml"
    if not f.exists():
        return {}
    try:
        import yaml
        return yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def parse_weight_kg(title: str) -> Optional[float]:
    """从标题里解析重量，换算成公斤。解析不出返回 None。

    取**最大**的那个值：标题里可能同时出现「40 lb」和「16 oz per scoop」，
    我们要的是整件商品的重量，不是某个分量。宁可高估也不低估——
    低估重量会让亏损品看起来能赚钱。
    """
    best = None
    for num, unit in _WEIGHT_RE.findall(title or ""):
        try:
            v = float(num.replace(",", "")) * UNIT_TO_KG[unit.lower()]
        except (ValueError, KeyError):
            continue
        # 小于 1 克的多半是误匹配（比如型号里的数字后面跟着 g）
        if v < 0.001:
            continue
        if best is None or v > best:
            best = v
    return round(best, 3) if best is not None else None


def parse_count(title: str) -> Optional[int]:
    """解析件数：12 Count / 3 Pack / Pack of 6。"""
    m = _COUNT_RE.search(title or "")
    if not m:
        return None
    raw = m.group(1) or m.group(2)
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return None
    return n if 1 < n <= 9999 else None


def parse_volume(title: str):
    """解析液体体积，返回 (数值, 单位) 或 None。"""
    m = _VOLUME_RE.search(title or "")
    if not m:
        return None
    try:
        return float(m.group(1)), re.sub(r"\s+", " ", m.group(2).lower())
    except ValueError:
        return None


def guess_zh(title: str) -> Optional[str]:
    """按词典给一个中文品类提示。命中最长的词条。

    这是**提示不是翻译** —— 只认词典里有的词，认不出就返回 None，
    不猜、不编。词典在 data/title_terms.yaml，可自己加。
    """
    terms = _load_terms()
    if not terms:
        return None
    low = (title or "").lower()
    hit, hit_len = None, 0
    for en, zh in terms.items():
        e = str(en).lower()
        if e in low and len(e) > hit_len:
            hit, hit_len = zh, len(e)
    return hit


# 跨境重货阈值。超过这个重量，头程运费通常会吃掉大部分利润空间。
# 不是硬性规则，只是提示——具体还是要看客单价，模型会算。
HEAVY_KG = 2.0


def describe(title: str) -> dict:
    """把一条标题解析成结构化提示，给面板显示用。"""
    w = parse_weight_kg(title)
    n = parse_count(title)
    vol = parse_volume(title)
    bits = []
    if w is not None:
        bits.append("%.2fkg" % w if w < 10 else "%.1fkg" % w)
    if n:
        bits.append("%d 件装" % n)
    if vol:
        bits.append("%g%s" % vol)
    return {
        "zh": guess_zh(title),
        "weight_kg": w,
        "count": n,
        "spec": " / ".join(bits) or None,
        "heavy": bool(w is not None and w >= HEAVY_KG),
    }
