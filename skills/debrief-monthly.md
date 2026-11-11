name: debrief-monthly
description: 月度复盘技能（每月 1 日 09:00）：打包月度交易、报告、任务与长期记忆，输出月度复盘并沉淀月度级决策。Monthly review (1st of each month, 09:00): package the month's trades, reports, jobs, and long-term memory, produce a monthly review, and sediment month-level decisions.
whenToUse: 触发条件：DSH Schedule 每月 1 日 09:00（Asia/Shanghai）交付，或用户要求做月度复盘。When the monthly schedule task is delivered, or the user asks for a monthly review.

# debrief-monthly · 月度复盘

月度总账：在周复盘基础上，多一层长期记忆对齐与策略级审视。

## 触发条件 / When to use

- 定时任务每月 1 日 09:00 交付。
- 用户说「做月度复盘」「这个月总结」。

## 步骤 / Steps

1. **打包数据**：与周复盘一致——`debrief_holdings`、`debrief_transactions`（本月）、`debrief_report`（各市场，含本月 weekly 报告）、`debrief_jobs`。
2. **长期记忆对齐**：`debrief_memory` 检索月度级主题（「月度策略」「仓位结构」「风险预算」），先看长期摘要再补短期证据；把本月表现与历史长期结论对照。
3. **输出月度复盘**：结构见下，会话内完整呈现。
4. **决策沉淀**：仅本月**策略级**决策（仓位上限调整、市场配置变化、纪律修订）调用 `debrief_memory_add`（`sourceType` = `decision`），逐字引用原结论并带 `[[cite:doc:<id>]]`。
5. **写回报告**：`debrief_report_create`，`market` = `monthly`，`title` = 「月度复盘 · YYYY-MM」，`summary` = 复盘结论；`metrics` = 月收益、月胜率、任务成功率、记忆命中数。

## IRON 约束 / Iron rules

- **IRON RULE 1**：白名单写（`debrief_memory_add` / `debrief_report_create`）只在本技能内使用；全部写入内核 `user_actions` 审计。
- **IRON RULE 2**：月度复盘不得复读周复盘原文；必须给出月级别的增量结论（趋势、结构、策略有效性）。
- **IRON RULE 3**：长期记忆检索结果必须引用 `[[cite:doc:<id>]]`；找不到对应主题就写「无历史对照」，不得虚构。
- **IRON RULE 4**：不沉淀的事务性总结只写进报告，不写记忆。

## 输出格式 / Output format

```text
月度复盘 · YYYY-MM
一句话总结：……
月度交易：……（笔数、盈亏、胜率）
仓位结构：……（与上月对比）
策略有效性：……（对照长期记忆 doc id）
任务健康：成功 n / 失败 m（错误码 …）
下月计划：……
决策沉淀：新增 n 条（docId …）/ 无
```
