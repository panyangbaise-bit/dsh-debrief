# UI · 卡片与 Dashboard 页面规格

> English follows the Chinese section.

## 渲染面

1. **会话内工具卡片**：`tool.call.toolview` 键控 slot（按工具名注册），命中即替换该次工具调用的通用行。
   注册 12 个 key（9 只读 + news + 3 白名单写）。
2. **Dashboard 页面（v1.5）**：注册于 `main` slot（key `debrief-dashboard`）+ `sidebar.panellist` 导航入口，
   数据来自认证路由 `/api/debrief/dashboard?range=N`（Host 内部 runCli dashboard）。

## 卡片矩阵

| 工具                                        | 卡片       | 头部                                              | 主体                                                           | 尾部                                   |
| ------------------------------------------- | ---------- | ------------------------------------------------- | -------------------------------------------------------------- | -------------------------------------- |
| debrief_holdings                            | 持仓总览卡 | 总市值/今日盈亏/总盈亏（涨跌色）                  | 持仓表：代码 名称 数量 成本 现价 市值 盈亏% 权重（权重迷你条） | 计数 · 更新于                          |
| debrief_transactions                        | 成交明细卡 | 共 N 笔                                           | 成交表：时间 方向 代码 名称 数量 价格 金额 状态                | 空态文案                               |
| debrief_watchlist                           | 监察表卡   | N 自选                                            | 表：代码 名称 现价 涨跌% 关注价 距关注价 提醒                  | 引导添加文案                           |
| debrief_report                              | 报告卡     | 市场 badge + 标题 + 生成时间                      | 摘要 + SVG 折线图 + 指标行                                     | 展开全文 / 收起                        |
| debrief_memory                              | 记忆证据卡 | 分层 badge（长期/短期）+ 主题 + 置信度 + 时间范围 | 摘要 + 证据引用（`[[cite:doc:id]]` 可展开看原文）              | 空态文案                               |
| debrief_analyze                             | 任务进度卡 | jobId + 状态点 + preparedAt                       | 行情快照 / 新闻 / 记忆候选三段                                 | guidance 提示                          |
| debrief_jobs                                | 运行记录卡 | N 条                                              | 时间线列表（状态点：成功/失败/运行中，失败显示错误码）         | 台账说明                               |
| debrief_dashboard                           | 仪表盘卡   | 近 N 天                                           | KPI 行 + 资产/收益折线 + 成分环形图 + 持仓/监察表              | 添加入口引导                           |
| debrief_news                                | 新闻速览卡 | N 条 · 抓取时间                                   | 时间线列表（标题/时间/市场·来源）                              | 空态文案                               |
| debrief_report_create / compact_write / add | 写回结果卡 | 报告已写回 / 记忆压缩已写回 / 记忆已沉淀          | ID（+版本/状态）                                               | 审计标注（已入内核 user_actions 审计） |

## 降级路径（绝不 crash slot）

- 未决块（`kind === undefined`）→ 空壳卡（meta「…」）。
- 工具失败（`isError`）→ 错误卡：错误码 + 说明（localize 错误码表，未命中用原始 message）。
- 结果非 JSON → `DEBRIEF_PARSE` 错误卡。
- 数据不匹配渲染模型（client 内置 schema 校验）→ 错误卡，不抛异常；未知 schema 版本宽松通过。
- 无数据/空数组 → 各自空态文案。

## 视觉与主题

- 颜色只走宿主 theme token（`--dsw-alias-*`，light/dark 自适应）；涨跌色为语义约定例外（CN 红涨绿跌，`light-dark()` 自适应）。
- 数字千分位、百分比 2 位；表格等宽数字；图表纯 SVG（折线/面积/环形），抽样 ≤365 点。
- 加载 = 骨架屏；Dashboard 页面图表用 IntersectionObserver 懒加载（160px 预载边距，进入视口后常驻）。
- 响应式：≥768px 全列；<768px 页面网格单列；表格横向滚动。
- 无障碍：卡片头可折叠（role=button / aria-expanded / Enter·Space）；涨跌同时给 +/- 符号（颜色不作唯一信息通道）；SVG 带 aria-label。

## Dashboard 页面结构（自上而下）

1. 标题 + 时间范围 chips（近 30 天 / 90 天 / 200 天 / 近一年），切换重绘两条折线。
2. KPI 行（4 格，<768px 自动换行）：总资产 / 今日收益 / 总收益 / 年化收益。
3. 资产变化面积图（跨 2 列）。
4. 收益折线（0 基线虚线，末值涨跌色）。
5. 成分环形图（stroke-dasharray 分段 + 图例，中心 = 持仓数）。
6. 持仓表（头部「+ 添加持仓」，v2 占位入口）。
7. 监察表（头部「+ 添加自选」，v2 占位入口）。
8. 底部提示：添加入口 v2 走 DSH 确认流。

