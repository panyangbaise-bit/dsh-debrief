# Security Policy · 安全政策

## Supported versions / 支持版本

| Version | Supported |
| ------- | --------- |
| 0.1.x   | ✅        |

## Reporting a vulnerability / 报告漏洞

请勿公开披露（勿发 issue）。请将细节发送至 **opensource-security@example.invalid**，
PGP 公钥见仓库 `SECURITY.md` 更新（如提供）。我们会：

1. 48 小时内确认收到；
2. 7 天内给出初步评估与修复计划；
3. 修复发布前不公开细节；发布后按严重程度在 CHANGELOG 与 advisory 中说明。

Please do **not** disclose publicly (no public issues). Send details to
**opensource-security@example.invalid**. We will acknowledge within 48 hours,
provide an initial assessment and fix plan within 7 days, and keep details
private until a fix ships.

## Scope / 范围

- 插件本体（tools 参数处理、stdin payload、envelope 解析、Dashboard 路由、客户端卡片渲染）。
- 影响内核审计（`user_actions`）或幂等状态机的绕过。
- 供应链问题（npm 产物中的意外文件、密钥泄漏）。

Out of scope / 不在范围：内核（debrief 数据域）自身的问题、DSH 框架问题——分别报给对应仓库。

## Disclosure process / 披露流程

1. Triage within 48h（48 小时内分级）。
2. Fix on a private branch（私有分支修复）。
3. Release + advisory（发布 + 公告）。

## Known accepted risks / 已知可接受风险

见 [docs/security.md](docs/security.md)「已知限制」：CLI 二进制可信度 = 进程身份；
token/cookie 丢失需重启轮换；白名单写工具的会话来源审计由内核 `user_actions` 承担。
