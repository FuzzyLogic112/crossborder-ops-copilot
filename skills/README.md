# 跨境运营 Skills

四个 skill，覆盖运营日常最高频的四件事。**每个 skill 固化的是判断标准，不是自动化动作** ——
这也是它对没有运营经验的人有用的原因：不用先有经验才能按流程做对。

| Skill | 什么时候用 | 解决的新手痛点 |
|---|---|---|
| [`product-screening`](product-screening/SKILL.md) | 「这个品能做吗」 | 不知道该看什么，看到榜单卖得好就想跟 |
| [`price-response`](price-response/SKILL.md) | 「竞品降价了跟不跟」 | 看到降价就跟，跟到亏损线以下 |
| [`listing`](listing/SKILL.md) | 「写产品文案」 | 三个平台各写一套，卖点不统一 |
| [`listing-visuals`](listing-visuals/SKILL.md) | 「做产品图」 | 主图做成海报，违规被下架 |

## 四个 skill 怎么串

```
product-screening  →  这个品能做吗
        ↓ 能做
   （去问供应商报价 → cbops compare-suppliers）
        ↓ 成本确定
listing + listing-visuals  →  文案与图，准备上架
        ↓ 上架后
price-response  →  竞品调价了怎么应对
```

## 共同的设计原则

**1. 硬性淘汰优先于打分。**
合规红线、重货、贡献利润为负 —— 这三条是一票否决，不是扣分。
需求分 24/25 的品因为合规 banned 照样归零。

**2. 缺数据就说缺数据。**
不把空值当 0。采购价留空当 0 会让商品看起来免费、利润爆表、评分通过 ——
**没有结论比错误的结论安全**。

**3. 算得清的算清，算不清的标出来。**
贡献利润是算的；需求、缺口、内容可做性是人判断的。
工具的价值不是替你判断，是**让能算清的那一项不可能拍脑袋**。

**4. 不碰写操作。**
不改价、不上架、不投放、不发消息。这些永远需要人在平台后台确认执行。

## 怎么装

**Claude Code**：把整个 skill 目录拷到 `~/.claude/skills/` 下即可自动加载。

```bash
cp -r skills/product-screening ~/.claude/skills/
cp -r skills/price-response ~/.claude/skills/
cp -r skills/listing ~/.claude/skills/
cp -r skills/listing-visuals ~/.claude/skills/
```

**Codex / 其它 AI 对话框**：直接把 `SKILL.md` 全文粘进对话，再附上你的输入数据。
生图部分用 Codex 更顺手（自带生图模型）——详见项目里的 `CODEX使用指南.md`。

**不想装**：面板「⑦ 文案生成」页可以直接生成拼好的 Prompt，复制即用。

## 数据可靠性

这些 skill 里出现的费率与阈值：

| 数据 | 可靠性 |
|---|---|
| 平台佣金率、支付费率 | ✅ 查的公开费率表，来源写在 `data/platforms.yaml` 头注释 |
| 重量阈值、评分权重 | ⚠️ 经验判断，不是行业标准，按自己情况调 |
| 物流费率 | ⚠️ 估算量级，需用货代实际 rate card 替换 |
| 退货率 | ⚠️ 估算占位值，只能用自己店铺历史订单统计 |
| 平台图片规范 | ⚠️ 会变，发布前以目标站点后台最新政策为准 |
