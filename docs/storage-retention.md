# Storage & retention · 存储与保留策略

> English follows the Chinese section.

本文档描述内核侧（debrief 数据域）的存储与保留策略；插件本身不落任何数据，
DSH session log 的持久化/保留/备份由 DSH 自理。

## Trace 分工

| 层                | Trace 载体                                                | 策略                                                                  |
| ----------------- | --------------------------------------------------------- | --------------------------------------------------------------------- |
| DSH（唯一 agent） | DSH session log（交互 + Schedule 定时任务会话的事件日志） | 唯一 trace；插件不重复记录                                            |
| debrief 内核      | `job_runs` 任务台账                                       | 可配置保留 `JOB_RUN_RETENTION_DAYS=365`，分批 `DELETE ... LIMIT` 清理 |
| debrief 内核      | 旧 LangGraph trace 表                                     | 直接 drop（drop 前 `VACUUM INTO` 备份一次；不回填、不兼容）           |

报告与图表（`financial_reports`/`analysis_charts`）是产出而非 trace，保留
`REPORT_RETENTION_DAYS=3650`。审计 ≠ trace：写操作入 `user_actions`（业务审计，永久保留）。

## 长短期记忆

| 层   | 载体                                                | 窗口                                      | 内容                          |
| ---- | --------------------------------------------------- | ----------------------------------------- | ----------------------------- |
| 短期 | `memory_documents` + `memory_chunks`（FTS5 可检索） | `MEMORY_SHORT_TERM_DAYS=30` 或最近 500 条 | 原始证据快照                  |
| 长期 | `long_term_memories`                                | 永久                                      | 压缩后的结构化摘要 + 证据引用 |

压缩流程（`debrief-compact` 技能每日执行）：

1. 候选 = 超窗未压缩的 `memory_documents`（`archived_into IS NULL`）。
2. 按 topic 分批（≤30 条/批）。
3. DSH agent 生成固定模板摘要，引用原始 docId。
4. `debrief_memory_compact_write` 落库（同 topic version+1）；原文 `archived_into=id`。
5. 原文默认保留（退出短期检索范围）；`MEMORY_ARCHIVE_DELETE=true` 时删除正文仅留指针。
6. 幂等：`memory_compaction_runs` 状态机（pending/running/done/failed+retry）；失败不影响读取。

## SQLite 运维（内核侧）

- `journal_mode=WAL`、`auto_vacuum=INCREMENTAL`；清理后 `PRAGMA incremental_vacuum(N)`。
- `VACUUM INTO` 做每日备份；备份源 `/var/lib/debrief/portfolio.db`（0600）。
- 每次清理返回删除行数/耗时，写入 `job_runs`，可观测。

## 容量与膨胀治理

- 旧 trace 表直接删除；台账保留清理；记忆压缩 + 决策沉淀（证据不丢）。
- DSH 侧（session log、输出保留）由 DSH 自身管理，纳入备份与磁盘监控。

---

This document describes the kernel-side (debrief data domain) storage and
retention policy; the plugin persists nothing itself, and DSH session log
persistence/retention/backup belongs to DSH.

## Trace split

| Layer                | Trace carrier                                     | Policy                                                                           |
| -------------------- | ------------------------------------------------- | -------------------------------------------------------------------------------- |
| DSH (the only agent) | DSH session log (interactive + schedule sessions) | The only trace; the plugin never duplicates it                                   |
| debrief kernel       | `job_runs` ledger                                 | Configurable retention `JOB_RUN_RETENTION_DAYS=365`, batched `DELETE ... LIMIT`  |
| debrief kernel       | Legacy LangGraph trace tables                     | Dropped outright (one `VACUUM INTO` backup first; no backfill, no compatibility) |

Reports and charts (`financial_reports`/`analysis_charts`) are outputs, not
traces: `REPORT_RETENTION_DAYS=3650`. Audit ≠ trace: writes enter
`user_actions` (business audit, kept forever).

## Long/short-term memory

| Layer      | Carrier                                     | Window                | Content                                         |
| ---------- | ------------------------------------------- | --------------------- | ----------------------------------------------- |
| Short-term | `memory_documents` + `memory_chunks` (FTS5) | 30 days or latest 500 | Raw evidence snapshots                          |
| Long-term  | `long_term_memories`                        | Forever               | Compressed structured summaries + evidence refs |

Compaction (`debrief-compact` skill, daily): out-of-window uncompressed
candidates → topic batches (≤30) → fixed-template summaries with docId
citations → `debrief_memory_compact_write` (version+1 per topic) → originals
marked `archived_into=id` (deleted only when `MEMORY_ARCHIVE_DELETE=true`).
Idempotent via the `memory_compaction_runs` state machine; failures never break
reads.

## SQLite operations (kernel side)

- `journal_mode=WAL`, `auto_vacuum=INCREMENTAL`, `PRAGMA incremental_vacuum(N)`
  after cleanups; daily `VACUUM INTO` backups; data dir 0600.
- Cleanups report deleted rows and duration into `job_runs`.

## Capacity governance

- Legacy trace tables dropped; ledger retention cleanup; memory compaction +
  decision sedimentation (evidence is never lost).
- DSH-side growth (session log, output retention) is managed by DSH itself and
  covered by backup and disk monitoring.
