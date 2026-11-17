name: debrief-profile
description: 投资记忆摘要技能：读取现有摘要与内核证据包 → 六段合成带引用要点 → 幂等写回（profile write）→ 播报变更 diff。三模式：每日刷新/重生成（只用 profile get 的证据包、保护 user 段）、提问（只读，允许 memory 检索）、更新（用户原话改写目标段并沉淀证据）。Investment memory profile: read the current digest and the kernel evidence package, synthesize six cited sections, write back idempotently, and announce the diff. Three modes: daily refresh/regenerate (evidence package only, protect user-edited sections), Q&A (read-only, memory search allowed), update (apply the user's own words and sediment evidence).
whenToUse: 触发条件：DSH Schedule「投资记忆摘要」任务交付（03:30 Asia/Shanghai），用户要求「重新生成投资记忆摘要」，用户在摘要卡提问，或用户提交「更新我的投资画像」并给出原话。When the daily profile schedule task is delivered, the user asks to regenerate the digest, asks questions from the digest card, or submits an update with their own words.

# debrief-profile · 投资记忆摘要

把内核证据包（活跃长期记忆主题 + 交易纪律原文 + 持仓/成交结构 + 近期决策文档）压缩成一张**给人看**的六段画像（投资组合 / 交易习惯 / 纪律与规则 / 风险画像 / 操作建议 / 关键决策）。你是摘要的唯一生成方（内核无 LLM）。生成必须幂等、可溯源、不写实时数字。

## 触发条件 / When to use

- 定时任务每日 03:30 交付（记忆压缩 02:30 完成之后 1 小时），做每日刷新。
- 用户要求「重新生成投资记忆摘要」。
- 用户在摘要卡提问（只读模式）或提交更新（更新模式）。

## 三种模式 / Modes

- **刷新/重生成（默认，定时任务）**：全量重建六段。生成输入**只准用** `debrief_profile` 返回的 `evidence` 证据包；`updatedBy='user'` 的段落原样保留（写回带 `protectUserSections`）。
- **提问**：只读。`debrief_profile` 读摘要 + `debrief_memory` 检索记忆回答问题；禁止任何写工具。
- **更新**：把用户原话更新进摘要：判断目标段落 → 仅改目标段落 → 写回 profile → `debrief_memory_add` 沉淀本次原话为证据。不调用 `debrief_memory` 做生成输入。

## 步骤 / Steps

1. **读现状**：调用 `debrief_profile`（内核映射 `profile get --json`）→ `{ version, generated, updatedAt, sections, markdown, evidenceRefs, discipline, evidence }`。`sections` 六段（key：portfolio/habits/discipline/risk/advice/decisions），每段带 `updatedBy`（user/agent）与 `updatedAt`。
2. **取证据（仅刷新/重生成）**：**只使用第 1 步返回的 `evidence` 证据包**——内核预组装：活跃长期主题摘要清单（各带 evidence_refs 的 docId）、`trading_discipline` 原文（= `discipline` 字段）、持仓/成交结构快照、近期非 feedback/run 决策文档。**禁止调用 `debrief_memory` 自由检索做生成输入**（`debrief_memory` 仅提问模式可用）；这同时切断「重生成读到自己的写入审计」循环。可选：读 `debrief_jobs` 确认最近一次「每日记忆压缩」状态，失败则播报警告，但仍以证据包为准生成，不阻塞。
3. **合成**：逐段按内容规范生成 2-5 条要点：
   - 每条 ≤50 字、末尾带 `[[cite:doc:<id>]]`；docId 只能来自证据包内主题自带的 evidence_refs；
   - 段落正文**禁止**价格/净值/市值/盈亏/股数/涨跌幅数字；只写结构、纪律、偏好与日期（规则阈值与日期允许）；
   - 证据不足的段写「暂无足够证据（截至日期）」，不静默留空；
   - `updatedBy='user'` 的段落**跳过本步**，原样保留；
   - discipline 段以 `discipline` 字段原文为准，逐字引用、不发挥、不解释。
4. **写回**：调用 `debrief_profile_write`（内核映射 `profile write --json`，stdin）：
   - `sections` = 本次要写的段（部分更新，只含非 user 段），元素 `{key, content}`（updatedBy 由内核按调用方派生：本技能经 `debrief_profile_write` 工具调用 → agent；不要在 payload 里带 updatedBy，内核会拒绝）；
   - `evidenceRefs` = 本次用到的 docId 全集（**整体替换**，≤64 条，元素 `{docId}`）；
   - `expectedVersion` = 第 1 步读到的 version（CAS；冲突返回 DEBRIEF_CONFLICT → 重读现状后重试一次）；
   - `protectUserSections: true`（内核强制 agent 不覆盖 user 段，响应 `preserved` 列出被保护段）；
   - 与现摘要无任何变化则不写（内核 noop：不 bump 不审计），播报「无变化」。
5. **播报 diff**：更新了哪几段、每段依据（docId/主题名）、保留的 user 段、写回版本号（格式见下）。

## IRON 约束 / Iron rules

- **IRON RULE 1**：白名单写：`debrief_profile_write` 只在本技能内使用；更新模式额外允许 `debrief_memory_add`（仅沉淀用户本次原话）。提问模式**零写**。本技能是白名单直写（writeKind='profileWrite'，无审批门——03:30 无人值守必须能写）；全部写入内核 `user_actions` 审计。
- **IRON RULE 2**：无证据不写。每条要点必须带 `[[cite:doc:<id>]]`；docId 只能来自 `debrief_profile` 返回的证据包；引用不存在的 docId 会被内核拒绝（DEBRIEF_VALIDATION），是最高严重度违规。
- **IRON RULE 3**：user 段落保护。`updatedBy='user'` 的段落在刷新/重生成时字节级原样保留——不重写、不润色、不加引用、不重新排版；写回带 `protectUserSections=true` 由内核强制兜底。
- **IRON RULE 4**：幂等。同一证据包生成同一文本；写回带 `expectedVersion` CAS，冲突重读重试一次；连续两次刷新 diff 必须为空（内核 noop 兜底）。
- **IRON RULE 5**：不写实时数字。段落正文禁止价格/净值/市值/盈亏/股数/涨跌幅；只写结构、纪律、偏好与日期；规则阈值数字（首笔≤1/3、权重>75% 红线）允许。
- **IRON RULE 6**：不越界。不得调用 `debrief_memory_compact_write`（不得创建/更新/退役长期主题）；不得沉淀决策（那是 compact/weekly 的职责）；更新模式只沉淀用户本次原话；刷新/更新模式不得调用 `debrief_memory` 检索。
- **IRON RULE 7**：失败不静默。写回失败报错误码（DEBRIEF_CONFLICT / DEBRIEF_VALIDATION / DEBRIEF_INTERNAL）并保留原状态（内核幂等状态机兜底）；播报单列失败原因。

## user 手改段落保护 / User-edited section semantics

- 刷新/重生成：user 段**原样保留（字节级）**，不写不碰；内核 `protectUserSections` 强制兜底（响应 `preserved` 列段名）。
- 更新模式：用户原话经本技能写入目标段（updatedBy 由内核判定为 agent）。为防后续刷新丢内容，**必须**同步 `debrief_memory_add` 沉淀原话（sourceType=conversation、逐字引用、instruments=涉及标的）——原话进入证据包后，后续刷新会带着引用重新生成该要点。
- 用户在内联编辑区的直改走 UI 路由（updatedBy='user'），不经本技能；本技能永不覆盖。

## 输出格式 / Output format

```text
投资记忆摘要 · 刷新（YYYY-MM-DD HH:mm）
更新段落：
- portfolio：+1 条（依据 doc 3441）
- decisions：滚动窗口 +1（依据 doc 2982）
保留段落：discipline（updatedBy=user，原样未动）
未动段落：habits / risk / advice
写回：version 7 → 8（noop=false）
```

提问模式输出：

```text
投资记忆 · 回答（只读）
结论：……
- …… [[cite:doc:<id>]]（摘要已知）
- …… [[cite:doc:<id>]]（检索补充）
未知：……（摘要与检索均无记录，不推断）
```

更新模式输出：

```text
投资记忆摘要 · 更新
目标段落：discipline
原文：……
新文：……（保留原要点，+1 条用户原话）
证据沉淀：docId 3052（sourceType=conversation）
其余段落：未动
写回：version 8 → 9
```
