# Tools · 工具契约

> English follows the Chinese section.

所有工具与内核 CLI 同构：输出统一为 UTF-8 JSON envelope
`{ ok: true, schemaVersion, data } | { ok: false, schemaVersion, error: { code, message } }`，
非零退出码 + 错误对象。插件侧执行前校验必填参数、写工具再校验 payload 结构，
校验失败返回 `DEBRIEF_ARGS`。

## 只读工具（交互会话）

### debrief_holdings · 持仓总览

```json
{ "status": "open ｜ 省略=全部", "refresh": true }
```

CLI：`debrief holdings --json [--status open] [--refresh] [--no-refresh]` →
`{ asOf, currency, totalMarketValue, dayPnl, dayPnlPct, totalPnl, totalPnlPct, pricesRefreshed, priceErrors?, positions[] }`；
position 带 `currency`（CNY/USD/HKD）。`refresh` 缺省 = 自动实时刷新过期行情；
`refresh: true` 映射 `--refresh` 强制全部刷新；`--no-refresh` 只读缓存。

### debrief_transactions · 成交明细

```json
{ "ticker": "AAPL", "limit": 20, "offset": 0 }
```

CLI：`debrief transactions --json [--ticker X] [--limit N] [--offset N]` → `{ total, items[] }`

### debrief_watchlist · 监察表

```json
{ "refresh": true }
```

CLI：`debrief watchlist --json [--refresh] [--no-refresh]` → `{ count, pricesRefreshed, items[] }`；item 带 `currency`。

### debrief_instruments · 选标搜索

```json
{ "market": "us|cn|hk|crypto", "query": "至少 2 字符" }
```

CLI：`debrief instruments search --market <m> --query <q> --json` → `{ query, market, source, items[] }`
股票 = 本地目录 + 东财 suggest 兜底；加密 = CoinGecko。

### debrief_report · 报告读取

```json
{ "id": "rpt-…", "market": "us|cn|hk|crypto" }
```

CLI：`debrief report latest --json` / `--id <id> --json` → `{ id, market, title, generatedAt, summary, fullText, metrics[], chart }`

### debrief_memory · 记忆检索 / 压缩候选

```json
{ "query": "建仓理由" }
{ "compactCandidates": true }
```

CLI：`debrief memory search --query <q> --json` →
`{ query, items[] }`（长期摘要优先，带证据引用）；
`compactCandidates: true` 映射 `debrief memory compact-candidates --json` →
超窗未压缩候选（供 debrief-compact 技能）。

### debrief_analyze · 盘后分析输入包

```json
{ "market": "us|cn|hk|crypto", "refresh": true }
```

CLI：`debrief analysis prepare --market <m> --json [--refresh] [--no-refresh]` →
`{ market, preparedAt, jobId, pricesRefreshed, inputs: { quotes[], news[], memoryCandidates[] }, guidance }`
agent 基于输入包自行生成结论（内核无 LLM）。

### debrief_jobs · 任务台账

无参数。CLI：`debrief job list --json` → `{ items[] }`（kind/at/status/durationSec/errorCode）

### debrief_dashboard · 投资组合聚合

```json
{ "range": "30|90|200|365", "refresh": true }
```

CLI：`debrief dashboard --json [--range N] [--refresh] [--no-refresh]` →
`{ kpis, series: { range, equity[], returns[] }, composition[], holdings[], watchlist[], fx, pricesRefreshed }`
`fx = { base: "CNY", asOf, rates: { CNY, USD, HKD, EUR }, source } | null`
（free open.er-api.com；失败为 null，页面仅按 CNY 展示）。

### debrief_news · 新闻速览

```json
{ "limit": 20, "refresh": true, "notify": false }
```

CLI：`debrief news latest --json [--limit N] [--no-refresh] [--notify]` →
`{ items: [{ id, title, source, url, summary, publishedAt }], total, fetched, newCount, asOf, notified? }`
默认实时拉取并落库（标题去重）；`refresh: false` 映射 `--no-refresh` 只读最近一批；
`notify: true` 在拉到新条目时额外推送 Telegram（需已配置）。
（无摘要；要点由 debrief-news 技能在会话内生成，相关性过滤由 agent 完成。）

### debrief_telegram · Telegram 推送检查/测试

```json
{ "action": "test ｜ status" }
```

CLI：`debrief notify test --json`（未配置 → `DEBRIEF_TELEGRAM_UNCONFIGURED`；成功 → `{ sent }`）
/ `debrief notify status --json` → `{ configured, chatIdSet, tokenMask }`（token 打码）。

## 白名单写工具（仅定时 skill 会话）

