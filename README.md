# dsh-debrief

**After-action portfolio review for DeepSeek Harness.** · **DeepSeek Harness 的持仓复盘插件。**

“Debrief” is the English name for 复盘 (fùpán): the post-market routine of going
back over what happened — positions, trades, watchlist, analysis, and the
decisions behind them — so the next session starts better informed.

“Debrief” 即「复盘」：收盘后回顾持仓、成交、监察表、分析与背后的决策，让下一次决策更有依据。

- **All model work runs in the DSH agent.** The `debrief` kernel is a
  model-free data CLI (SQLite + data collection + JSON commands); this plugin
  bridges it with subprocess calls, renders a card for every tool call, and
  ships a read-only Portfolio page. **全部模型工作都在 DSH agent 内完成**：内核是无模型的数据 CLI，插件只做 subprocess 桥接、工具卡片与只读「投资组合」页面（Portfolio）。
- **20 tools / 工具**：11 个只读工具（`debrief_holdings`、`debrief_transactions`、
  `debrief_watchlist`、`debrief_instruments`、`debrief_report`、`debrief_memory`、
  `debrief_analyze`、`debrief_jobs`、`debrief_dashboard`、`debrief_news`、
  `debrief_telegram`）+ 3 个白名单写工具（`debrief_report_create`、
  `debrief_memory_compact_write`、`debrief_memory_add`，仅供定时 skill 会话使用）+
  6 个 v2 审批门控编辑工具（`debrief_holding_add/update/remove`、
  `debrief_watchlist_add/update/remove`，对话编辑经 DSH 审批确认流，写操作入内核
  `user_actions` 审计）。读取默认实时刷新过期行情；新闻实时拉取；Telegram 推送
  复盘/新闻/提醒（可选配置）。
- **5 scheduled skills / 定时技能**：`debrief-after-market`（盘后分析 ×4 市场）、
  `debrief-news`（每小时新闻摘要）、`debrief-weekly`（周六周复盘）、
  `debrief-monthly`（月度复盘）、`debrief-compact`（每日记忆压缩）。
- **Schedule presets / 任务预置**：`/debrief-setup` 一条命令校验内核并幂等注册
  8 个 DSH Schedule 任务（RRULE 显式 `TZID=Asia/Shanghai`、`new_once` 专属会话）。
- **UI**：keyed `tool.call.toolview` 卡片（持仓/成交/监察表/报告 SVG 图/记忆证据/
  任务进度/运行台账/投资组合/新闻/写回结果）+ 投资组合页面（Portfolio，KPI 行、资产/收益折线、
  成分环形图、持仓表、监察表、时间范围 chips、显示币种 chips CNY/USD/HKD）。v2 起投资组合页面
  支持添加/编辑/删除持仓与自选：市场 chips + 搜索式选标器 + 表单弹窗、删除二次确认、toast 反馈；
  对话侧同名工具走 DSH 审批确认流。持仓/监察表价格带币种单位（A股与基金 CNY、美股与加密 USD、
  港股 HKD），总资产按免费汇率接口准实时切换显示币种。纯 SVG、主题 token、中英双语、IntersectionObserver 懒加载。

## Quick start / 快速开始

```sh
dsh plugin --profile web add dsh-debrief
```

