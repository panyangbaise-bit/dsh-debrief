# debrief CLI — 命令与 JSON Schema 参考 / Command & JSON Schema Reference

> 内核 = 纯数据域（无 Agent、无 LLM）；模型与多轮对话全部在 DSH 一侧。
> The kernel is data-only (no agent, no LLM); all model work lives in DSH.

## 0. 总览 / Overview

- 入口：console script `debrief`（`debrief.cli:main`），也可 `python -m debrief`。
- 每个命令在 **stdout 打印恰好一行 UTF-8 JSON envelope**，成功返回 `0`，用法错误返回 `2`，运行时错误返回 `1`。
- 数据库：`--db <path>`（可选，置于子命令之前）＞ `DATABASE_URL` 环境变量 ＞ 仓库根 `portfolio.db`。首次打开自动执行幂等迁移（等价于 `debrief migrate`）。
- 写命令（`report create` / `memory compact-write` / `memory add`）从 **stdin** 读取单个 JSON 对象。
- `--json` 标志在所有命令上接受（envelope 始终为 JSON，标志为兼容占位）。
- stderr 静默策略：CLI 单次调用按 WARNING 级输出（迁移等 INFO 日志不刷屏，插件错误路径可读）；仅 `worker` 常驻命令恢复 INFO 运维日志。

```
成功: {"ok": true,  "schemaVersion": 1, "data": {...}}
失败: {"ok": false, "schemaVersion": 1, "error": {"code": "DEBRIEF_XXX", "message": "..."}}
```

| 领域 | 命令                                                                                  |
| ---- | ------------------------------------------------------------------------------------- |
| 组合 | `holdings` · `transactions` · `watchlist` · `dashboard`                               |
| 选标 | `instruments search`                                                                  |
| 报告 | `report latest` · `report --id` · `report create`                                     |
| 记忆 | `memory search` · `memory compact-candidates` · `memory compact-write` · `memory add` |
| 任务 | `analysis prepare` · `job list/start/status/finish`                                   |
| 运维 | `migrate` · `worker`                                                                  |

错误码表 / Error codes：`DEBRIEF_USAGE`（参数/命令错误，exit 2）、`DEBRIEF_ARGS`（缺参数）、`DEBRIEF_DB`（库不可用）、`DEBRIEF_NOT_FOUND`、`DEBRIEF_JOB_ALREADY_RUNNING`（分析防重入）、`DEBRIEF_VALIDATION`（stdin JSON 校验失败）、`DEBRIEF_FX_UNAVAILABLE`（汇率缺失）、`DEBRIEF_INTERNAL`。DSH 插件侧还会补充 `DEBRIEF_TIMEOUT` / `DEBRIEF_CLI_NOT_FOUND` / `DEBRIEF_PARSE` / `DEBRIEF_BAD_PAYLOAD`（见 dsh-debrief/index.js）。

---

## 1. holdings

```bash
debrief holdings [--status open] [--json]
```

```json
{
  "asOf": "2026-11-11 22:35",
  "currency": "CNY",
  "totalMarketValue": 282770.72,
  "dayPnl": -7766.49,
  "dayPnlPct": -2.67,
  "totalPnl": 20953.66,
  "totalPnlPct": 7.69,
  "positions": [
    {
      "market": "CC",
      "symbol": "HYPE",
      "name": "HYPE",
      "quantity": 20.0,
      "cost": 38.0,
      "price": 41.2,
      "marketValue": 824.0,
      "pnlPct": 8.42,
      "weight": 1.94
    }
  ]
}
```

- `positions[].market` ∈ `US|CN|HK|CC`；`totalMarketValue/dayPnl/totalPnl` 均为 CNY（汇率来自 open.er-api.com，可用 `DEBRIEF_FX_USD=7.2 DEBRIEF_FX_HKD=0.92` 离线覆盖）。
- `price` = `price_cache` 最新收盘（缺失时回退成本价）；`dayPnl` 用最新两个快照价差；`totalPnl` 含已清仓实现盈亏。
- `--status open` 为兼容占位（默认即只含 open 持仓）。