三个写工具 description 均注明「Whitelisted write tool for scheduled debrief
skill sessions; every write is recorded in the kernel user_actions audit ledger」。
写操作入内核 `user_actions` 审计、走幂等 job 状态机。交互会话的写（添加持仓/自选）是 v2 能力。

### debrief_report_create

```json
{
  "market": "us|cn|hk|crypto|weekly|monthly",
  "title": "盘后分析 · 2026-11-11",
  "summary": "一句话总结/关键变化/组合影响/操作信号",
  "fullText": "可选",
  "metrics": [{ "label": "波动率", "value": "18.6%" }],
  "chart": { "title": "60 日走势", "unit": "", "points": [100, 101.2] },
  "jobId": "debrief-job-2048"
}
```

CLI：`debrief report create --json`（payload 走 stdin）→ `{ id, status }`

### debrief_memory_compact_write

```json
{
  "topic": "position-aapl-rationale",
  "instruments": ["AAPL"],
  "summary": "结论/理由/条件",
  "evidenceRefs": [{ "docId": 12, "quote": "原文摘录" }],
  "timeRange": { "from": "2026-03-01", "to": "2026-05-31" },
  "confidence": "high|medium|low",
  "caveats": "已知局限"
}
```

CLI：`debrief memory compact-write --json`（stdin）→ `{ id, version }`（同 topic 自动 version+1）

### debrief_memory_add

```json
{
  "sourceType": "decision|trade|report|note|conversation",
  "content": "决策原文 + 理由 + 条件",
  "instruments": ["AAPL"],
  "occurredAt": "2026-11-10T08:00:00Z"
}
```

CLI：`debrief memory add --json`（stdin）→ `{ docId }`

## v2 编辑工具（审批门控 · 对话与 UI 同一实现）

六个编辑工具与 投资组合页面弹窗共用同一个 Host 操作（UserActions 单一实现模式）：
Agent 发起的写操作先经过 DSH 审批确认流（`tools/pre-execute` 返回 `ask`；
审批不可用时框架把 ask 转为拒绝，写操作被结构化拒绝、绝不静默执行）；
UI 提交经认证路由 `POST /api/debrief/mutate`（人工确认 = 弹窗提交 + 删除二次确认）。
每次写操作由内核记入 `user_actions` 审计（payload 为完整请求 JSON）。

| 工具                       | CLI                                | 参数                                                                  | 结果                                                            |
| -------------------------- | ---------------------------------- | --------------------------------------------------------------------- | --------------------------------------------------------------- |
| `debrief_holding_add`      | `holdings add --json`（stdin）     | `{market,symbol,name?,quantity,cost}`                                 | `{id,market,symbol,name,quantity,cost}`                         |
| `debrief_holding_update`   | `holdings update --json`（stdin）  | `{id 或 market+symbol, quantity?,cost?}`（至少一个字段）              | `{id,status:'updated'}`                                         |
| `debrief_holding_remove`   | `holdings remove --json`（stdin）  | `{id 或 market+symbol}`                                               | `{id,status:'removed'}`                                         |
| `debrief_watchlist_add`    | `watchlist add --json`（stdin）    | `{market,symbol,name?,targetPrice?,alert?}`                           | `{id,market,symbol,name,targetPrice,alert}`（alert=存储开关值） |
| `debrief_watchlist_update` | `watchlist update --json`（stdin） | `{id 或 market+symbol, targetPrice?,alert?}`（targetPrice=null 清除） | `{id,status:'updated'}`                                         |
| `debrief_watchlist_remove` | `watchlist remove --json`（stdin） | `{id 或 market+symbol}`                                               | `{id,status:'removed'}`                                         |

错误码：重复 `DEBRIEF_CONFLICT`（如 `holding US:QQQ already exists (id 2)`）、
未找到 `DEBRIEF_NOT_FOUND`、参数错 `DEBRIEF_USAGE`；审批被拒
`DEBRIEF_APPROVAL`（审批不可用 `DEBRIEF_APPROVAL_UNAVAILABLE`）。
注意 `id 或 market+symbol` 是互斥选择：两者都给或都不给 = `DEBRIEF_ARGS`。

## HTTP 路由（认证，仅 owner cookie）

| 路由                                            | 方法 | 说明                                                                          |
| ----------------------------------------------- | ---- | ----------------------------------------------------------------------------- |
| `/api/debrief/dashboard?range=30\|90\|200\|365` | GET  | 投资组合聚合（只读）                                                          |
| `/api/debrief/instruments?market=&query=`       | GET  | 选标搜索（只读；弹窗选标器数据源）                                            |
| `/api/debrief/mutate`                           | POST | `{entity:holding\|watchlist, action:add\|update\|remove, payload}` → 内核写入 |

## 稳定错误码

