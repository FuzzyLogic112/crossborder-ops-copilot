# 使用指南 · Usage Guide

`crossborder-ops-copilot` 的完整使用文档。这套工具有 **4 种用法**，从简单到复杂：

| 用法 | 适合谁 | 需要 AI 吗 |
|---|---|---|
| 1️⃣ 命令行 CLI | 所有人。装完就能跑 | ❌ 不需要 |
| 2️⃣ Listing 生成 Skill | 要写多平台产品文案的人 | ✅ 需要 Claude / ChatGPT 等 |
| 3️⃣ MCP Server | 想用自然语言驱动工具的人 | ✅ 需要支持 MCP 的客户端 |
| 4️⃣ 自动化工作流 | 想每天自动出日报的人 | ❌ 不需要 |

**四种可以只用一种，互不依赖。** 建议从 1️⃣ 开始。

---

# 0. 安装

```bash
git clone <this-repo>
cd crossborder-ops-copilot
pip install pandas openpyxl pytest pyyaml
```

想用 MCP（用法 3️⃣）再额外装：

```bash
pip install mcp anyio
```

验证装好了：

```bash
python -m pytest -q
```

应该看到 `46 passed`。**核心命令全部离线运行，不需要注册任何账号、不需要 API Key。**

---

# 1️⃣ 命令行 CLI（最基础，推荐先用这个）

## 1.1 选品评分

给一批候选商品打分排序，并自动淘汰不该做的品。

```bash
python cli.py score-products --scenario standard
```

输出一张表 + 一个 Excel 文件（`reports/product_scores.xlsx`）。

**六维度评分模型**（总分 100）：

| 维度 | 权重 | 含义 |
|---|---|---|
| 需求稳定性 | 25 | 需求是否持续，而非一次性话题 |
| 竞争缺口 | 20 | 是否有可切入的差异化空间 |
| 贡献利润 | 20 | 由系统按真实费率计算，**唯一客观项** |
| 物流履约 | 15 | 体积重量、时效、破损风险 |
| 合规与侵权风险 | 10 | 商标、专利、平台禁限售 |
| 内容展示空间 | 10 | 是否方便拍图拍视频 |

**硬性淘汰规则**（不等总分算完，直接出局）：
- `compliance_flag = banned`（禁限售 / 功效宣称风险）
- 贡献利润 ≤ 0（成本覆盖不了）

> ⚠️ 六项里只有「贡献利润」是系统算的，**另外四项需要你自己在 CSV 里打分**。
> 这个工具的定位是**把打分标准固定下来 + 算准利润 + 自动执行红线**，
> 不是替你做判断。

可选参数：

```bash
--scenario conservative   # 目标毛利 20%
--scenario standard       # 目标毛利 30%（默认）
--scenario aggressive     # 目标毛利 40%
--platform tiktok_shop | amazon_fba | amazon_fba_electronics | amazon_fba_apparel | independent_site | independent_site_paypal
--market US | EU | SEA
--input  自己的商品 CSV
--output 输出路径（.xlsx 或 .csv）
```

## 1.2 单品利润与定价测算

```bash
python cli.py profit --sku TRAVEL-001 --platform tiktok_shop --scenario conservative
```

输出完整成本拆解：采购、包装、头程物流、平台佣金、支付手续费、退款准备金、
**保本价、建议定价、贡献利润率、广告 Broke-even ROAS**。

想算「按某个具体售价能不能做」：

```bash
python cli.py profit --sku TRAVEL-001 --price 59.9
```

**核心公式**：

```
固定成本 = 采购价 + 包装成本 + 头程物流
头程物流 = 首重基础费 + 重量 × 续重单价
费率合计 = 平台佣金率 + 支付手续费率 + 退货准备金率

保本价   = 固定成本 ÷ (1 - 费率合计)
建议定价 = 固定成本 ÷ (1 - 费率合计 - 目标毛利率)
Broke-even ROAS = 1 ÷ 贡献利润率
```

> 💡 注意保本价是**除以** `(1 - 费率)`，不是乘以 `(1 + 费率)`——
> 因为佣金按**售价**百分比收取，不是按成本收取。这里很容易算错，
> 而且错得不明显，只是每单少赚几块钱。

## 1.3 竞品变化监控

比较两份竞品快照，输出变化日报：

```bash
python cli.py monitor --from data/competitors_2026-09-10.csv \
                      --to   data/competitors_2026-09-11.csv \
                      --output reports/change.md
```