## 2. transactions

```bash
debrief transactions [--ticker AAPL] [--limit 20] [--offset 0] [--json]
```

```json
{
  "total": 48,
  "limit": 20,
  "offset": 0,
  "items": [
    {
      "time": "2026-11-08 09:32",
      "side": "buy",
      "market": "US",
      "symbol": "AAPL",
      "name": "苹果",
      "quantity": 50,
      "price": 182.4,
      "amount": 9120.0,
      "status": "filled"
    }
  ]
}
```

- 按时间倒序；`--ticker` 精确匹配 symbol（大小写不敏感）；`limit` 默认 20 上限 100；`total` = 过滤后总数。
- `status` 恒为 `filled`（台账只记录已成交）。
- 包含已清仓/归档持仓的历史成交。

## 3. watchlist

```bash
debrief watchlist [--ticker 00700] [--json]
```

```json
{
  "count": 1,
  "items": [
    {
      "market": "HK",
      "symbol": "00700",
      "name": "腾讯控股",
      "price": 412.8,
      "changePct": 0.6,
      "targetPrice": 380.0,
      "distancePct": 8.6,
      "alert": false
    }
  ]
}
```

- `targetPrice` 取 `target_price_low`（缺失用 high）；`changePct` 用最近两次快照价差（数据不足为 null）；
- `alert` = 现价已触及关注价（`price <= targetPrice`）。`price/distancePct` 在缺价时为 null。

## 4. instruments search

```bash
debrief instruments search --market <us|cn|hk|crypto> --query <Q> [--json]
```

```json
{
  "query": "maotai",
  "market": "cn",
  "source": "akshare catalog (daily sync) + eastmoney suggest fallback",
  "items": [
    { "market": "CN", "symbol": "600519", "name": "贵州茅台", "currency": "CNY", "assetClass": "stock", "held": true }
  ]
}
```

- 排序：精确代码 ＞ 代码前缀 ＞ 精确名称 ＞ 名称前缀 ＞ 子串（含拼音别名）。
- 股票：本地 `instrument_catalog`（worker 每日同步 akshare 列表）＋ 东财 suggest 兜底（60 次/分限流、进程内 15 分钟缓存）；加密：CoinGecko（目录 `/coins/list` 同步 + 实时 `/search` 兜底）。上游不可用自动回退本地目录。
- `held` 仅当该标的在 open 持仓中时出现且为 true。`--query` 至少 2 字符。

## 5. report latest / --id / create

```bash
debrief report latest [--market us] [--json]
debrief report --id rpt-2026-11-11-us [--json]
```

```json
{
  "id": "rpt-2026-11-11-us",
  "market": "US",
  "title": "盘后分析",
  "generatedAt": "2026-11-11 18:00",
  "summary": "三大指数收涨……",
  "fullText": "风险提示：……",
  "metrics": [{ "label": "波动率", "value": "18.6%" }],
  "chart": { "title": "60 日走势", "unit": "", "points": [100.0, 101.2, 103.4] }
}
```

- 无匹配报告 → `DEBRIEF_NOT_FOUND`。`chart` 无图时为 `null`；`fullText` 可为 `null`。

```bash
echo '{"market":"us","title":"盘后分析","summary":"…","fullText":"…","metrics":[{"label":"波动率","value":"18.6%"}],"chart":{"title":"60 日走势","unit":"","points":[1,2,3]},"jobId":42}' \
  | debrief report create --json
# → {"ok":true,"schemaVersion":1,"data":{"id":"rpt-2026-11-11-us","status":"succeeded"}}
```

- 必需：`market/title/summary`；可选 `fullText/metrics[]/chart/jobId`。
- 落 `analysis_reports` + `analysis_charts`（`chart_id` 关联）；写 `user_actions` 审计（`report.create`）。
- 带 `jobId`：对应 `job_runs` 置 `succeeded` 并回填 `report_id`（返回 `status:"succeeded"`）；job 不存在 → `DEBRIEF_NOT_FOUND`。

## 6. memory search

