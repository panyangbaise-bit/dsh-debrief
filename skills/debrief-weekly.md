name: debrief-weekly
description: 周复盘技能（周六 09:00）：打包本周交易、报告、任务与记忆，输出周度复盘并把本周决策沉淀进短期记忆。Weekly review (Saturday 09:00): package the week's trades, reports, jobs, and memory, produce a weekly review, and sediment this week's decisions into short-term memory.
whenToUse: 触发条件：DSH Schedule 周六 09:00（Asia/Shanghai）交付，或用户要求做周复盘。When the Saturday schedule task is delivered, or the user asks for a weekly review.

# debrief-weekly · 周复盘

每周一次的总账：数据打包 → 复盘输出 → 决策沉淀写回。

## 触发条件 / When to use

- 定时任务每周六 09:00 交付。
- 用户说「做周复盘」「总结这周」。

## 步骤 / Steps

1. **打包数据**：
   - `debrief_holdings`（现状）；`debrief_transactions`（本周成交，注意时间过滤）；
   - `debrief_report`（各市场最新报告：us/cn/hk/crypto 各读一次）；
   - `debrief_jobs`（本周任务台账，确认定时任务健康度与失败项）。
2. **记忆对齐**：用 `debrief_memory` 检索本周纪律关键词（如「止盈」「止损」「仓位上限」），核对本周操作是否与历史纪律一致。若本周有用户投资问答（conversation 类）尚未沉淀，先补 `debrief_memory_add`（sourceType=conversation，逐字引用）。
3. **输出周复盘**：结构化输出（格式见下），并在会话内完整呈现。
4. **决策沉淀**：对本周**实际做出的决策**（买/卖/调仓/放弃操作/纪律更新），每条调用一次 `debrief_memory_add`：
   - `sourceType` = `decision`（交易类用 `trade`）；
   - `content` = 决策原文 + 理由 + 条件（尽量逐字引用当时的会话结论）；
   - `instruments` = 关联标的；
   - `occurredAt` = 决策时间。
     没有新决策则跳过本步，绝不重复沉淀历史决策。
5. **写回报告**：调用 `debrief_report_create` 写入周复盘报告：`market` = `weekly`，`title` = 「周复盘 · YYYY-Www」，`summary` = 复盘结论四段，`metrics` 可选（周收益、成交笔数、任务成功率）。

## IRON 约束 / Iron rules

- **IRON RULE 1**：`debrief_memory_add` / `debrief_report_create` 是白名单写工具，只在本技能内使用；写操作自动进入内核 `user_actions` 审计。
- **IRON RULE 2**：决策沉淀必须可溯源——内容里保留会话原句与 `[[cite:doc:<id>]]` 引用；编造决策是最高严重度违规。
- **IRON RULE 3**：只沉淀本周决策；本周无决策就明确写「本周无新决策」，不得把历史记忆重写一遍（幂等性）。
- **IRON RULE 4**：失败的任务要写出错误码（来自 `debrief_jobs`），不要静默。

## 输出格式 / Output format

```text
周复盘 · YYYY-Www（时间范围）
一句话总结：……
交易：买入 X 笔 / 卖出 Y 笔，本周盈亏 ……
纪律核对：……（逐条：遵守 / 偏离 + 证据 doc id）
任务健康：成功 n / 失败 m（错误码 …）
下周观察：……
决策沉淀：新增 n 条（docId …）/ 无
```