能识别：降价 / 涨价 / 新品上榜 / 下架 / 促销变化 / 评分变化，
每类配一条规则化建议（观察 / 测试 / 立即处理）。

> ⚠️ **两份快照必须覆盖相同范围**（同类目、同页数）。
> 如果范围不同，多出来的商品会被误判成「新品上榜」。
> 工具会自动只在共同区间内比对并在报告顶部警告，但那部分数据等于白抓了。

## 1.4 历史数据入库

```bash
python cli.py ingest --input data/competitors_2026-09-10.csv --snapshot-date 2026-09-10
```

写入本地 SQLite（`data/history.db`）。主键是 `(日期, 平台, 商品ID)` 三列联合，
**同一天重复导入是覆盖而不是叠加**，方便纠错重跑。

## 1.5 接入你自己的数据

### 商品清单：`data/products.csv`

| 字段 | 含义 | 怎么填 |
|---|---|---|
| `sku` / `name` / `category` | 编号 / 名称 / 类目 | 类目要和 `platforms.yaml` 的退货率配置对得上 |
| `cost_price` / `packaging_cost` | 采购价 / 包装成本 | 数字 |
| `weight_kg` / `volume_l` | 计费重量 / 体积 | 影响物流成本 |
| `compliance_flag` | 合规标记 | `ok` / `review_needed` / `banned` |
| `demand_score` | 需求稳定性 | 0–25，**你自己判断打分** |
| `gap_score` | 竞争缺口 | 0–20 |
| `logistics_score` | 物流履约 | 0–15 |
| `content_score` | 内容展示空间 | 0–10 |
| `planned_price` | **计划售价** | 参考竞品定的实际售价 |

> ⚠️ `planned_price` 必须填**真实参考价**，不要填「刚好达标」的价格。
> 否则所有商品的利润分都会是满分，评分失去区分能力。

### 竞品快照：`data/competitors_*.csv`

必需字段：`platform, item_id, title, price, rating, review_count, promotion, url`

可选字段（会保留但不入库）：`rank, category, source, collected_date`

> 💡 编码用 **UTF-8**。如果是 Excel 导出的 CSV（带 BOM），工具已自动处理。

### 费率配置

- **`data/platforms.yaml`** — 平台佣金、支付手续费、分类目退货率
  🟢 佣金与支付费率是**真实公开数据**，文件头注释有来源链接与查询日期
  🟡 退货率是**估算占位值**（平台不公布，只能用自己店铺历史订单统计）

- **`data/logistics_rates.yaml`** — 各市场头程物流费率
  🟡 **全是估算**。货代报价一对一议价、不公开挂牌，
  请找货代要一份 rate card 后替换，**不需要改任何代码**

---

# 2️⃣ Listing 生成 Skill（需要 AI）

三层 Prompt 架构，为同一个产品生成多平台文案并做合规质检。

```
skills/listing/
  planning_layer.md      第 1 层 决策：产品信息 → 内容策略卡（JSON）
  execution_amazon.md    第 2 层 执行：策略卡 → 亚马逊标题 + 五点 + 后台关键词
  execution_shopify.md   第 2 层 执行：策略卡 → 独立站长文案 + SEO 元信息
  execution_tiktok.md    第 2 层 执行：策略卡 → TikTok 短标题 + 15 秒口播稿
  qa_layer.md            第 3 层 质检：扫合规风险 + 字数超限
```

## 用法 A：手动三轮（任何 AI 对话框都能用）

1. 复制 `planning_layer.md` 全文 → 粘到 AI 对话框 → 附上你的产品 JSON（格式见
   `examples/example_input.json`）→ 得到**内容策略卡**
2. 分别复制三个 `execution_*.md` → 各配上策略卡跑一次 → 得到三个平台的文案草稿
3. 复制 `qa_layer.md` → 把三份草稿一起贴上 → 得到风险提示 + 字数检查

参考结果见 `examples/example_output.md`。

## 用法 B：装成 Claude Code Skill（自动加载）

```bash
# macOS / Linux
cp -r skills/listing ~/.claude/skills/cross-border-listing

# Windows PowerShell
Copy-Item -Recurse skills\listing "$env:USERPROFILE\.claude\skills\cross-border-listing"
```

之后直接说「给这个产品生成三平台 Listing」，Claude Code 会自动加载这套 Prompt，
不用手动复制粘贴。

## 边界声明（重要）