```bash
debrief memory search --query <Q> [--json]
```

```json
{
  "query": "aapl",
  "items": [
    {
      "layer": "long",
      "topic": "建仓理由 · AAPL",
      "instruments": ["US:AAPL"],
      "confidence": "high",
      "timeRange": "2026-03 ~ 2026-05",
      "summary": "建仓基于生态护城河……",
      "evidence": [{ "docId": 12, "date": "2026-03-18", "label": "建仓决策", "quote": "……计划首批建仓 50 股……" }]
    },
    {
      "layer": "short",
      "topic": "decision · US:AAPL",
      "instruments": ["US:AAPL"],
      "confidence": "high",
      "timeRange": "2026-11-11",
      "summary": "……",
      "evidence": [{ "docId": 6, "date": "2026-11-11", "label": "…", "quote": "…" }]
    }
  ]
}
```

- 检索顺序：先 `long_term_memories`（命中即给摘要 + 证据引用）→ 后 FTS5 短期证据（`memory_documents.archived_into IS NULL`）。
- 被压缩的短期条目不再直接出现（通过其长期摘要 + `docId` 引用可溯源）。

## 7. memory compact-candidates

```bash
debrief memory compact-candidates --json
```

```json
{
  "batches": [
    {
      "topic": "decision:CN:600519",
      "items": [
        { "docId": 34, "content": "交易 买入……", "occurredAt": "2026-03-01T08:00:00", "instruments": ["CN:600519"] }
      ]
    }
  ],
  "pendingCount": 150
}
```

- 候选 = 超窗（`MEMORY_SHORT_TERM_DAYS=30`，或超出 `MEMORY_SHORT_TERM_MAX=500` 的最旧条目）且未压缩（`archived_into IS NULL`）。
- 按 `topic`（source_type + 首个标的）分批，每批 ≤ `MEMORY_COMPACT_BATCH=30`；`content` 截断至 2000 字符。

## 8. memory compact-write

```bash
echo '{"topic":"position-aapl-rationale","instruments":["US:AAPL"],"summary":"……",
       "evidenceRefs":[{"docId":12,"quote":"……"}],
       "timeRange":{"from":"2026-03-01","to":"2026-05-01"},
       "confidence":"high","caveats":"……"}' \
  | debrief memory compact-write --json
# → {"ok":true,"schemaVersion":1,"data":{"id":1,"version":1}}
```

- 必需：`topic/summary/evidenceRefs(非空)/timeRange{from,to}`；可选 `confidence(high|medium|low)/caveats/instruments`。
- 同 topic 已存在 → `version+1` 重压缩合并（证据按 docId 去重合并、时间窗取并集）。
- 原文标记 `archived_into/archived_at`；`MEMORY_ARCHIVE_DELETE=true` 时额外删除分块与正文。
- `memory_compaction_runs` 状态机（pending→running→done/failed+retry）：写入失败回滚业务数据、只留 failed 运行记录，不影响读取。
- 写 `user_actions` 审计（`memory.compact_write`）。

## 9. memory add

```bash
echo '{"sourceType":"decision","content":"建仓理由：……","instruments":["US:AAPL"],"occurredAt":"2026-11-11T10:00:00"}' \
  | debrief memory add --json
# → {"ok":true,"schemaVersion":1,"data":{"docId":6}}
```

- 必需：`sourceType`（≤40 字符）/`content`；可选 `instruments[]/occurredAt`（ISO 时间）。
- 证据快照入 `memory_documents`（自引用 `source_id`）并**立即入 FTS5**（无需等待 indexer）；写 `user_actions` 审计（`memory.add`）。

## 10. analysis prepare

```bash
debrief analysis prepare --market <us|cn|hk|crypto> [--json]
```

```json
{
  "market": "us",
  "preparedAt": "2026-11-10 15:30",
  "jobId": 2048,
  "inputs": {
    "quotes": [{ "symbol": "AAPL", "name": "苹果", "price": 189.5, "changePct": 0.4 }],
    "news": [{ "title": "……", "at": "2026-11-10 14:20", "source": "财联社" }],
    "memoryCandidates": [{ "topic": "建仓理由 · AAPL", "summary": "……" }]
  },
  "guidance": "基于以上 美股 行情、新闻与记忆候选，输出结构化盘后结论：……"
}
```

