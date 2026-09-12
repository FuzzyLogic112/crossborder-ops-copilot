# -*- coding: utf-8 -*-
"""供应商报价比价 —— 把不同平台、不同条件的报价归一化成「到仓成本单价」后再比。

为什么不能直接比单价：
    ¥38/件 · MOQ 1000 · 不含税 · 不含运
    ¥42/件 · MOQ 100  · 含税   · 含运
这两个报价直接比大小是错的。你只要 200 件时，前者根本买不到；
就算买得到，加上 13% 税和国内运费后，也可能比后者贵。

真正可比的数字是：**在你实际采购量下，货到你仓库时的单件成本。**

    到仓成本单价 = 适用阶梯单价（按需含税）+ （国内运费 + 打样费 + 模具费）÷ 实际采购量

本模块不抓取任何供应商平台 —— 实测 1688 / Alibaba / 义乌购 / DHgate 的价格
全部在登录墙或反爬后面，且项目边界规定遇到登录墙即停止自动访问。
报价由人工录入或从平台自己的导出文件导入。
"""
import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

# 常见供货渠道。这只是下拉建议，不限制录入。
KNOWN_PLATFORMS = [
    "1688", "义乌购", "阿里巴巴国际站", "中国制造网", "DHgate",
    "拼多多", "淘宝", "速卖通", "线下档口", "展会", "工厂直联", "其他",
]

# 中国增值税一般税率。仅在「报价不含税且你需要专票」时计入。
DEFAULT_VAT_RATE = 0.13


@dataclass
class SupplierQuote:
    sku: str                        # 对应 products.csv 里的 SKU
    platform: str                   # 从哪个平台拿到的报价
    supplier: str                   # 供应商/店铺名
    unit_price: float               # 基础单价（该平台标价口径）
    moq: int = 1                    # 最小起订量
    tax_included: bool = True       # 单价是否已含税
    freight_included: bool = False  # 单价是否已含国内运费（到你仓库）
    domestic_freight: float = 0.0   # 国内运费总额（不是单件）
    sample_fee: float = 0.0         # 打样费（一次性）
    mold_fee: float = 0.0           # 模具/开版费（一次性）
    lead_days: Optional[int] = None # 交期（天）
    tiers: List[Tuple[int, float]] = field(default_factory=list)  # 阶梯价 [(起订量, 单价)]
    url: str = ""
    quoted_date: str = ""           # 报价日期 —— 报价会变，没有日期的报价不可信
    notes: str = ""


@dataclass
class LandedCost:
    quote: SupplierQuote
    order_qty: int                  # 你想采购的量
    actual_qty: int                 # 实际必须采购的量（受 MOQ 约束）
    tier_price: float               # 该量级适用的阶梯单价
    taxed_price: float              # 计税后单价
    freight_per_unit: float
    oneoff_per_unit: float
    landed_unit_cost: float         # ⭐ 最终可比的数字
    moq_shortfall: int              # 因 MOQ 被迫多买的件数（0 表示刚好或超过）
    warnings: List[str] = field(default_factory=list)


def applicable_tier_price(quote: SupplierQuote, qty: int) -> float:
    """阶梯价里取适用单价：取「起订量 <= qty」中起订量最大的那一档。
    没有阶梯价时用基础单价。
    """
    if not quote.tiers:
        return quote.unit_price
    eligible = [(m, p) for m, p in sorted(quote.tiers) if m <= qty]
    if not eligible:
        # qty 比最低那档还小 —— 用最低档单价（通常也是最贵的那档）
        return sorted(quote.tiers)[0][1]
    return eligible[-1][1]


