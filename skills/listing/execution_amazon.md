# 执行层 Prompt：Amazon Listing 文案

输入是决策层产出的「内容策略卡」。产出以下三部分，不要额外发挥：

1. **标题**（Title）：主关键词 + 产品属性 + 使用场景，控制在 200 字符以内。
2. **五点描述**（Bullet Points）：正好 5 条，每条以大写关键词开头（如 `DURABLE MATERIAL:`），
   每条对应策略卡里的一个卖点或场景，禁止使用 `avoid_claims` 里列出的表述。
3. **后台关键词**（Search Terms）：8-10 个，只用策略卡里的 `target_keywords` 及其自然变体，
   不得堆砌无关词或竞品品牌词。

## 输出格式

```markdown
### Title
...

### Bullet Points
1. ...
2. ...
3. ...
4. ...
5. ...

### Search Terms
...
```