- 副作用：创建 `job_runs`（`after-market-<market>`，running）。同市场已有 running → `DEBRIEF_JOB_ALREADY_RUNNING`（防重入锁）。
- DSH agent 分析后经 `report create {jobId}` 写回并关闭 job。

## 11. job list / start / status / finish

```bash
debrief job list [--limit 50] [--json]
debrief job start --kind after-market-us [--json]          # → {"id":7,"status":"running"}
debrief job status --id 7 [--json]
debrief job finish --id 7 --status done|failed [--error-code E] [--json]
```

```json
{
  "items": [{ "id": 7, "kind": "盘后分析 · 美股", "at": "2026-11-09 18:00", "status": "succeeded", "durationSec": 42 }]
}
```

- `kind` 中文标签来自 `KIND_LABELS`（after-market-us→盘后分析 · 美股、weekly-review→周复盘、prices→价格采集……；未知 kind 原样显示）。
- 内部状态 `completed/skipped` 对外归一化为 `succeeded`；`errorCode` 仅失败时出现。
- `finish` 幂等：对已终态 job 返回现有状态；`done→succeeded`、`failed→failed`。

## 12. dashboard

```bash
debrief dashboard [--range 30|90|200|365] [--json]
```

```json
{
  "kpis": {"totalAssets": 1234567, "currency": "CNY", "dayPnl": 15120, "dayPnlPct": 1.24,
           "totalPnl": 95860, "totalPnlPct": 8.42, "annualPct": 12.6},
  "series": {"range": 90, "equity": [1000000, ...], "returns": [0.0, ...]},
  "composition": [{"name": "贵州茅台", "value": 21.0}],
  "holdings": [/* 同 §1 positions */],
  "watchlist": [/* 同 §3 items */]
}
```

- 数据源 = `holdings` + `price_cache` 日快照聚合（按 ticker carry-forward）；`returns[i] = equity[i]/equity[0]-1`；`annualPct` = 序列年化（不足 2 点时回退总收益率）。
- 曲线末端钉住当前组合：若末个快照日期 == 今天（与 `PriceCache.date` 相同的 UTC 日期口径），用当前 `totalAssets` 替换末点；若末日期更早（如新持仓当日无快照行），追加今天数据点（值 = 当前 `totalAssets`）——`equity[-1]` 恒等于 `kpis.totalAssets`；无任何快照时保留单点 = 当前总资产。`returns`/`annualPct` 基于钉住后的序列重算。
- 抽样上限 = range（30/90/200/365）：点数超限时等距抽样，且首末点必保留。

## 13. migrate

```bash
debrief migrate --json
# → {"ok":true,"schemaVersion":1,"data":{"db":"sqlite:///…/portfolio.db","applied":[],"totalMigrations":19}}
```

- 幂等；`applied` = 本次新应用的版本（空 = 已最新）。
- 完成：drop 旧 trace 表（drop 前一次性 `VACUUM INTO pre-agent-removal-backup.db` 留档）、`user_actions` 去 FK 重建、`analysis_charts` 改挂 `report_id`、`memory_documents` 增 `archived_into/archived_at`、`long_term_memories`/`memory_compaction_runs`/`instrument_catalog`/`analysis_reports` 建表、`job_runs` 增 `error_code/report_id`、`journal_mode=WAL`、`auto_vacuum=INCREMENTAL`、清理指向被删表的 `memory_checkpoints` 游标；v13 再增 `user_actions.payload` 与 `watchlist_items.alert_enabled`。

## 14. worker

```bash
debrief worker [--dry-run] [--json]
```