## 验证口径

- keyed 命中替换通用行；zod 失败 → fallback，slot 不 crash。
- light/dark 双检；360px 窄屏可用。
- 卡片不 import 任何宿主 client 包；npm 产物无第三方 UI 依赖（见发布门槛）。

---

## Rendering surfaces

1. **In-conversation tool cards**: keyed `tool.call.toolview` slot (one entry
   per tool name); a hit replaces the generic tool row. 12 keys are registered
   (9 read tools + news + 3 whitelisted writes).
2. **Dashboard page (v1.5)**: registered in the `main` slot (key
   `debrief-dashboard`) plus a `sidebar.panellist` navigation entry; data comes
   from the authenticated route `/api/debrief/dashboard?range=N` (the Host runs
   `dashboard --json` internally).

## Card matrix

| Tool                                        | Card            | Header                                                | Body                                                                  | Footer                           |
| ------------------------------------------- | --------------- | ----------------------------------------------------- | --------------------------------------------------------------------- | -------------------------------- |
| debrief_holdings                            | Holdings        | Total value / day P&L / total P&L (up-down colors)    | Table: symbol, name, qty, cost, price, value, P&L%, weight (mini bar) | Count · as-of                    |
| debrief_transactions                        | Trades          | N trades                                              | Table: time, side, symbol, name, qty, price, amount, status           | Empty state                      |
| debrief_watchlist                           | Watchlist       | N watched                                             | Table: symbol, name, price, chg%, target, distance, alert             | Add guidance                     |
| debrief_report                              | Report          | Market badge + title + generated-at                   | Summary + SVG line chart + metrics                                    | Expand/collapse full text        |
| debrief_memory                              | Memory evidence | Layer badge (long/short) + topic + confidence + range | Summary + expandable evidence (`[[cite:doc:id]]`)                     | Empty state                      |
| debrief_analyze                             | Analysis job    | jobId + status dot + preparedAt                       | Quotes / news / memory candidates sections                            | Guidance hint                    |
| debrief_jobs                                | Job ledger      | N entries                                             | Timeline (status dots; failures show error code)                      | Ledger note                      |
| debrief_dashboard                           | Dashboard       | Last N days                                           | KPIs + equity/returns charts + donut + tables                         | Add guidance                     |
| debrief_news                                | News            | N items · fetched-at                                  | Timeline (title/time/market·source)                                   | Empty state                      |
| debrief_report_create / compact_write / add | Write result    | Report written / Memory compacted / Memory added      | ID (+version/status)                                                  | Audit note (kernel user_actions) |

## Fallback paths (never crash the slot)

- Unsettled block → empty-shell card (meta “…”).
- Tool failure → error card: code + localized explanation (unknown codes fall
  back to the raw message).
- Non-JSON result → `DEBRIEF_PARSE` error card.
- Data failing the render-model validation → error card, never a throw; unknown
  schema versions pass permissively.
- Empty payloads → per-card empty states.

## Visual and theme

- Colors only from host theme tokens (`--dsw-alias-*`, light/dark adaptive);
  up/down colors are the semantic exception (red-up in the CN convention, via
  `light-dark()`).
- Thousands separators, 2-decimal percentages; tabular numerals in tables; pure
  SVG charts (line/area/donut), sampled to ≤365 points.
- Loading = skeleton; page charts lazy-load via IntersectionObserver (160px
  pre-load margin, sticky once visible).
- Responsive: full columns ≥768px; single column below; tables scroll
  horizontally.
- A11y: collapsible card headers (role=button, aria-expanded, Enter/Space);
  up/down always carries a +/- sign (color is never the only channel); SVGs
  carry aria-labels.

## Dashboard page layout (top to bottom)

1. Title + range chips (30/90/200 days, 1 year); switching redraws both lines.
2. KPI row (4 cells): total assets / day return / total return / annualized.
3. Equity area chart (spans 2 columns).
4. Returns line (dashed zero baseline, end value in up/down color).
5. Composition donut (stroke-dasharray segments + legend; center = holdings count).
6. Holdings table (header “+ Add holding”, v2 placeholder).
7. Watchlist table (header “+ Add watch”, v2 placeholder).
8. Footer note: add entries arrive in v2 through the DSH confirmation flow.

## Acceptance criteria

- Keyed hit replaces the generic row; validation failure falls back, the slot
  never crashes.
- Light/dark verified; usable at 360px.
- Cards import no host client package; the npm artifact has no third-party UI
  dependency (see the release gate).
