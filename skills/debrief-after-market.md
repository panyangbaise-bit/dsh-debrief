name: debrief-after-market
description: 盘后分析技能：为单一市场（美股/A股/港股/加密）打包行情、新闻与记忆候选，生成结构化盘后结论并写回内核报告中心。After-market analysis for one market (us/cn/hk/crypto): prepare quotes, news, and memory candidates, synthesize a structured conclusion, and write it back to the kernel report center.
whenToUse: 触发条件：DSH Schedule 盘后任务交付（美股 次日 05:30 / A股 15:30 / 港股 16:45 / 加密 08:00，Asia/Shanghai），或用户说「做一下 XX 盘后分析」「复盘今天」。When a scheduled after-market task is delivered, or the user asks for a market's after-market review.

# debrief-after-market · 盘后分析

本技能把一个市场的盘后分析变成「内核打包 → 你生成结论 → 写回内核」三步闭环。你（DSH agent）是唯一的模型层，内核不生成任何结论。

## 触发条件 / When to use

- 定时任务 prompt 指明市场（us / cn / hk / crypto）。
- 用户要求对某个市场做盘后分析、复盘。

## 步骤 / Steps（严格按序）

1. **打包**：调用 `debrief_analyze`，参数 `market` = 目标市场。拿到输入包：`jobId`、`preparedAt`、`inputs.quotes`（行情快照）、`inputs.news`（新闻原文）、`inputs.memoryCandidates`（记忆候选，带 topic/summary）、`guidance`。
2. **阅读**：完整读完输入包。行情看涨跌幅与量能变化；新闻只采用输入包内出现的事实；记忆候选用于对齐历史判断（建仓理由、纪律约束）。
3. **生成结论**：你自己综合，输出结构化结论（格式见下）。不得调用其他数据源或编造输入包之外的数据。
4. **写回**：调用 `debrief_report_create`，参数：
   - `market` = 目标市场；
   - `title` = 简短标题（如「盘后分析 · 2026-11-11」）；
   - `summary` = 一句话总结 / 关键变化 / 组合影响 / 是否触发操作信号（四段）；
   - `fullText`（可选）= 完整分析正文；
   - `metrics`（可选）= `[{label, value}]` 指标行（波动率、换手、关注度、风险等级）；
   - `chart`（可选）= `{title, unit, points}`（输入包或内核提供的数据点，抽样 ≤365 点）；
   - `jobId` = 步骤 1 拿到的 jobId（必传，关联 job_runs 台账）。
5. **汇报**：调用 `debrief_jobs` 确认本次 job 状态；把结论摘要讲给用户（或写入任务会话消息）。

## IRON 约束 / Iron rules

- **IRON RULE 1**：`debrief_report_create` 是白名单写工具，只在本技能（或定时会话）内使用；写操作会自动进入内核 `user_actions` 审计，不得隐藏、绕过或分拆调用。
- **IRON RULE 2**：结论只能依据输入包内的事实；引用记忆时必须带 `[[cite:doc:<id>]]` 原始文档 id，不得改写记忆原意。
- **IRON RULE 3**：必须把步骤 1 的 `jobId` 原样传给 `debrief_report_create`；缺失时先重新 prepare，不得编造 jobId。
- **IRON RULE 4**：不写库、不动持仓与自选；结论只呈现 + 写报告，交互写工具是 v2 能力，本技能一律不用。

## 输出格式 / Output format

先写一行**数据边界**：报价时点与是否处于交易时段、记忆候选是否命中（未命中要写明）、新闻是否跨市场。

```text
数据边界：……
一句话总结：……
关键变化：1) …… 2) ……
组合影响：……
操作信号：无 / 触发（说明触发哪条纪律或条件）
```

报告 `summary` 直接使用上述四段结构。
