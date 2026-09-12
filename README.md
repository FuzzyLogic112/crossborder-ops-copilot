# crossborder-ops-copilot

跨境电商运营智能副驾驶 —— 个人求职实训项目。用一套本地可运行的工具证明：
跨平台选品、竞品分析、贡献利润测算、Listing 草稿生成、合规风险提示、日报生成，
这套判断能力在亚马逊 / TikTok Shop / Shopee / Temu / 独立站方向都能迁移使用。

**本项目代码由 Codex / Claude Code 等 AI 编码工具辅助生成，需求拆解、数据结构与业务逻辑设计
由本人完成，本人负责测试与验收。**

**数据真实性分三类，详见 [`USAGE.md` 的「数据可靠性分级」](USAGE.md#数据可靠性分级)：平台佣金与支付费率是真实公开数据
（有来源链接）；`data/real/` 下的竞品数据是自有工具抓取的真实亚马逊公开榜单数据；
退货率与物流费率是估算占位值（已标注）；`data/` 根目录的商品与演示竞品数据是训练用虚构数据。
**任何情况下都不代表真实店铺业绩、真实 GMV 或真实投放结果。**

## 文档

| 文档 | 内容 |
|---|---|
| [`USAGE.md`](USAGE.md) | ⭐ **推荐先看**。跑通全链路的完整参考：8 步流程、所有参数、公式、数据可靠性分级、FAQ |
| [`skills/README.md`](skills/README.md) | 4 个运营 SOP：选品初筛 / 跟价决策 / Listing 文案 / 产品图。**不用装工具也能直接粘进 AI 对话框用** |

## 在线演示与完整功能的区别

**在线只读版**：https://fuzzylogic112.github.io/crossborder-ops-copilot/

| 功能 | 在线版 | 本机运行 |
|---|---|---|
| 定价计算器（交互式，实时重算） | ✅ | ✅ |
| 选品评分与硬性淘汰可视化 | ✅ | ✅ |
| Listing 三层 Prompt 生成（复制后粘到自己的 AI 工具） | ✅ | ✅ |
| **供应商比价**（到仓成本归一化，多平台横向对比） | ✅ 算法在浏览器跑 | ✅ 可落盘、可写回采购价 |
| 浏览器本地存储 / 自建数据库推送 | ✅ | ✅ |
| **抓取真实竞品数据** | ❌ | ✅ |
| **每日工作流、快照入库、跨快照对比** | ❌ | ✅ |
| CLI / MCP Server | ❌ | ✅ |

### 为什么在线版不能抓取，也连不上你本机的服务

两道浏览器安全墙，都绕不过：

1. **同源策略（CORS）**：网页 JS 不能直接请求 amazon.com 这类站点，平台不会给你的页面发跨域许可。
2. **本地网络访问限制**：在线版是 HTTPS 页面，浏览器会拦掉它对 `http://127.0.0.1` 的请求
   （Private Network Access 限制，实测报 `ERR_BLOCKED_BY_CLIENT`）。

**所以：在线版永远连不上你本机的 `serve.py`，刷新也没用。**
要跑完整链路，clone 下来在本机运行，然后访问本地服务自己打开的地址：

```bash
git clone https://github.com/FuzzyLogic112/crossborder-ops-copilot
cd crossborder-ops-copilot
pip install pandas openpyxl pytest pyyaml
python serve.py --open        # 自动打开 http://127.0.0.1:8911
```

## 安装

```bash
pip install pandas openpyxl pytest pyyaml mcp anyio pytest-anyio

# 只有「抓真实竞品数据」这一步需要，其余命令都不需要
pip install playwright
python -m playwright install chromium
```

**核心命令（评分 / 利润 / 比对 / 报告 / MCP）全部离线可跑，无需账号、无需 API Key。**
只有 `import-amzrank` 前置的 amzrank 抓取步骤需要联网。

## 命令

```bash
# 1. 把竞品快照 CSV 导入本地 SQLite 历史库
python cli.py ingest --input data/competitors_2026-09-10.csv --snapshot-date 2026-09-10
python cli.py ingest --input data/competitors_2026-09-11.csv --snapshot-date 2026-09-11

# 2. 对候选商品做六维度评分与硬性淘汰，导出 Excel 报告
python cli.py score-products --scenario standard

# 3. 计算单个 SKU 的贡献利润、保本价、建议定价与广告 Broke-even ROAS
python cli.py profit --sku TRAVEL-001 --scenario conservative

# 4. 比较两次竞品快照，生成变化日报
python cli.py monitor --from data/competitors_2026-09-10.csv --to data/competitors_2026-09-11.csv

# 5. 抓真实竞品数据（三步）：先用 amzrank 抓，再转标准格式，再入库
#    步骤 1 在 amzrank 项目里跑（需 playwright install chromium）：
#      python amzrank.py --site us --category pet-supplies --pages 1
#    步骤 2-3 在本项目：
python cli.py import-amzrank --collected-date 2026-09-11
python cli.py ingest --input data/real/competitors_real.csv --snapshot-date 2026-09-11

# 6. 每日自动化工作流：导入 -> 比对 -> 评分摘要 -> 落盘报告，一条命令跑完
python automation/daily_workflow.py --input data/competitors_2026-09-11.csv --date 2026-09-11 --prev-date 2026-09-10

# 7. 启动本地 MCP Server（stdio，接入 Claude Desktop / Claude Code 用）
python mcp_server/server.py

# 跑测试（含 MCP 协议层与抓取适配层，共 37 个）
python -m pytest -q
```

## MCP 工具（6 个，见 mcp_server/tools.py + server.py）

| 工具 | 审批级别 |
|---|---|
| get_competitor_snapshot / score_product / calculate_unit_profit / build_weekly_report | 只读 |
| draft_listing | 人工审核后才可使用（只出策略骨架，不出可直接发布的文案） |
| create_price_change | **禁止自动执行**，只算利润影响对比，不接入任何真实店铺 |

Agent 编排规则见 `mcp_server/agent_policy.md`——核心原则是**报告里的每个数字都必须来自工具返回结果，
不得自行编造**，也不得暗示自动改价 / 上架 / 投放 / 发消息已经执行。

## 定时运行

`automation/daily_workflow.py` 本身不做任何定时调度，也不会自己注册系统任务
（改系统设置需要你自己确认并执行）。如果要每天自动跑一次，在 Windows 上可以自己创建计划任务：

```powershell
schtasks /create /tn "CrossBorderOpsDaily" /tr "python D:\path\to\automation\daily_workflow.py --input <今日CSV> --date <今日日期> --prev-date <昨日日期>" /sc daily /st 09:00
```

请自行替换路径和日期参数后再执行，本项目不会代你注册这个任务。

## 目录结构

```
crossborder-ops-copilot/
  data/              样例数据、平台费率配置、历史快照数据库
  src/               评分器、利润计算器、竞品监控、数据导入
  adapters/          抓取数据源适配层（amzrank -> 标准竞品快照格式）
  skills/            4 个运营 SOP（选品初筛 / 跟价决策 / Listing / 产品图），见 skills/README.md
  reports/           score-products 和 monitor 命令生成的报告
  tests/             123 个单元测试，覆盖计算逻辑、硬性淘汰、数据导入、MCP 工具、
                     抓取适配层、标题解析、空环境启动
  cli.py             命令行入口
```

## 六维度选品评分模型

需求稳定性 25 + 竞争缺口 20 + 贡献利润 20 + 物流履约 15 + 合规与侵权风险 10 + 内容展示空间 10 = 100。
任何商品出现 `compliance_flag = banned`（禁限售 / 功效宣称风险）或贡献利润 ≤ 0，
**直接淘汰，不参与总分排序**——这条规则本身就是可以在面试中讲的一句话："我不是只看总分排名，
出现红线问题会一票否决。"

## 贡献利润公式

```
贡献利润 = 售价 - 采购 - 包装 - 头程与尾程物流 - 平台佣金 - 支付手续费 - 退款准备金
```

这是一个简化模型，没有计入仓储费、退货物流费、平台活动扣点等更细的成本项——
先把核心结构跑通，后续可以按需加更多成本项。

## 数据与合规边界

- **平台佣金与支付费率是真实公开数据**，来源链接写在 `data/platforms.yaml` 文件头注释里
  （2026-09-10 检索）。权威口径仍应查 Amazon Seller Central 官方费率页与 TikTok Shop 商家后台。
- **退货率与头程物流费率是估算占位值**，已在配置文件中单独标注——退货率平台不公布，
  物流是货代一对一报价，这两项换成真实数字不需要改任何代码。
- **`data/real/` 下是真实抓取的亚马逊公开榜单数据**（自有工具 amzrank，Playwright 驱动，
  默认 3 秒间隔，只抓公开 Best Sellers 榜单页）。抓取与分析解耦：`adapters/` 负责把不同
  数据源转成标准快照格式，`src/` 的核心逻辑不关心数据从哪来。
- **`data/` 根目录下的 `products.csv` 与 `competitors_*.csv` 是训练用虚构数据**，
  URL 为不可路由占位域名，保留它们是为了让测试与演示不依赖网络。真实与虚构数据严格分开存放。
- **采购成本、重量、退货率抓不到**——那是供应链与店铺自有数据，只能靠供应商报价和历史订单。
  详见 USAGE.md 的「数据可靠性分级」。
- 真实使用时，数据获取只限**公开且允许访问的页面、官方 API、已授权账户导出或合法工具导出**；
  遇到登录、验证码、访问限制或站点条款不允许的情况，**必须停止自动访问，改用手工或授权导出**。
- 本项目**不做任何自动改价、自动上架、自动投放广告、自动发送客户或达人消息**——
  这类操作永远需要人工审核后手动执行。
- Listing 质检层的合规规则整理自公开可查的常见风险类型（见 `data/common_risk_types.md`），
  **不是任何平台的官方违禁词库**，发布前仍需人工核对目标平台最新政策。

## 简历项目描述（可直接用）

> 个人项目｜跨境电商运营智能副驾驶：使用 Python、SQLite、pandas 和三层 Prompt 架构，
> 搭建竞品数据标准化、选品评分、贡献利润测算、Listing 草稿生成、合规风险提示的完整流程；
> 所有平台动作保留人工审核。

**不要写**：独立运营店铺、实现真实 GMV、自动投放广告、爬取平台数据、成功打造爆款——
除非确有能核验的真实经历。
