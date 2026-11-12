# FAQ · 常见问题

> English follows the Chinese section.

## 内核是什么？为什么不做成 DSH 原生服务？

内核是去 Agent 后的数据域（SQLite + 采集 + CLI）。设计决策：DSH 是唯一模型层；
内核保持无模型、无 Key，让交互问答与定时任务共用同一套 agent 与 session log（唯一 trace）。

## 每个工具调用都要起 subprocess，不慢吗？

冷启动约 0.5–1.5s，简单、无状态、崩溃隔离，符合「一条命令可验证」的原则。
常驻 daemon（unix socket + JSON-line）是 P4 可选优化。

## 为什么要 3 个白名单写工具？

盘后分析/记忆压缩/决策沉淀需要把 DSH agent 生成的结论写回内核（报告、长期记忆、证据快照）。
写操作入 `user_actions` 审计、走幂等 job 状态机；交互会话的写（添加持仓/自选）是 v2 能力。

## 为什么没有 zod / 为什么 devDeps 只有四项？

发布门槛是「零运行时第三方依赖」。类型安全由 TypeScript strict + 内置的
迷你 schema 校验模块保证（tests 覆盖），devDependencies 刻意收敛为
typescript / vitest / eslint / prettier。

## 为什么 client 是单文件、不能 import？

Web Host 只服务导出的 `./client` URL；内部 import 会 404。因此浏览器端一个
文件自包含，React 从宿主模块表 `require('react')` 获取。

## 定时任务失败了怎么办？

失败不静默：job 台账写错误码 + 任务会话内播报；`new_once` 串行交付，
错过时段只补最新一次；重跑 `debrief-setup` 幂等。

## 为什么投资组合（Portfolio）路由不走 webServer.register？

inspect 到的现行契约：`webServer.register` 的 resource 不带 Peer、不做认证；
`ctx.connection.fetch` 是经签名 cookie + Host/Origin fence 准入的认证 exact route。
安全优先，采用后者（已记录偏差）。

## 支持哪些市场？

us（美股）/ cn（A股）/ hk（港股）/ crypto（加密）。报告 market 额外支持
`weekly` / `monthly`（周/月复盘）。

## 支持什么语言？

工具描述为英文（模型面向）；UI 卡片、页面、技能内容、文档均为中英双语；
客户端 locale 缺省回退 zh。

## 旧 LangGraph trace 怎么办？

按设计直接 drop（drop 前 `VACUUM INTO` 备份一次）；DSH session log 是唯一
agent trace；决策/证据由记忆快照承载，记忆本体不动。详见
[storage-retention.md](storage-retention.md)。

---

## What is the kernel? Why not a native DSH service?

The kernel is the de-agentized data domain (SQLite + collection + CLI). Design
decision: DSH is the only model layer; the kernel stays model-free and key-free,
so interactive chat and scheduled tasks share one agent and one session log
(the only trace).

## A subprocess per tool call — isn't that slow?

Cold start is ~0.5–1.5s: simple, stateless, crash-isolated, and one command is
verifiable end to end. A resident daemon (unix socket + JSON lines) is an
optional P4 optimization.

## Why three whitelisted write tools?

After-market analysis, memory compaction, and decision sedimentation must write
DSH-generated conclusions back to the kernel (reports, long-term memory,
evidence snapshots). Writes enter the `user_actions` audit and an idempotent job
state machine; interactive writes (add holding / watchlist) are a v2 feature.

## Why no zod? Why only four devDependencies?

The release gate is “zero runtime third-party dependencies”. Type safety comes
from TypeScript strict plus a tiny built-in schema validator (test-covered);
devDependencies are deliberately typescript / vitest / eslint / prettier.

## Why is the client a single import-free file?

The Web Host serves only the exported `./client` URL; internal imports would 404. The browser half is therefore self-contained and takes React from the host
module table via `require('react')`.

## A scheduled task failed — now what?

Failures are never silent: the job ledger records the error code and the task
session announces it; `new_once` delivers serially and only the latest missed
occurrence is delivered; re-running `debrief-setup` is idempotent.

## Why doesn't the Portfolio route use webServer.register?

The inspected contracts show that `webServer.register` resources carry no Peer
and no authentication, while `ctx.connection.fetch` is the authenticated exact
route (signed cookie + Host/Origin fence). Security wins; the deviation is
documented.

## Which markets are supported?

us / cn (A-shares) / hk / crypto. Report `market` additionally accepts
`weekly` / `monthly` for reviews.

## Which languages?

Tool descriptions are English (model-facing); cards, the page, skills, and docs
are bilingual zh/en; the client locale falls back to zh.

## What happens to the legacy LangGraph traces?

Dropped outright per the design (one `VACUUM INTO` backup first); the DSH
session log is the only agent trace; decisions and evidence live in memory
snapshots which are untouched. See [storage-retention.md](storage-retention.md).