- APScheduler 常驻数据采集（**无任何 LLM 调用**）：`prices`（**`*/30 * * * *` 全天每 30 分钟，Asia/Shanghai**，覆盖美股盘后 21:30–04:00、港股尾盘、A 股与加密全天；可用 `PRICES_CRONTAB` 环境变量或 `data/scheduler_settings.json` 的 `prices_crontab` 键覆盖）、`news`（NEWS_CRONTAB，默认 0 8-22/2）、`catalog-sync`（每日 06:10，akshare 列表 + CoinGecko /coins/list）、`reminders`（*/15 提醒比对 + Telegram 通知）、`cleanup`（每日 03:00，`JOB_RUN_RETENTION_DAYS=365` 分批 DELETE + incremental_vacuum）。
- 上游故障不崩溃：每次运行写 `job_runs`（succeeded / failed + `DEBRIEF_UPSTREAM_*` 错误码）。
- `--dry-run` 打印排程并退出。

---

## 15. Decisions（设计歧义定夺记录 / Design decisions）

| #   | 歧义                                                                                                    | 定夺                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| --- | ------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | 「报告来自 financial_reports/analysis_charts」但原 `financial_reports` 是企业财报（ticker/revenue/eps） | 新增 `analysis_reports` 表承载运行中心报告；`analysis_charts` 重建为 `report_id` 关联；`financial_reports` 保持企业财报语义不动。                                                                                                                                                                                                                                                                                                                       |
| 2   | `analysis prepare` 同市场已有 running 时「复用/拒绝」                                                   | **拒绝**，返回 `DEBRIEF_JOB_ALREADY_RUNNING` 并附已有 job id（复用会让两个会话并发分析同一市场）。                                                                                                                                                                                                                                                                                                                                                      |
| 3   | 加密市场代码                                                                                            | 库内沿用 `CRYPTO`；CLI 输出归一化为 `CC`（与插件 mock 一致），输入接受 `crypto                                                                                                                                                                                                                                                                                                                                                                          | cc`。                                                           |
| 4   | `holdings` 默认范围                                                                                     | 只含 open 持仓（合约渲染当前组合）；`--status open` 保留为兼容占位。                                                                                                                                                                                                                                                                                                                                                                                    |
| 5   | 拼音别名                                                                                                | `pinyin_alias` 由东财 suggest 的 PinYin 机会式填充；akshare 列表不含拼音，不引入额外依赖。                                                                                                                                                                                                                                                                                                                                                              |
| 6   | watchlist `alert`/`changePct`                                                                           | `alert` = 现价已触及 `target_price_low`（或 high）；`changePct` = 最近两个快照价差，数据不足为 null。                                                                                                                                                                                                                                                                                                                                                   |
| 7   | 提醒队列                                                                                                | 本版无独立队列表：`reminders` job 比对后写入 `job_runs.details` + Telegram 通知（可关）；队列表留给 v2。                                                                                                                                                                                                                                                                                                                                                |
| 8   | job id 形态                                                                                             | `job start` 返回 `job_runs.id`（整数），mock 的字符串 id 仅形状同构；`kind` 中文标签见 `KIND_LABELS`。                                                                                                                                                                                                                                                                                                                                                  |
| 9   | `job finish` 对已终态 job                                                                               | 幂等返回现有状态，不报错。                                                                                                                                                                                                                                                                                                                                                                                                                              |
| 10  | 短期检索的置信度                                                                                        | 由 `time_quality` 推导：recorded→high，imported→low（长期条目用压缩时给定的 confidence）。                                                                                                                                                                                                                                                                                                                                                              |
| 11  | 压缩写回失败                                                                                            | 回滚业务写入（不残留半成品长期记忆），仅保留 failed 运行记录 + retry_at 指数退避。                                                                                                                                                                                                                                                                                                                                                                      |
| 12  | dashboard `annualPct`                                                                                   | 序列年化（首尾点/365 天）；序列不足时回退总收益率。                                                                                                                                                                                                                                                                                                                                                                                                     |
| 13  | 汇率                                                                                                    | 运行时 open.er-api.com，支持 `DEBRIEF_FX_<CCY>` 环境变量离线覆盖；缺汇率 → `DEBRIEF_FX_UNAVAILABLE`。                                                                                                                                                                                                                                                                                                                                                   |
| 14  | streamlit 应用                                                                                          | 保留为可选 UI（`[project.optional-dependencies] ui`），但删除推荐/Ask-Agent 页；history 改为成交+审计，operations 改为报告中心+台账。                                                                                                                                                                                                                                                                                                                   |
| 15  | 旧迁移步骤在全新库上                                                                                    | v1/v4/v7/v2/v2b/v2c/v6/v9b 加守卫：目标表/列缺失即记为已应用（no-op），保证 migrate 幂等无告警。                                                                                                                                                                                                                                                                                                                                                        |
| 16  | 写命令市场代码                                                                                          | 内部库沿用历史代码 `US/CN/HK/CRYPTO`（与旧数据一致），响应/目录侧归一为 `US/CN/HK/CC`；`crypto                                                                                                                                                                                                                                                                                                                                                          | cc` 输入均接受，重复判定按库内归一码 + symbol（大小写不敏感）。 |
| 17  | holdings remove / watchlist remove                                                                      | **软删**：复用现有 `status` 字段置 `archived`（与 UI 删除语义一致），台账与记忆证据保留；对已归档行再操作 → `DEBRIEF_NOT_FOUND`。                                                                                                                                                                                                                                                                                                                       |
| 18  | holdings add 台账                                                                                       | 自动补一条 opening buy 交易（notes='opening'），保持账本可重放；`quantity/cost` 直接入 `shares/cost_basis`。                                                                                                                                                                                                                                                                                                                                            |
| 19  | watchlist alert 语义                                                                                    | 新增 `watchlist_items.alert_enabled` 列（v13 迁移，默认 1）。GET `alert` = 开关开启 **且** 现价已触及关注价（`price <= targetPrice`）；写命令返回存储的开关值。targetPrice 映射 `target_price_low`（update 传 null 即清除）。                                                                                                                                                                                                                           |
| 20  | 审计 payload                                                                                            | `user_actions.payload` 列（v13 迁移）存完整请求 JSON（verbatim）；目录自动补全时附 `catalogCurrency`。审计行动词：holding.add/update/remove、watchlist.add/update/remove。                                                                                                                                                                                                                                                                              |
| 22  | slim wheel 的 FX 依赖                                                                                   | CLI 读路径（holdings/dashboard 的 CNY 汇率）需要 `adapters.fx`（requests + domain.markets）。选型：wheel 纳入 adapters 轻量子集（`__init__.py`/`base.py`/`fx.py`），保持与完整安装单一实现，不迁移 FX 代码；市场适配器仍由 worker 懒加载。缺陷复盘：初版 wheel 缺 adapters，在仓库根 cwd 下运行被源码目录 shadow 未暴露——已加「仓库外 cwd + 全新 venv 只装 wheel + PYTHONPATH 清空」的真实场景回归测试。                                                |
| 21  | prices 采集窗口                                                                                         | 默认 `*/30 * * * *`（Asia/Shanghai，全天 48 次/天）：单一 job 覆盖美股盘后（21:30–04:00）/港股尾盘/A 股/加密全天。不做分市场窗口——collect_prices 单 job 遍历全部目标，适配器对闭市市场返回最新可得价（休市/节假日天然安全），省去四套时区窗口与节假日历复杂度；48 次/天 × 少量目标（当前 6 个）上游调用成本可忽略，`coalesce=True` + `max_instances=1` 防重叠，适配 1.6G 服务器。可经 `PRICES_CRONTAB` 环境变量或 settings 的 `prices_crontab` 键覆盖。 |

