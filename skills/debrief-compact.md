name: debrief-compact
description: 每日记忆压缩技能：取超窗候选 → 按主题分组 → 生成带证据引用的结构化长期摘要 → 幂等写回（compact-write）→ 决策沉淀（memory add）。Daily memory compaction: take out-of-window candidates, group them by topic, synthesize structured long-term summaries with evidence citations, write them back idempotently, and sediment decisions.
whenToUse: 触发条件：DSH Schedule 每日记忆压缩任务交付（02:30 Asia/Shanghai），或短期记忆超过阈值时用户手动触发。When the daily compaction schedule task is delivered, or the user triggers compaction manually.

# debrief-compact · 每日记忆压缩

短期记忆窗口外的证据快照被压缩成带引用的长期摘要；你是唯一的摘要生成方（内核无 LLM）。压缩必须幂等、可溯源。

## 触发条件 / When to use

- 定时任务每日 02:30 交付。
- 用户要求「压缩记忆」。

## 步骤 / Steps

1. **取候选**：调用 `debrief_memory`，参数 `compactCandidates: true`（内核映射 `memory compact-candidates --json`）。候选 = 超出短期窗口（默认 30 天）且未压缩的 `memory_documents`，每条带 docId/topic/instruments/sourceType/content。内核已排除 `run` 源类型的任务执行日志（prices/reminders/news 台账），这些不是投资记忆。
2. **分组**：按 `topic` 分组（source_type + instrument 或语义聚类）；每批 ≤30 条；批内读每条原文与 docId。
3. **生成摘要**：每个 topic 一组，模板固定（见输出格式）。摘要必须引用原始 docId（`[[cite:doc:<id>]]`），不得改写原意；时间范围取组内最早/最晚。
4. **幂等写回**：对每组调用 `debrief_memory_compact_write`：
   - `topic` = 组主题（同 topic 已存在时内核自动 version+1 重压缩）；
   - `instruments` = 组内关联标的；
   - `summary` = 结构化摘要；
   - `evidenceRefs` = `[{docId, quote?}]`，docId 必须来自候选集；
   - `timeRange` = `{from, to}`；
   - `confidence` = high/medium/low（依据证据完整度自评）；
   - `caveats` = 已知局限与未知。
5. **决策沉淀**：候选里属于**决策**的条目（决策/交易类），同步 `debrief_memory_add` 沉淀为可检索快照（内容带原文与 docId 引用）。
6. **汇报**：输出压缩统计（组数、覆盖 docId 列表、写回的 id/version）。

## IRON 约束 / Iron rules

- **IRON RULE 1**：白名单写（`debrief_memory_compact_write` / `debrief_memory_add`）只在本技能内使用；全部写入内核 `user_actions` 审计。
- **IRON RULE 2**：`evidenceRefs.docId` 只能来自候选集；引用不存在的 docId 是最高严重度违规（可溯源性是压缩的根基）。
- **IRON RULE 3**：每批 ≤30 条；超了就继续分组，不得合并不同主题。
- **IRON RULE 4**：不得删除、丢弃候选原文；写回失败要报错误码并保留原状态（内核幂等状态机兜底，失败不静默）。
- **IRON RULE 5**：摘要不含任何候选之外的新事实；置信度必须如实标注。
- **IRON RULE 6**：`run` 源类型的任务执行日志、写操作审计副本不是投资记忆，不得压缩进长期记忆；发现这类候选应跳过并计入统计说明。

## 输出格式 / Output format

```text
长期记忆 · <topic>
结论：……
理由：…… [[cite:doc:<id>]] [[cite:doc:<id>]]
条件：……
时间范围：from ~ to
置信度：high/medium/low
局限：……
```