| 错误码                                              | 含义                                             |
| --------------------------------------------------- | ------------------------------------------------ |
| `DEBRIEF_ARGS`                                      | 参数缺失或 payload 不合 schema                   |
| `DEBRIEF_TIMEOUT`                                   | 内核调用超时                                     |
| `DEBRIEF_CLI_NOT_FOUND`                             | 找不到 CLI（检查 cliPath）                       |
| `DEBRIEF_CLI_NOT_EXECUTABLE`                        | CLI 不可执行                                     |
| `DEBRIEF_EXEC`                                      | 内核执行失败                                     |
| `DEBRIEF_PARSE`                                     | stdout 不是合法 JSON                             |
| `DEBRIEF_BAD_PAYLOAD`                               | envelope 结构未知                                |
| `DEBRIEF_OUTPUT_TOO_LARGE`                          | stdout 超过 8MiB                                 |
| `DEBRIEF_ABORTED`                                   | 调用被取消                                       |
| `DEBRIEF_USAGE` / `DEBRIEF_NOT_FOUND`               | 内核命令用法错误 / 记录不存在                    |
| `DEBRIEF_CONFLICT`                                  | 记录已存在或被并发修改（重复添加/陈旧更新）      |
| `DEBRIEF_TELEGRAM_UNCONFIGURED`                     | Telegram 未配置（缺 token 或 chat id）           |
| `DEBRIEF_FX_UNAVAILABLE`                            | 汇率源不可用（可用 `DEBRIEF_FX_<CCY>` 离线兜底） |
| `DEBRIEF_APPROVAL` / `DEBRIEF_APPROVAL_UNAVAILABLE` | 审批被拒 / 审批不可用，写操作被拒绝              |

---

## Read tools (interactive sessions)

All tools mirror the kernel CLI. Output is a UTF-8 JSON envelope
`{ ok: true, schemaVersion, data } | { ok: false, schemaVersion, error: { code, message } }`;
failures carry a non-zero exit and a structured error object. The plugin checks
required arguments before execution and validates write payloads against their
shapes; violations return `DEBRIEF_ARGS`.

| Tool                   | Parameters                             | CLI                                                                     |
| ---------------------- | -------------------------------------- | ----------------------------------------------------------------------- |
| `debrief_holdings`     | `status?`, `refresh?`                  | `holdings --json [--status open] [--refresh] [--no-refresh]`            |
| `debrief_transactions` | `ticker?`, `limit?`, `offset?`         | `transactions --json [--ticker X] [--limit N] [--offset N]`             |
| `debrief_watchlist`    | `refresh?`                             | `watchlist --json [--refresh] [--no-refresh]`                           |
| `debrief_instruments`  | `market`, `query`                      | `instruments search --market <m> --query <q> --json`                    |
| `debrief_report`       | `id?`, `market?`                       | `report latest --json` / `report --id <id> --json`                      |
| `debrief_memory`       | `query` (or `compactCandidates: true`) | `memory search --query <q> --json` / `memory compact-candidates --json` |
| `debrief_analyze`      | `market`, `refresh?`                   | `analysis prepare --market <m> --json [--refresh] [--no-refresh]`       |
| `debrief_jobs`         | —                                      | `job list --json`                                                       |
| `debrief_dashboard`    | `range?`, `refresh?`                   | `dashboard --json [--range N] [--refresh] [--no-refresh]`               |
| `debrief_news`         | `limit?`, `refresh?`, `notify?`        | `news latest --json [--limit N] [--no-refresh] [--notify]`              |
| `debrief_telegram`     | `action: test\|status`                 | `notify test --json` / `notify status --json`                           |

Read commands refresh stale quotes live by default (`--refresh` forces all,
`--no-refresh` reads the cache only); quote caches older than
`PRICE_STALE_SECONDS` (default 120 s) count as stale. The dashboard payload
carries the `fx` block that powers the Portfolio page currency switcher.

## Whitelisted write tools (scheduled skill sessions only)

Each write tool description declares: “Whitelisted write tool for scheduled
debrief skill sessions; every write is recorded in the kernel user_actions
audit ledger.” Writes enter the kernel `user_actions` audit and the idempotent
job state machine. Interactive writes (add holding / watchlist) are a v2 feature.

| Tool                           | Payload → CLI (stdin JSON) → Result                                                                                                                              |
| ------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `debrief_report_create`        | `{ market, title, summary, fullText?, metrics?, chart?, jobId? }` → `report create --json` → `{ id, status }`                                                    |
| `debrief_memory_compact_write` | `{ topic, instruments[], summary, evidenceRefs[{docId,quote?}], timeRange{from,to}, confidence?, caveats? }` → `memory compact-write --json` → `{ id, version }` |
| `debrief_memory_add`           | `{ sourceType, content, instruments[], occurredAt? }` → `memory add --json` → `{ docId }`                                                                        |

