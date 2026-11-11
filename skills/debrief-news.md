name: debrief-news
description: 每小时新闻摘要技能：读取内核采集的新闻原文流，压缩成要点式摘要并在会话内播报。Hourly news digest: read the kernel-collected raw news feed, compress it into a bullet digest, and announce it in the session.
whenToUse: 触发条件：DSH Schedule 每小时整点新闻任务交付，或用户要求「扫一下最新消息」。When the hourly news schedule task is delivered, or the user asks for a quick news sweep.

# debrief-news · 每小时新闻摘要

内核 APScheduler 负责抓取新闻原文（无摘要）；你负责阅读 + 压缩成要点。摘要只在会话内呈现。

## 触发条件 / When to use

- 定时任务每小时交付（整点后 5 分钟，Asia/Shanghai）。
- 用户主动要求新闻扫描。

## 步骤 / Steps

1. **读取**：调用 `debrief_news`（可选 `market`、`limit`），拿到最新新闻条目（title/source/at）。
2. **筛选**：只保留与组合持仓、监察表标的、已关注板块相关的条目；无相关条目时直接播报「无相关新闻」。
3. **压缩**：每条 ≤1 行要点，去重合并同一事件的多来源报道，标注来源与时间。
4. **播报**：在会话内输出要点列表。若某条新闻触发了记忆中的纪律条件（可用 `debrief_memory` 检索核对），明确指出「触发观察」并给出原纪律的 `[[cite:doc:<id>]]`。

## IRON 约束 / Iron rules

- **IRON RULE 1**：不写库。本技能没有白名单写工具，不得调用任何 debrief 写工具。
- **IRON RULE 2**：不得扩写新闻为分析结论；只做压缩与相关度判断，结论性解读留给盘后分析技能。
- **IRON RULE 3**：新闻事实只能来自 `debrief_news` 返回条目，不得引入记忆或外部来源当作新闻。

## 输出格式 / Output format

```text
📰 新闻要点（HH:MM 更新）
· [美股] …（来源，时间）
· [A股] …（来源，时间）
触发观察：…… [[cite:doc:<id>]] / 无
```