def landed_cost(quote: SupplierQuote, order_qty: int,
                need_invoice: bool = False,
                vat_rate: float = DEFAULT_VAT_RATE) -> LandedCost:
    """算到仓成本单价。

    need_invoice：你是否需要增值税专用发票（做出口退税通常需要）。
        - 需要 + 报价不含税 → 要把税加上，否则低估成本
        - 不需要 → 不含税报价按原价用（很多小卖家就是这么买的）
    """
    if order_qty <= 0:
        raise ValueError("采购量必须大于 0")
    if quote.unit_price < 0:
        raise ValueError("单价不能为负")
    if quote.moq < 1:
        raise ValueError("MOQ 必须 >= 1")

    warnings: List[str] = []

    # MOQ 约束：想买 200 但人家起订 1000，你实际得买 1000
    actual_qty = max(order_qty, quote.moq)
    shortfall = max(0, quote.moq - order_qty)
    if shortfall:
        warnings.append(
            "MOQ %d 高于你的采购量 %d —— 实际要买 %d 件，多出的 %d 件是压货风险"
            % (quote.moq, order_qty, actual_qty, shortfall))

    tier_price = applicable_tier_price(quote, actual_qty)

    taxed = tier_price
    if need_invoice and not quote.tax_included:
        taxed = tier_price * (1 + vat_rate)
        warnings.append("报价不含税，按需要专票计入 %.0f%% 增值税" % (vat_rate * 100))
    elif not need_invoice and not quote.tax_included:
        warnings.append("报价不含税，当前按「不需要专票」处理 —— 若要出口退税需重算")

    freight_per_unit = 0.0
    if not quote.freight_included:
        freight_per_unit = quote.domestic_freight / actual_qty
        if quote.domestic_freight == 0:
            warnings.append("标为不含运费但国内运费填 0 —— 到仓成本可能被低估")

    oneoff_per_unit = (quote.sample_fee + quote.mold_fee) / actual_qty

    landed = taxed + freight_per_unit + oneoff_per_unit

    if not quote.quoted_date:
        warnings.append("没有报价日期 —— 报价会变，无日期的报价不能作为决策依据")
    if quote.lead_days is not None and quote.lead_days > 30:
        warnings.append("交期 %d 天偏长，注意断货与资金占用风险" % quote.lead_days)

    return LandedCost(
        quote=quote, order_qty=order_qty, actual_qty=actual_qty,
        tier_price=round(tier_price, 4), taxed_price=round(taxed, 4),
        freight_per_unit=round(freight_per_unit, 4),
        oneoff_per_unit=round(oneoff_per_unit, 4),
        landed_unit_cost=round(landed, 4),
        moq_shortfall=shortfall, warnings=warnings,
    )


def compare_quotes(quotes: List[SupplierQuote], order_qty: int,
                   need_invoice: bool = False,
                   vat_rate: float = DEFAULT_VAT_RATE) -> List[LandedCost]:
    """按到仓成本单价从低到高排序。
    MOQ 不满足的报价不剔除 —— 它们可能仍是最优选择（只是要压货），
    由人看着警告自己决定，工具不替人砍掉选项。
    """
    results = [landed_cost(q, order_qty, need_invoice, vat_rate) for q in quotes]
    results.sort(key=lambda r: (r.landed_unit_cost, r.actual_qty))
    return results


def compare_summary(results: List[LandedCost]) -> dict:
    """给比价结果一句话结论 + 关键差异。"""
    if not results:
        return {"ok": False, "reason": "没有可比的报价"}

    best = results[0]
    out = {
        "ok": True,
        "winner": {
            "platform": best.quote.platform,
            "supplier": best.quote.supplier,
            "landed_unit_cost": best.landed_unit_cost,
            "actual_qty": best.actual_qty,
        },
        "count": len(results),
    }

    if len(results) > 1:
        second = results[1]
        gap = second.landed_unit_cost - best.landed_unit_cost
        out["gap_to_second"] = round(gap, 4)
        out["gap_pct"] = round(gap / best.landed_unit_cost * 100, 2) if best.landed_unit_cost else None

        # 标价最低的那个，未必是到仓最低的 —— 这是本模块存在的理由
        cheapest_sticker = min(results, key=lambda r: r.quote.unit_price)
        if cheapest_sticker is not best:
            out["sticker_trap"] = (
                "%s 的%s标价最低（¥%.2f/件），但到仓成本 ¥%.2f 反而更高；"
                "%s 的%s标价 ¥%.2f、到仓 ¥%.2f 才是更优选择。"
                "直接比标价会选错。"
                % (cheapest_sticker.quote.platform, cheapest_sticker.quote.supplier,
                   cheapest_sticker.quote.unit_price, cheapest_sticker.landed_unit_cost,
                   best.quote.platform, best.quote.supplier,
                   best.quote.unit_price, best.landed_unit_cost))

    forced = [r for r in results if r.moq_shortfall]
    if forced:
        out["moq_note"] = "%d 个报价的 MOQ 高于你的采购量，选它们意味着压货" % len(forced)

    return out


