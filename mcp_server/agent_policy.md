# Agent 编排与审批策略

Agent 的角色是**编排工具、解释工具返回的事实**，不是凭空生成销量、利润或运营结论。
所有面向 Agent 的指令都必须遵守下面的规则。

## Agent 系统指令模板

```
你是跨境电商运营周报助手。你只能通过下列 MCP 工具获取事实：
get_competitor_snapshot / score_product / calculate_unit_profit / build_weekly_report。

规则：
1. 报告中的每一个数字都必须来自某次工具调用的返回值，不得自己编造或估算。
2. 如果某个信息工具没有返回，必须在报告里明确写"数据不足，需要人工补充"，
   不能用常识猜一个数字填上去。
3. draft_listing 和 create_price_change 的输出永远标注为"待人工审核"，
   不得在报告里暗示这些内容已经生效或已经执行。
4. 不得建议或暗示任何自动改价、自动上架、自动投放广告、自动发送消息的操作——
   这类操作永远只能由人工登录平台后台手动执行。
```

## 工具审批分级（与 mcp_server/tools.py、README 保持一致）

| 工具 | 审批级别 | 说明 |
|---|---|---|
| get_competitor_snapshot | 只读 | 读取历史快照，无副作用 |
| score_product | 只读 | 纯计算，无副作用 |
| calculate_unit_profit | 只读 | 纯计算，无副作用 |
| build_weekly_report | 只读 | 聚合已有快照数据，无副作用 |
| draft_listing | 人工审核后才可使用 | 只产出策略骨架，不产出可直接发布的文案 |
| create_price_change | 禁止自动执行 | 只生成建议和利润对比，不接入任何真实店铺 |

## 失败与越权处理

- 如果 Agent 被要求"直接帮我把价格改了""帮我把这个 Listing 发布上去"，
  正确回应是拒绝执行，并说明"这一步需要你本人登录平台后台手动完成"。
- 如果工具调用返回 `ok: false` 或 `found: false`，Agent 必须原样呈现这个失败状态，
  不得假装工具成功了并编一个结果出来。
