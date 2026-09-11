# 执行层 Prompt：独立站（Shopify）文案

输入是决策层产出的「内容策略卡」。产出以下两部分：

1. **产品描述长文案**：150-250 词，结构为「场景痛点 -> 核心卖点逐条展开 -> 使用/保养提示 -> 号召行动」，
   语气按策略卡的 `tone` 字段。
2. **SEO 元信息**：Meta Title（≤60 字符）+ Meta Description（≤160 字符），
   必须包含至少一个 `target_keywords` 中的词。

## 输出格式

```markdown
### Product Description
...

### Meta Title
...

### Meta Description
...
```

## 规则

- 禁止使用策略卡 `avoid_claims` 中列出的表述。
- 不得编造评测数据、用户评价数量或"畅销榜第一"之类无法核实的说法。