- 质检层的规则**整理自公开可查的常见合规风险类型**（见 `data/common_risk_types.md`），
  **不是任何平台的官方违禁词库**。发布前必须人工核对目标平台最新政策。
- 执行层输出是**草稿**，不是可直接发布的文案。
- 决策层不会凭空新增卖点——它只对你输入的 `core_features` 排序。

---

# 3️⃣ MCP Server（需要支持 MCP 的客户端）

把 6 个业务函数暴露成 MCP 工具，让 AI 助手用自然语言驱动。

## 接入 Claude Code

项目自带 `.mcp.json`，在项目目录启动即可：

```bash
cd crossborder-ops-copilot
claude
```

首次会询问是否信任项目配置，同意后用 `/mcp` 确认 `crossborder-ops` 已连接。

然后就能直接问：

> 「TRAVEL-001 在 tiktok_shop 和 amazon_fba 上的贡献利润分别是多少，哪个更值得做？」

它会自己调 `calculate_unit_profit` 两次再对比。

## 接入 Claude Desktop

编辑配置文件：
- Windows：`%APPDATA%\Claude\claude_desktop_config.json`
- macOS：`~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "crossborder-ops": {
      "command": "python",
      "args": ["/absolute/path/to/crossborder-ops-copilot/mcp_server/server.py"]
    }
  }
}
```

**Claude Desktop 必须用绝对路径。** 改完重启客户端。

## 手动启动（调试用）

```bash
python mcp_server/server.py
```

**会「卡住不动、没有任何输出」——这是正常的**，stdio 协议在等客户端连接。
`Ctrl+C` 退出。

## 6 个工具与审批分级

| 工具 | 作用 | 审批级别 |
|---|---|---|
| `get_competitor_snapshot` | 读取某日某竞品的标准化记录 | 只读 |
| `score_product` | 单品六维度评分 | 只读 |
| `calculate_unit_profit` | 单品利润明细 | 只读 |
| `build_weekly_report` | 生成周报事实摘要 | 只读 |
| `draft_listing` | 起草 Listing 策略骨架 | ⚠️ 需人工审核（**卖点字段刻意留空，不让 AI 编造产品特性**） |
| `create_price_change` | 改价建议与利润影响对比 | 🚫 **禁止自动执行** |

### 设计原则：能力上就不具备，而非靠开关控制

`create_price_change` 永远改不了价——**这个函数里根本没有调用任何店铺 API 的代码**。

**本项目不做**：自动改价、自动上架、自动投放广告、自动发送客户或达人消息。
这些永远需要人工在平台后台确认执行。Agent 编排规则见 `mcp_server/agent_policy.md`：
**报告里每个数字都必须来自工具返回结果，不得自行编造。**

---

# 4️⃣ 自动化工作流

一条命令跑完「导入 → 比对 → 评分摘要 → 落盘报告」：

```bash
python automation/daily_workflow.py \
  --input data/competitors_2026-09-11.csv \
  --date 2026-09-11 \
  --prev-date 2026-09-10
```

产出在 `reports/daily_<date>.md`。

## 定时运行

脚本**本身不注册任何系统定时任务**（改系统设置需要你自己确认）。

Windows 任务计划程序：

```powershell
schtasks /create /tn "CrossBorderOpsDaily" /tr "python C:\path\to\automation\daily_workflow.py --input <今日CSV> --date <今日> --prev-date <昨日>" /sc daily /st 09:00
```

Linux / macOS crontab：

```
0 9 * * * cd /path/to/crossborder-ops-copilot && python automation/daily_workflow.py --input data/today.csv --date $(date +\%F) --prev-date $(date -d yesterday +\%F)
```

---

# 5. 接入你自己的抓取工具

`adapters/` 是数据源适配层。核心逻辑（`src/`）**不知道数据从哪来**，
所以换平台只需要新写一个 adapter。

## 现成的：amzrank 适配器

把抓取工具导出的 `.xlsx` 放进 `data/inbox/`，然后：

```bash
python cli.py import-amzrank --collected-date 2026-09-11
```

自动取 `data/inbox/` 里**修改时间最新**的 xlsx（会跳过 Excel 的 `~$` 锁文件）。

也可以指定目录或文件：

```bash
export AMZRANK_OUT=/path/to/your/output      # 环境变量
python cli.py import-amzrank --input file.xlsx --collected-date 2026-09-11
```

## 自己写一个 adapter

在 `adapters/` 下新建文件，只需要输出满足这个契约的 CSV：

