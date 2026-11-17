name: debrief-news
description: 每4小时新闻摘要技能：读取内核采集的新闻原文流，压缩成要点式摘要，在会话内播报并推送到 Telegram。Every-4h news digest: read the kernel-collected raw news feed, compress it into a concise bullet digest, announce it in the session, and push the digest to Telegram.
whenToUse: 触发条件：DSH Schedule 每4小时新闻任务交付，或用户要求「扫一下最新消息」。When the 4-hourly news schedule task is delivered, or the user asks for a quick news sweep.

# debrief-news · 每4小时新闻摘要

内核负责抓取新闻原文（APScheduler 兜底轮询 + `debrief_news` 调用时实时拉取，无摘要，也不再自动推送原始新闻流）；你负责阅读 + 压缩成要点，并在会话内播报、推送到 Telegram。

## 触发条件 / When to use

- 定时任务每4小时交付（Asia/Shanghai）。
- 用户主动要求新闻扫描。

## 步骤 / Steps

1. **读取**：调用 `debrief_news`（可选 `limit`；默认实时拉取，`refresh: false` 只读最近一批），拿到最新新闻条目（title/source/publishedAt/url/summary，含新增计数 `newCount`）。相关性过滤由你完成——内核不再提供 `market` 过滤参数。
2. **筛选**：只保留与组合持仓、监察表标的、已关注板块相关的条目；无相关条目时直接在会话内播报「无相关新闻」，并且**不推送 Telegram**。
3. **压缩**：每条 ≤1 行要点，去重合并同一事件的多来源报道，标注来源与时间。
4. **会话播报**：在会话内输出要点列表（格式见下）。若某条新闻触发了记忆中的纪律条件（可用 `debrief_memory` 检索核对），明确指出「触发观察」并给出原纪律的 `[[cite:doc:<id>]]`。
5. **Telegram 推送**：当本轮有新增相关条目时，调用 `debrief_telegram`（`action: "send"`，`text` = 同一份摘要的 markdown 版本）推送到 Telegram。text 要求：`**加粗**` 分区标题、`- ` 要点列表、`[来源](https://url)` 可点击链接（内核自动转成 Telegram HTML 并分段）；每条要点 ≤1 行，链接必须可跳转。无新增相关条目时不调用 send（避免噪音）。

## IRON 约束 / Iron rules

- **IRON RULE 1**：不写库。本技能没有白名单写工具，不得调用任何 debrief 写工具。`debrief_telegram` 的 `send` 是通知发送、不是写库，允许使用。
- **IRON RULE 2**：不得扩写新闻为分析结论；只做压缩与相关度判断，结论性解读留给盘后分析技能。
- **IRON RULE 3**：新闻事实只能来自 `debrief_news` 返回条目，不得引入记忆或外部来源当作新闻。
- **IRON RULE 4**：禁止推送原始新闻条目：不要用 `debrief_news` 的 `notify: true`（旧行为，推的是未加工的原始条目）；Telegram 只接收本技能生成的摘要。

## 输出格式 / Output format

会话播报与 Telegram 推送共用同一份要点文本；Telegram 版用 markdown（加粗/列表/链接）：

```text
📰 新闻摘要 · MM-DD HH:MM（每4小时）

【美股】QQQ
- 要点一句话（来源，HH:MM）[华尔街见闻](https://wallstreetcn.com/...)
- …

【A股】
- …

触发观察：…… / 无
```

要求：简洁（每条 ≤1 行）、按市场分区、来源可点击跳转；无相关新闻时仅会话内播报「无相关新闻」。