Point the plugin at the kernel CLI in the profile patch (`cordis.patch.yml`, or
the profile's own patch layer) / 在 profile patch 里把插件指向内核 CLI：

```yaml
- id: debrief
  config:
    cliPath: /opt/debrief/bin/debrief # absolute path or PATH name
    timeoutMs: 15000
    # Optional Telegram pushes (reports + news + watchlist alerts):
    # telegram:
    #   botToken: '123456:ABC…'
    #   chatId: '-100…'
```

Reads refresh stale quotes live by default (real-time); the Portfolio page
switches total assets between CNY/USD/HKD using a free FX feed. Telegram is
send-only — check `debrief notify status`, test with `debrief notify test`.
读取默认实时刷新过期行情；投资组合页面支持 CNY/USD/HKD 总资产切换（免费汇率源）。
Telegram 仅发不收 —— `debrief notify status` 查看状态、`notify test` 测试推送。

Then run the setup command once in any session / 然后在任意会话里执行一次安装命令：

```text
/debrief-setup
```

It validates the kernel (`debrief job list --json`) and idempotently registers
every scheduled task; tasks show up on the Schedule page where they can be
paused or deleted. 该命令校验内核后幂等注册全部定时任务，任务出现在 Schedule 页面，可暂停/删除。

The kernel contract is one command in, one JSON envelope out / 内核契约：一条命令进，一个 JSON envelope 出：

```sh
debrief holdings --json
debrief instruments search --market us --query aapl --json
echo '{"market":"us","title":"盘后分析","summary":"…","jobId":"…"}' | debrief report create --json
```

## Local demo (no kernel) / 本地演示（无需内核）

A mock kernel ships in `mock/debrief.js`; point `cliPath` at it to exercise
every tool, card, and the Portfolio page. 仓库自带 `mock/debrief.js` 模拟内核，把 `cliPath` 指向它即可体验全部工具、卡片与投资组合页面。

```yaml
- id: debrief
  config:
    cliPath: /absolute/path/to/dsh-debrief/mock/debrief.js
```

One-shot demo script / 一键演示脚本：

```sh
bash examples/demo.sh
```

## Configuration / 配置

| Field                  | Default                                         | Description / 说明                                                            |
| ---------------------- | ----------------------------------------------- | ----------------------------------------------------------------------------- |
| `cliPath`              | 未设置（managed 自举；external 默认 `debrief`） | Kernel CLI path or PATH name / 内核 CLI 路径（external 模式）                 |
| `kernelMode`           | `auto`                                          | `auto` 显式 cliPath 优先否则自举 / `external` 服务器部署 / `managed` 强制自举 |
| `dataDir`              | `~/.dsh/debrief-runtime`                        | Bootstrap venv data directory / 自举 venv 数据目录                            |
| `withCollectors`       | `false`                                         | Opt-in networked collectors extra / 可选联网安装采集依赖                      |
| `timeoutMs`            | `15000`                                         | Per-call timeout / 单次调用超时                                               |
| `enableSetup`          | `true`                                          | Register the `debrief-setup` command / 注册 `debrief-setup` 命令              |
| `enableDashboardRoute` | `true`                                          | Serve `/api/debrief/dashboard` / 提供投资组合只读路由                         |

**安装即用**：npm 包内置内核 wheel（纯 Python）与离线依赖轮子（`kernel/wheels/`，
约 2.6MB）。机器上有 **uv 或 Python ≥3.11** 时，首次使用（managed /
auto 且未配置 cliPath）会自动在 `~/.dsh/debrief-runtime/` 自举隔离 venv，全部
离线安装；行情采集依赖（collectors）为可选项。服务器部署沿用 external 模式指向
外部 venv。**Installs-and-runs**: the package bundles the kernel wheel (pure
Python) and its offline dependencies under `kernel/wheels/`; with uv or
Python ≥3.11 the first managed use bootstraps an isolated venv offline;
collectors stay optional.

Full reference: [docs/configuration.md](docs/configuration.md) · 完整配置见 [docs/configuration.md](docs/configuration.md)。

## Development / 开发

```sh
npm install
npm run typecheck   # tsc --noEmit (strict)
npm run lint        # eslint 0-warning gate
npm run format:check
npm test            # vitest (61 tests: tool schemas, CLI stdin mapping, envelope, render models, fallbacks)
npm run build       # tsc → dist/index.js + dist/client.js
```

Zero runtime dependencies; React comes from the host module table in the
browser half. Dev dependencies are limited to typescript, vitest, eslint, and
prettier. 零运行时依赖；浏览器端 React 取自宿主模块表；devDependencies 仅
typescript / vitest / eslint / prettier 四项。

## Docs / 文档

- [docs/quickstart.md](docs/quickstart.md) — 快速开始
- [docs/configuration.md](docs/configuration.md) — 配置项
- [docs/tools.md](docs/tools.md) — 每个工具的 JSON Schema 与示例
- [docs/ui.md](docs/ui.md) — 卡片与投资组合页面（Portfolio）规格
- [docs/architecture.md](docs/architecture.md) — 架构（引用设计文档）
- [docs/storage-retention.md](docs/storage-retention.md) — 存储与保留策略
- [docs/remote-access.md](docs/remote-access.md) — 浏览器远程访问
- [docs/security.md](docs/security.md) — 安全边界
- [docs/troubleshooting.md](docs/troubleshooting.md) — 故障排查
- [docs/faq.md](docs/faq.md) — 常见问题

## Kernel / 数据内核

The data kernel (Python, no model, no agent) lives in [`kernel/`](kernel/): the
`debrief` CLI over a local SQLite database, its tests, and the wheels shipped
with the npm package. DSH is the host and the only agent runtime — every model
call happens in a DSH session; the plugin only bridges the kernel over its JSON
CLI. `kernel/` 内置数据内核（Python、无模型、无 Agent）：SQLite 上的 `debrief`
CLI、测试与随包分发的离线轮子；DSH 是宿主与唯一 agent 运行时，插件只通过
JSON CLI 桥接内核。See [`kernel/README.md`](kernel/README.md) and
[`kernel/docs/cli.md`](kernel/docs/cli.md) for the contract and how to rebuild
the wheel.

## Design / 设计

See [`docs/architecture.md`](docs/architecture.md) for this project's
architecture (kernel without agent, DSH session log as the only trace, DSH
Schedule `new_once` for scheduled tasks, owner-only access). 完整架构见
[`docs/architecture.md`](docs/architecture.md)（内核去 Agent、DSH session log
唯一 trace、DSH Schedule `new_once` 定时任务、仅 owner 访问）。

## License

MIT