## 16. 测试 / Testing

```bash
~/.local/bin/uv venv -p 3.11 .venv-debrief
~/.local/bin/uv pip install -p .venv-debrief/bin/python -e '.[dev,ui]'
.venv-debrief/bin/python -m pytest tests/ -q        # 227 passed, 2 skipped (worker AST 扫描跳过 + Qdrant opt-in)
.venv-debrief/bin/ruff check debrief db scheduler notifier app memory tests runtime.py server.py config.py
```

覆盖：每命令 envelope/schema（`tests/test_debrief_cli.py`）、迁移幂等与旧库 drop 留档（`tests/test_debrief_migration.py`）、job 状态机/压缩写回/审计/目录排名（`tests/test_debrief_storage.py`）、worker 排程与故障容错（`tests/test_debrief_worker.py`）、v2 写命令成功/校验/冲突/未找到/审计（`tests/test_debrief_writes.py`）、dashboard 曲线末端钉住当前总资产与抽样（`tests/test_debrief_dashboard.py`）。测试 fixture 全部由迁移生成的种子库构造，不依赖真实数据与网络。

---

## 17. v2 写命令（holdings / watchlist add|update|remove）/ v2 Write Commands

> 白名单写（v2）：全部从 **stdin** 读取单个 JSON 对象，逐行写 `user_actions` 审计（含完整 payload）。同一进程内事务原子提交；SQLite WAL + busy timeout 处理跨进程并发。写后 `holdings`/`watchlist`/`dashboard` 立即反映。