# ── 报价文件读写 ──

QUOTE_COLUMNS = ["sku", "platform", "supplier", "unit_price", "moq",
                 "tax_included", "freight_included", "domestic_freight",
                 "sample_fee", "mold_fee", "lead_days", "tiers",
                 "url", "quoted_date", "notes"]


def _parse_tiers(raw: str) -> List[Tuple[int, float]]:
    """阶梯价格式：'100:42.5;500:38;1000:35'"""
    out = []
    for part in (raw or "").replace("，", ";").replace(",", ";").split(";"):
        part = part.strip()
        if not part or ":" not in part:
            continue
        q, p = part.split(":", 1)
        try:
            out.append((int(float(q.strip())), float(p.strip())))
        except ValueError:
            continue
    return sorted(out)


def _fmt_tiers(tiers: List[Tuple[int, float]]) -> str:
    return ";".join("%d:%s" % (q, p) for q, p in sorted(tiers))


def _as_bool(v, default=False) -> bool:
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("1", "true", "yes", "y", "是", "含", "含税", "含运"):
        return True
    if s in ("0", "false", "no", "n", "否", "不含"):
        return False
    return default


def _as_float(v, default=0.0) -> float:
    try:
        return float(str(v).strip()) if str(v).strip() != "" else default
    except (TypeError, ValueError):
        return default


def load_quotes(path: str) -> List[SupplierQuote]:
    p = Path(path)
    if not p.exists():
        return []
    out = []
    with p.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if not (row.get("sku") or "").strip():
                continue
            lead = row.get("lead_days")
            out.append(SupplierQuote(
                sku=row["sku"].strip(),
                platform=(row.get("platform") or "").strip() or "其他",
                supplier=(row.get("supplier") or "").strip(),
                unit_price=_as_float(row.get("unit_price")),
                moq=max(1, int(_as_float(row.get("moq"), 1))),
                tax_included=_as_bool(row.get("tax_included"), True),
                freight_included=_as_bool(row.get("freight_included"), False),
                domestic_freight=_as_float(row.get("domestic_freight")),
                sample_fee=_as_float(row.get("sample_fee")),
                mold_fee=_as_float(row.get("mold_fee")),
                lead_days=int(_as_float(lead)) if str(lead or "").strip() else None,
                tiers=_parse_tiers(row.get("tiers")),
                url=(row.get("url") or "").strip(),
                quoted_date=(row.get("quoted_date") or "").strip(),
                notes=(row.get("notes") or "").strip(),
            ))
    return out


def save_quotes(quotes: List[SupplierQuote], path: str) -> int:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=QUOTE_COLUMNS)
        w.writeheader()
        for q in quotes:
            w.writerow({
                "sku": q.sku, "platform": q.platform, "supplier": q.supplier,
                "unit_price": q.unit_price, "moq": q.moq,
                "tax_included": int(q.tax_included),
                "freight_included": int(q.freight_included),
                "domestic_freight": q.domestic_freight,
                "sample_fee": q.sample_fee, "mold_fee": q.mold_fee,
                "lead_days": q.lead_days if q.lead_days is not None else "",
                "tiers": _fmt_tiers(q.tiers),
                "url": q.url, "quoted_date": q.quoted_date, "notes": q.notes,
            })
    return len(quotes)
