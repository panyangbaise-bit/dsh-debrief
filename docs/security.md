# Security · 安全

> English follows the Chinese section.

## 边界

- **密钥零落地**：全部模型调用在 DSH；DeepSeek Key 只存在于 DSH 一侧。内核无模型调用、无 Key；插件不接触任何模型凭据。
- **只读优先**：交互会话只有只读工具；3 个白名单写工具仅供定时 skill 会话使用，写操作入内核 `user_actions` 审计。
- **无命令注入**：工具参数经 schema 校验后以 argv 数组（非 shell）传给 `spawn`，不拼接 shell 字符串；payload 以 JSON 走 stdin。
- **认证路由**：`/api/debrief/dashboard` 走 `ctx.connection.fetch`（签名 cookie + Host/Origin fence + 仅 owner Peer），插件不自建弱认证。
- **无第三方 UI 依赖**：浏览器端 React 取自宿主模块表；npm 产物无第三方运行时依赖（`npm pack` 审计见 §6.5）。

## 依赖与供应链

- 零运行时依赖；devDependencies 仅 typescript / vitest / eslint / prettier。
- 发布前手动跑 `npm audit` / `npm pack --dry-run` 审计依赖与产物（仓库不含 CI 流水线）。

## 报告漏洞

请勿公开披露。发送到 SECURITY.md 中的联系方式，我们会在 48 小时内响应。

## 已知限制

- 内核 CLI 的可信度 = 进程身份：插件不校验 CLI 二进制签名，部署方应保证 `cliPath` 指向可信内核（服务账户、文件权限）。
- token/session cookie 丢失 = 实例权限丢失：轮换 = 重启 dsh。
- 白名单写工具在 DSH 层不做会话来源强校验（判断来源不是工具的职责）；审计链由内核 `user_actions` 保证。

---

## Boundaries

- **Zero key storage**: all model calls run in DSH; the DeepSeek key exists
  only on the DSH side. The kernel makes no model calls and the plugin never
  touches model credentials.
- **Read-first**: interactive sessions expose read tools only; the 3 whitelisted
  write tools are for scheduled skill sessions, and every write enters the
  kernel `user_actions` audit.
- **No command injection**: validated arguments are passed to `spawn` as an
  argv array (never a shell string); write payloads travel as JSON on stdin.
- **Authenticated route**: `/api/debrief/dashboard` goes through
  `ctx.connection.fetch` (signed cookie + Host/Origin fence + owner-only Peer);
  the plugin builds no weaker auth of its own.
- **No third-party UI dependencies**: browser-side React comes from the host
  module table; the npm artifact has no third-party runtime dependencies
  (`npm pack` audit, §6.5).

## Dependencies & supply chain

- Zero runtime dependencies; devDependencies are typescript / vitest / eslint /
  prettier only.
- `npm audit` / `npm pack --dry-run` run manually before each release (this repository ships no CI pipeline).
  renovate/dependabot.

## Reporting a vulnerability

Do not disclose publicly. Use the contact in SECURITY.md; we respond within 48
hours.

## Known limitations

- Kernel CLI trust equals process identity: the plugin does not verify the CLI
  binary signature; operators must keep `cliPath` pointing at a trusted kernel
  (service account, file permissions).
- Losing the token/session cookie loses the instance: rotate by restarting dsh.
- The whitelisted write tools do not hard-verify the calling session's origin at
  the DSH layer (that judgement is not a tool's job); the audit chain is
  guaranteed by the kernel `user_actions` ledger.