```python
SNAPSHOT_COLUMNS = ["platform", "item_id", "title", "price",
                    "rating", "review_count", "promotion", "url"]
EXTRA_COLUMNS = ["rank", "category", "source", "collected_date"]
```

照 `adapters/amzrank_adapter.py` 的结构写即可。
测试 `tests/test_amzrank_adapter.py::test_output_csv_satisfies_ingest_required_columns`
守的就是这个契约——**新 adapter 照抄这个测试就能确认接得上**。

## 数据采集的合规边界（请务必遵守）

- 只采集**公开可见的页面、官方 API、已授权账户导出、合法工具导出**的数据
- 遇到**登录墙、验证码、访问限制、站点条款不允许**的情况：
  **停止自动访问**，改用手工或授权导出
- 控制请求频率（建议**页面间隔 ≥ 3 秒**），不要给对方服务器造成压力
- **本仓库不包含任何抓取到的第三方平台数据**。
  `data/real/` 在 `.gitignore` 里——请自己抓自己的数据，不要转发他人抓取结果

---

# 6. 数据真实性声明

这个项目里有三类数据，**真实性完全不同，请不要混着引用**：

| | 内容 | 位置 |
|---|---|---|
| 🟢 **真实公开数据** | 平台佣金、支付手续费率（含来源链接与查询日期） | `data/platforms.yaml` 文件头 |
| 🟡 **估算占位值** | 退货率、头程物流费率（已在文件里单独标注） | `platforms.yaml` / `logistics_rates.yaml` |
| 🔴 **训练用虚构数据** | 10 个示例商品、演示用竞品快照（URL 为不可路由占位域名） | `data/products.csv`、`data/competitors_*.csv` |

**保留虚构演示数据是刻意设计**——这样 clone 下来就能立刻跑通全部命令、跑通测试，
不需要先去抓数据、不需要联网。

> ⚠️ 用于任何真实经营决策前，请把上面 🟡 和 🔴 两类全部换成你自己的真实数据。
> 费率请以目标平台官方费率页为准（平台规则会变），物流请以货代实际报价为准。

---

# 7. 常见问题

**Q：报 `ModuleNotFoundError: No module named 'src'`**
在项目根目录运行命令。`conftest.py` 只负责测试时的路径，直接跑脚本要在根目录。

**Q：跑测试报 `pytest-current` 权限错误（Windows）**
Windows 符号链接限制。换个临时目录：`python -m pytest -q --basetemp=.pytest-tmp`

**Q：`import-amzrank` 报 PermissionError，路径里有 `~$`**
那是 Excel 锁文件。关掉 Excel 即可。新版本已自动跳过锁文件。

**Q：CSV 第一个列名前面多了奇怪字符，报缺字段**
Excel 导出的 CSV 带 BOM。工具用 `utf-8-sig` 读取已自动处理；
如果你自己写读取代码，注意别用 `utf-8`。

**Q：`monitor` 报出几十条「新品上榜」**
两份快照覆盖范围不同（页数不一样）。用相同类目、相同页数重抓。

**Q：MCP 启动后没反应**
正常。stdio 协议在等客户端连接，不是报错。

**Q：目标毛利率报「无法达成」**
费率合计 + 目标毛利率超过 100% 了。降低 `--scenario` 或检查 `platforms.yaml` 配置。

---

# 8. 项目结构

```
crossborder-ops-copilot/
├── cli.py                 命令行总入口
├── src/                   核心逻辑（纯函数，不碰网络）
│   ├── models.py          数据结构定义
│   ├── calculator.py      选品评分 + 利润测算  ← 核心
│   ├── monitor.py         竞品快照比对
│   └── ingest.py          CSV → SQLite
├── adapters/              数据源适配层（外部格式 → 标准格式）
├── skills/listing/        Listing 生成三层 Prompt
├── mcp_server/            MCP 工具（6 个，含审批分级）
├── automation/            每日自动化工作流
├── data/                  配置（费率）+ 示例数据
│   └── inbox/             抓取工具落地目录
├── reports/               命令产出的报告
└── tests/                 46 个单元测试
```

---

# 9. License 与免责

本项目代码由 AI 编码工具辅助生成，需求拆解、数据结构与业务逻辑设计由作者完成。

**免责**：本工具提供的是计算框架，不构成经营建议。
所有费率、退货率、物流成本都需要使用者用自己的真实数据替换后才具备决策价值。
使用本工具采集数据时，请自行确保遵守目标平台的服务条款与所在地法律法规。