## v2 edit tools (approval-gated; conversation and UI share one implementation)

The six edit tools and the Portfolio modal execute the same Host operation
(UserActions single-implementation pattern). Agent-initiated writes pass the
DSH approval confirmation flow first (`tools/pre-execute` returns `ask`; without
approval support the framework turns the ask into a denial, so the write is
refused with a structured error and never executes silently). UI submits go
through the authenticated route `POST /api/debrief/mutate` (the human
confirmation is the modal submit plus the double-confirm removal). Every write
is recorded in the kernel `user_actions` audit with the full request payload.

| Tool                       | CLI (stdin JSON)          | Parameters                                                               | Result                                                              |
| -------------------------- | ------------------------- | ------------------------------------------------------------------------ | ------------------------------------------------------------------- |
| `debrief_holding_add`      | `holdings add --json`     | `{market,symbol,name?,quantity,cost}`                                    | `{id,market,symbol,name,quantity,cost}`                             |
| `debrief_holding_update`   | `holdings update --json`  | `{id \| market+symbol, quantity?,cost?}` (≥1 field)                      | `{id,status:'updated'}`                                             |
| `debrief_holding_remove`   | `holdings remove --json`  | `{id \| market+symbol}`                                                  | `{id,status:'removed'}`                                             |
| `debrief_watchlist_add`    | `watchlist add --json`    | `{market,symbol,name?,targetPrice?,alert?}`                              | `{id,market,symbol,name,targetPrice,alert}` (alert = stored switch) |
| `debrief_watchlist_update` | `watchlist update --json` | `{id \| market+symbol, targetPrice?,alert?}` (`targetPrice:null` clears) | `{id,status:'updated'}`                                             |
| `debrief_watchlist_remove` | `watchlist remove --json` | `{id \| market+symbol}`                                                  | `{id,status:'removed'}`                                             |

Errors: duplicates → `DEBRIEF_CONFLICT` (e.g. `holding US:QQQ already exists
(id 2)`), missing → `DEBRIEF_NOT_FOUND`, bad args → `DEBRIEF_USAGE`; approval
denied → `DEBRIEF_APPROVAL` (`DEBRIEF_APPROVAL_UNAVAILABLE` when approval is
missing). `id` and `market+symbol` are mutually exclusive selectors: giving
both or neither is `DEBRIEF_ARGS`.

## HTTP routes (authenticated, owner cookie only)

| Route                                           | Method | Purpose                                    |
| ----------------------------------------------- | ------ | ------------------------------------------ |
| `/api/debrief/dashboard?range=30\|90\|200\|365` | GET    | Portfolio aggregate (read-only)            |
| `/api/debrief/instruments?market=&query=`       | GET    | Instrument search (picker data source)     |
| `/api/debrief/mutate`                           | POST   | `{entity, action, payload}` → kernel write |

## Stable error codes

| Code                                                | Meaning                                                                   |
| --------------------------------------------------- | ------------------------------------------------------------------------- |
| `DEBRIEF_ARGS`                                      | Missing argument or payload not matching the schema                       |
| `DEBRIEF_TIMEOUT`                                   | Kernel call timed out                                                     |
| `DEBRIEF_CLI_NOT_FOUND`                             | CLI not found (check cliPath)                                             |
| `DEBRIEF_CLI_NOT_EXECUTABLE`                        | CLI not executable                                                        |
| `DEBRIEF_EXEC`                                      | Kernel execution failed                                                   |
| `DEBRIEF_PARSE`                                     | stdout is not valid JSON                                                  |
| `DEBRIEF_BAD_PAYLOAD`                               | Unknown envelope structure                                                |
| `DEBRIEF_OUTPUT_TOO_LARGE`                          | stdout exceeded 8 MiB                                                     |
| `DEBRIEF_ABORTED`                                   | Call cancelled                                                            |
| `DEBRIEF_USAGE` / `DEBRIEF_NOT_FOUND`               | Kernel command usage error / record missing                               |
| `DEBRIEF_CONFLICT`                                  | Record exists or was modified concurrently (duplicate add / stale update) |
| `DEBRIEF_TELEGRAM_UNCONFIGURED`                     | Telegram not configured (missing token or chat id)                        |
| `DEBRIEF_FX_UNAVAILABLE`                            | FX provider unavailable (`DEBRIEF_FX_<CCY>` env overrides work offline)   |
| `DEBRIEF_APPROVAL` / `DEBRIEF_APPROVAL_UNAVAILABLE` | Approval denied / approval unavailable — write refused                    |