### holdings add

```bash
echo '{"market":"cn","symbol":"600519","quantity":100,"cost":1450}' \
  | debrief holdings add --json
# → {"ok":true,"schemaVersion":1,"data":{"id":3,"market":"CN","symbol":"600519","name":"贵州茅台","quantity":100.0,"cost":1450.0}}
```

- stdin：`market`（us|cn|hk|crypto|cc，归一输出 US/CN/HK/CC）、`symbol`（必填，存大写）、`name?`、`quantity`（number>0，必填）、`cost`（number>=0，必填）。
- symbol 命中 `instrument_catalog` → 自动补 `name`（审计 payload 附 `catalogCurrency`）；不在目录 → `name` 必填，否则 `DEBRIEF_VALIDATION`。
- 同 (market,symbol) 已存在（非归档行）→ `DEBRIEF_CONFLICT` exit 1。自动补一条 opening buy 交易。

### holdings update

```bash
echo '{"id":3,"quantity":150,"cost":1400}' | debrief holdings update --json
echo '{"market":"cn","symbol":"600519","quantity":150}' | debrief holdings update --json
# → {"ok":true,"schemaVersion":1,"data":{"id":3,"status":"updated"}}
```

- 定位：`{id}` 或 `{market,symbol}`；至少一个 `quantity`(>0)/`cost`(>=0)，全空 → `DEBRIEF_USAGE`；不存在/已归档 → `DEBRIEF_NOT_FOUND`。

### holdings remove

```bash
echo '{"id":3}' | debrief holdings remove --json
echo '{"market":"cn","symbol":"600519"}' | debrief holdings remove --json
# → {"ok":true,"schemaVersion":1,"data":{"id":3,"status":"removed"}}
```

- 软删：`status='archived'`（台账/记忆保留，GET 不再返回）；再操作 → `DEBRIEF_NOT_FOUND`。

### watchlist add

```bash
echo '{"market":"hk","symbol":"00700","name":"腾讯控股","targetPrice":380,"alert":true}' \
  | debrief watchlist add --json
# → {"ok":true,"schemaVersion":1,"data":{"id":2,"market":"HK","symbol":"00700","name":"腾讯控股","targetPrice":380.0,"alert":true}}
```

- stdin：`market/symbol` 必填；`name?`（目录命中自动补）；`targetPrice?`（number>=0 或 null，默认 null → `target_price_low`）；`alert?`（boolean，默认 true → `alert_enabled`）。
- 同 (market,symbol) 已存在 → `DEBRIEF_CONFLICT`。

### watchlist update

```bash
echo '{"id":2,"targetPrice":400}' | debrief watchlist update --json
echo '{"market":"hk","symbol":"00700","alert":false}' | debrief watchlist update --json
# → {"ok":true,"schemaVersion":1,"data":{"id":2,"status":"updated"}}
```

- 定位：`{id}` 或 `{market,symbol}`；至少一个 `targetPrice`（null 可清除）/`alert`，全空 → `DEBRIEF_USAGE`；不存在/已归档 → `DEBRIEF_NOT_FOUND`。

