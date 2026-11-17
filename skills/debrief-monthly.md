name: debrief-monthly
description: 月度复盘技能（每月 1 日 09:00）：打包月度交易、报告、任务与长期记忆，输出月度复盘、沉淀月度级决策，并向 Telegram 推送精简月度复盘。Monthly review (1st of each month, 09:00): package the month's trades, reports, jobs, and long-term memory, produce a monthly review, sediment month-level decisions, and push a concise digest to Telegram.
whenToUse: 触发条件：DSH Schedule 每月 1 日 09:00（Asia/Shanghai）交付，或用户要求做月度复盘。When the monthly schedule task is delivered, or the user asks for a monthly review.

# debrief-monthly · 月度复盘

月度总账：在周复盘基础上，多一层长期记忆对齐与策略级审视，最后推送精简月度复盘。

## 触发条件 / When to use

- 定时任务每月 1 日 09:00 交付。
- 用户说「做月度复盘」「这个月总结」。

## 步骤 / Steps

1. **打包数据**：与周复盘一致——`debrief_holdings`、`debrief_transactions`（本月）、`debrief_report`（各市场，含本月 weekly 报告）、`debrief_jobs`。
2. **长期记忆对齐**：`debrief_memory` 检索月度级主题（「月度策略」「仓位结构」「风险预算」），先看长期摘要再补短期证据；把本月表现与历史长期结论对照。
3. **输出月度复盘**：结构见下，会话内完整呈现。
4. **决策沉淀**：仅本月**策略级**决策（仓位上限调整、市场配置变化、纪律修订）调用 `debrief_memory_add`（`sourceType` = `decision`），逐字引用原结论并带 `[[cite:doc:<id>]]`。
5. **写回报告**：`debrief_report_create`，`market` = `monthly`，`title` = 「月度复盘 · YYYY-MM」，`summary` = 复盘结论；`metrics` = 月收益、月胜率、任务成功率、记忆命中数。
6. **Telegram 推送**：写回成功后，调用 `debrief_telegram`（`action: "send"`，`text` = 精简月度复盘，格式见下）。要求：
   - 总长 ≤700 字、正文尽量 ≤12 行；只推精简版，不推完整报告。
   - `**加粗**` 分区标题、`- ` 要点列表；引用外部来源时用 `[来源名](url)` 可点击链接，URL 必须来自本次实际数据，没有来源就不附链接、不编造。
   - `[[cite:doc:<id>]]` 改写成「记忆#<id>」或省略，不要输出原始 token。
   - 推送失败不影响报告落库；如实说明即可。

## IRON 约束 / Iron rules

- **IRON RULE 1**：白名单写（`debrief_memory_add` / `debrief_report_create`）只在本技能内使用；全部写入内核 `user_actions` 审计。`debrief_telegram` 的 `send` 是通知发送、不是写库，允许使用。
- **IRON RULE 2**：月度复盘不得复读周复盘原文；必须给出月级别的增量结论（趋势、结构、策略有效性）。
- **IRON RULE 3**：长期记忆检索结果必须引用 `[[cite:doc:<id>]]`；找不到对应主题就写「无历史对照」，不得虚构。
- **IRON RULE 4**：不沉淀的事务性总结只写进报告，不写记忆。
- **IRON RULE 5**：Telegram 只推精简月度复盘（格式见下），禁止原样转发报告 `summary` / `fullText`；推送内容必须与报告一致。

## 输出格式 / Output format

### 会话内（完整版）

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

### Telegram（精简版，markdown；内核自动转成 Telegram HTML）

```text
📊 月度复盘 · 2026-11

一句话：……
**月度交易**：X 笔；盈亏 ……；胜率 ……
**仓位结构**：……（与上月对比）
**策略有效性**：……（记忆#docId，无历史对照写明）
**任务健康**：成功 n / 失败 m（错误码 …）
**下月计划**：……
决策沉淀：新增 n 条 / 无
```

要求：简洁（≤700 字）、分区加粗、要点列表；有来源链接时必须可点击跳转。
