# Troubleshooting · 故障排查

> English follows the Chinese section.

## 卡片显示「读取失败」+ 错误码

| 错误码                       | 含义                     | 处理                                                                           |
| ---------------------------- | ------------------------ | ------------------------------------------------------------------------------ |
| `DEBRIEF_CLI_NOT_FOUND`      | 找不到内核 CLI           | 检查 profile patch 的 `cliPath` 是否为绝对路径或 PATH 名；`which debrief` 验证 |
| `DEBRIEF_CLI_NOT_EXECUTABLE` | CLI 不可执行             | `chmod +x <cliPath>`，确认 shebang 与解释器存在                                |
| `DEBRIEF_TIMEOUT`            | 内核超时                 | 调大 `timeoutMs`；检查内核进程负载                                             |
| `DEBRIEF_PARSE`              | stdout 非 JSON           | 内核版本不匹配插件契约；升级内核或检查命令拼写                                 |
| `DEBRIEF_ARGS`               | 参数/payload 不合 schema | 让 Agent 按工具参数重试；写工具注意必填字段                                    |
| `DEBRIEF_BAD_PAYLOAD`        | envelope 结构未知        | 内核 schema 版本不兼容；升级内核                                               |
| `DEBRIEF_ABORTED`            | 调用被取消               | 正常现象；让 Agent 重试                                                        |

卡片不自行重试——让 Agent 重试即可。

## `/debrief-setup` 失败

1. `kernel check failed: DEBRIEF_CLI_NOT_FOUND` → 见上表。
2. `commands or schedule service unavailable` → 当前 profile 缺服务，检查插件是否在 web profile。
3. 个别任务「注册失败」→ 按报错修正 RRULE（时区必须显式 `TZID=Asia/Shanghai`，DTSTART 必须是该时区的真实本地时间）。
4. 重跑一次即可（幂等：已注册的按标题跳过）。

## Dashboard 页面打不开 / 加载失败

- 页面显示错误码 + 重试按钮：先点重试；持续失败检查内核 `debrief dashboard --json --range 90` 是否能直接跑通。
- 若路由未注册（Host 日志有 `connection service unavailable`），确认 web profile 完整。
- 侧边栏没有「复盘仪表盘」入口：确认 Client 插件加载（页面刷新后查看），slot 注册名 `debrief-dashboard`。

## 定时任务没触发

- 在 Schedule 页面确认任务 active、`scheduledAt` 符合预期（Asia/Shanghai）。
- `new_once` 是串行交付：上一轮没跑完，本轮会排队；错过时段只补最新一次。
- 会话内用 `debrief_jobs` 查看台账：失败项带错误码，按码排查；失败在任务会话内播报，不静默。

## 写工具在交互会话不可用

这是设计行为：3 个写工具只供定时 skill 会话使用；交互写（添加持仓/自选）是 v2 能力。

## 登录/token 问题

- token/cookie 丢失 = 实例权限丢失：重启 `dsh web` 轮换 token，重新登录。
- 远程 403/401：检查 `--trusted-host` 是否含浏览器可见 authority；Caddy basic_auth 与 DSH cookie 两层都要通过。

---

## Card shows “Read failed” + an error code

| Code                         | Meaning                  | Fix                                                               |
| ---------------------------- | ------------------------ | ----------------------------------------------------------------- |
| `DEBRIEF_CLI_NOT_FOUND`      | Kernel CLI missing       | Check `cliPath` in the profile patch; verify with `which debrief` |
| `DEBRIEF_CLI_NOT_EXECUTABLE` | CLI not executable       | `chmod +x <cliPath>`; verify shebang/interpreter                  |
| `DEBRIEF_TIMEOUT`            | Kernel timed out         | Raise `timeoutMs`; check kernel load                              |
| `DEBRIEF_PARSE`              | stdout not JSON          | Kernel/plugin contract mismatch; upgrade the kernel               |
| `DEBRIEF_ARGS`               | Payload fails the schema | Retry with documented arguments                                   |
| `DEBRIEF_BAD_PAYLOAD`        | Unknown envelope         | Schema version mismatch; upgrade the kernel                       |
| `DEBRIEF_ABORTED`            | Call cancelled           | Normal; let the Agent retry                                       |

Cards never retry on their own — ask the Agent to retry.

## `/debrief-setup` fails

1. `kernel check failed: DEBRIEF_CLI_NOT_FOUND` → see above.
2. `commands or schedule service unavailable` → the profile lacks the services;
   check the plugin is loaded in the web profile.
3. One task reports “注册失败” → fix its RRULE (explicit `TZID=Asia/Shanghai`;
   DTSTART must be a real local time in that zone).
4. Re-running is safe — registration is idempotent (existing titles are skipped).

## Dashboard page does not open / fails to load

- Use the in-page retry first; if it persists, run
  `debrief dashboard --json --range 90` directly.
- If the route was not registered (Host log: `connection service unavailable`),
  confirm the web profile is complete.
- Missing sidebar entry: confirm the Client half loaded (refresh the page);
  the panel id is `debrief-dashboard`.

## Scheduled tasks do not fire

- On the Schedule page, confirm the task is active and `scheduledAt` matches
  Asia/Shanghai expectations.
- `new_once` delivers serially: a pending run queues the next; only the latest
  missed occurrence is delivered.
- Check the ledger with `debrief_jobs`: failed rows carry an error code and are
  announced inside the task session — failures are never silent.

## Write tools unavailable in interactive sessions

By design: the 3 write tools are for scheduled skill sessions; interactive
writes (add holding / watchlist) are a v2 feature.

## Login / token issues

- Losing the token/cookie loses the instance: restart `dsh web` to rotate the
  token and log in again.
- Remote 403/401: verify `--trusted-host` names the browser-visible authority;
  both Caddy basic_auth and the DSH cookie must pass.