### watchlist remove

```bash
echo '{"id":2}' | debrief watchlist remove --json
# → {"ok":true,"schemaVersion":1,"data":{"id":2,"status":"removed"}}
```

- 软删：`status='archived'`。

### 审计 / Audit

每行 `user_actions`：`action` ∈ holding.add/update/remove、watchlist.add/update/remove；`target_type` ∈ holding/watchlist；`target_id` = 行 id；`payload` = 完整请求 JSON；`acted_at` = UTC 时间。

---

## 18. 打包与分发 / Packaging & Distribution

### 依赖拆分 / Dependency split

- **core**（`[project].dependencies`，CLI 读写命令必需）：`sqlalchemy>=2.0`、`requests>=2.31`、`python-dotenv>=1.0`。
- **collectors extra**（`pip install 'portfolio-agent-kernel[collectors]'`）：`yfinance`、`akshare`、`pycoingecko`、`apscheduler`、`python-telegram-bot`、`pyyaml`、`tomlkit`——`debrief worker` 与数据采集需要。
- **ui extra**：`streamlit`、`plotly`（可选 UI）。
- CLI 路径（debrief/_、db/_、common/_、domain/_、memory/*、config.py）只 import 上述三个 core 依赖；`debrief worker` 的 apscheduler/适配器 import 全部按需加载（`scripts` 目录下的打包测试用 AST + 全新解释器断言锁定）。
- `debrief worker` 缺 collectors 时返回结构化错误（不再裸 ImportError 堆栈）：

```json
{
  "ok": false,
  "schemaVersion": 1,
  "error": {
    "code": "DEBRIEF_MISSING_COLLECTORS",
    "message": "worker needs the collectors extra: pip install 'portfolio-agent-kernel[collectors]' (missing module: apscheduler)"
  }
}
```

### Slim CLI wheel

```bash
# 需要 build/setuptools：uv pip install -p .venv-debrief/bin/python build 'setuptools>=68' wheel
scripts/build_cli_wheel.sh 0.2.2
# → artifacts/portfolio_agent_kernel-0.2.2-py3-none-any.whl（约 65KB，纯 Python）
```

- 只含 CLI 必需模块：`debrief/ db/ common/ domain/ memory/ + config.py + adapters 轻量子集（__init__/base/fx）`；排除 `app/ scheduler/ notifier/` 与其余 adapters（重依赖面）。
- `adapters/fx.py` 是 CLI 读路径（`holdings`/`dashboard` 的 CNY 汇率）唯一需要的适配器层（requests + domain.markets，已具备 core 依赖）；选型 = 纳入轻量子集而非迁移 FX 逻辑，保持 `adapters.fx` 与完整安装单一实现。市场适配器（us/cn/hk/crypto）仍只在 worker 运行时懒加载。
- 验收回归：`tests/test_debrief_packaging.py::test_wheel_install_cli_works_outside_repo` 在**仓库外 cwd + 全新 venv 只装 wheel + PYTHONPATH 清空**下运行 `migrate → holdings add → holdings → dashboard → job list`，并断言 sys.path 不含仓库根（防 cwd shadow 掩盖缺模块缺陷）。
- 轮子内含 console script `debrief`（`debrief.cli:main`）与 `collectors` extra 元数据。
- 版本 0.2.2（与插件对齐）。

### 铁律 / Iron rule

> **wheel 内容一变就必须升版本号，禁止同版本覆盖。** uv/pip 缓存以「wheel 文件名 + 版本」为键：同名同版本覆盖后，缓存过旧包的机器 `--find-links` 会命中旧缓存装出旧内容（加 `--no-cache` 才会正确）。发布新内容 = 递增版本（0.2.0 → 0.2.1 → …），artifacts/ 只保留当前版本单文件。

### 离线安装 / Offline install

```bash
pip install --no-index --find-links artifacts portfolio_agent_kernel
pip install --no-index --find-links artifacts 'portfolio-agent-kernel[collectors]'   # worker 场景（另需完整源码安装提供 adapters/）
```
