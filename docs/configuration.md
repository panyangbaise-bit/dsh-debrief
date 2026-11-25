# Configuration · 配置

> English follows the Chinese section.

插件在 profile patch 层配置（`cordis.patch.yml` 的 `- id: debrief` 行）：

```yaml
- id: debrief
  config:
    cliPath: /opt/debrief/bin/debrief
    kernelMode: auto
    dataDir: ~/.dsh/debrief-runtime
    withCollectors: false
    timeoutMs: 15000
    enableSetup: true
    enableDashboardRoute: true
    telegram:
      botToken: '123456:ABC…' # 可选；Telegram Bot token
      chatId: '-100…' # 可选；接收推送的 chat id
```

| 配置项                 | 类型                        | 默认                     | 说明                                                                                                                                     |
| ---------------------- | --------------------------- | ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `cliPath`              | string                      | 未设置                   | 内核 CLI 的绝对路径或 PATH 名（external 模式；auto 模式的优先选择）。指向 `mock/debrief.js` 即可本地演示。                               |
| `kernelMode`           | `auto\|external\|managed`   | `auto`                   | `auto`：显式 cliPath/`DEBRIEF_CLI_PATH` 优先 external，否则自举；`external`：始终用 cliPath（服务器部署）；`managed`：始终自举内置内核。 |
| `dataDir`              | string                      | `~/.dsh/debrief-runtime` | 自举 venv 与 marker 的运行时目录（managed 模式）；环境变量 `DEBRIEF_DATA_DIR` 兜底。                                                     |
| `withCollectors`       | boolean                     | `false`                  | 自举完成后额外从 PyPI 联网安装 `portfolio_agent_kernel[collectors]`（采集依赖，可选；失败不阻断核心读写；实时行情刷新需要它）。          |
| `timeoutMs`            | number                      | `15000`                  | 单次内核调用超时（毫秒），超时返回 `DEBRIEF_TIMEOUT`。                                                                                   |
| `enableSetup`          | boolean                     | `true`                   | 是否注册 `debrief-setup` 人类命令（幂等注册 8 个定时任务）。                                                                             |
| `enableDashboardRoute` | boolean                     | `true`                   | 是否注册只读路由 `/api/debrief/dashboard?range=30\|90\|200\|365`（经 DSH 认证的 connection fetch 通道，仅 owner cookie 可达）。          |
| `dashboardCacheMs`     | number                      | `20000`                  | 路由 payload 的内存缓存时长（毫秒，0 关闭）；同 range 的并发请求合并为一次内核调用。                                                     |
| `dashboardRefresh`     | `background\|inline\|never` | `background`             | 读时行情刷新策略：默认先返回缓存价、后台刷新；`inline` 阻塞等待实时刷新（旧行为）；`never` 只读缓存（由定时 worker 负责新鲜度）。        |
| `pycachePrefix`        | string                      | `<dataDir>/pycache`      | 注入内核子进程的 `PYTHONPYCACHEPREFIX`：只读 venv 也能落字节码缓存；空串关闭。环境变量 `DEBRIEF_PYCACHE_PREFIX` 兜底。                   |
| `telegram.botToken`    | string                      | 未设置                   | Telegram Bot token；与 chatId 同时设置即启用推送（技能侧新闻/复盘摘要、提醒比对、`notify test`）。注入为内核 `TELEGRAM_BOT_TOKEN`。       |
| `telegram.chatId`      | string                      | 未设置                   | 接收推送的 chat id（私聊数字 id 或频道 `@channel`）；注入为内核 `TELEGRAM_CHAT_ID`。                                                     |

未在 schema 内的字段会被忽略。插件不持久化配置：修改 profile patch 由用户自行编辑。

## 内核模式与自举（managed）

插件 npm 包内置 `kernel/wheels/`（内核 wheel（纯 Python）+ 8 个纯 Python 离线依赖轮子，
约 2.6MB）。首次调用内核时：

1. 探测工具：优先 `uv`（PATH 可执行），否则 `python3.11|python3.12|python3.13`
   （版本校验 ≥3.11）；两者皆无 → 结构化错误 `DEBRIEF_NO_PYTHON`。
2. `uv venv --python 3.11 <dataDir>/venv` 或 `python3.x -m venv <dataDir>/venv`。
3. `pip install --no-index --find-links <pkg>/kernel/wheels portfolio_agent_kernel`
   —— 全程离线、不访问网络；自举输出单独捕获，不会污染 CLI envelope。
4. 写入 marker（wheel 指纹 + 启动器路径）；指纹变化时自动重建 venv。
5. 并发安全：目录锁串行化自举；等待超时返回 `DEBRIEF_KERNEL_INITIALIZING`。

缺少内核轮子 → `DEBRIEF_NO_WHEEL`（更新插件或改用 external）。`/debrief-setup`
会先完成自举再注册任务，并输出内核状态（mode/launcher/dataDir/wheel）。

## 环境变量

| 变量                   | 说明                                                               |
| ---------------------- | ------------------------------------------------------------------ |
| `DEBRIEF_CLI_PATH`     | `cliPath` 的兜底来源（auto 模式视为显式配置）。                    |
| `DEBRIEF_DATA_DIR`     | `dataDir` 的兜底来源。                                             |
| `DEBRIEF_WHEELS_DIR`   | 轮子目录覆盖（测试用，一般不需要）。                               |
| `TELEGRAM_BOT_TOKEN`   | 内核侧 Telegram token（插件 `telegram.botToken` 会注入覆盖）。     |
| `TELEGRAM_CHAT_ID`     | 内核侧 Telegram chat id（插件 `telegram.chatId` 会注入覆盖）。     |
| `TELEGRAM_NEWS_PUSH`   | 新闻**原始条目**推送开关（默认关闭；摘要由定时技能经 `debrief_telegram` 推送）。设 `true` 恢复内核推送，仅在已配置时生效。 |
| `TELEGRAM_REPORT_PUSH` | 复盘报告**原始摘要**推送开关（默认关闭；精简摘要由定时技能经 `debrief_telegram` 推送）。设 `true` 恢复内核推送，仅在已配置时生效。 |
| `PRICE_STALE_SECONDS`  | 行情缓存视为过期的秒数（默认 120）；读侧超过此时长即实时刷新。     |
| `REMINDER_COOLDOWN_MINUTES` | 关注价提醒冷却分钟数（默认 120）：标的持续处于关注价内时，每个冷却窗口最多推送一次。 |
| `DEBRIEF_FX_<CCY>`     | 汇率离线兜底：每 1 CNY 兑换多少 `CCY`（如 `DEBRIEF_FX_USD=7.2`）。 |

## 实时行情 / 汇率 / Telegram

- **实时行情**：`holdings` / `watchlist` / `dashboard` / `analysis prepare` 默认在
  行情超过 `PRICE_STALE_SECONDS` 秒时自动实时刷新（`--refresh` 强制全部刷新、
  `--no-refresh` 只读缓存）；未安装 collectors 时静默降级为缓存数据。
- **汇率**：dashboard 附 `fx` 块（免费接口 open.er-api.com，无需密钥，可接受秒级
  延迟），投资组合页面据此提供 CNY/USD/HKD 总资产切换；接口失败时仅按 CNY 展示。
- **Telegram**：仅发不收（send-only）。新闻与复盘摘要都由定时技能经 `debrief_telegram`
  推送（内核 worker 的原始新闻推送与 `report create` 的原始报告推送默认关闭，避免与
  技能侧 digest 重复、且保证来源链接可点击）；可用 `debrief notify status` 查看状态、
  `notify test` 发送测试消息（未配置返回 `DEBRIEF_TELEGRAM_UNCONFIGURED`）。
- **关注价提醒**：worker 每 15 分钟比对一次，但**只在该标的所属市场的常规交易时段内**
  推送（US 09:30–16:00 ET / CN 09:30–11:30、13:00–15:00 / HK 09:30–12:00、13:00–16:00 /
  加密 24/7；周末不推，节假日暂未建模），同一标的每 `REMINDER_COOLDOWN_MINUTES`
  （默认 2 小时）最多一次；价格回到关注价外侧后再次触及会立即提醒。

## UI 相关说明

- 涨跌色遵循宿主主题约定（CN 红涨绿跌），颜色全部走 theme token（`--dsw-alias-*`）；
  `ui.upDown` 的两套色板（cn / intl）由宿主控制，插件跟随 token，不额外配置。
- 卡片与投资组合页面文案走 zh/en locale，缺省回退 zh。

---

The plugin is configured in the profile patch layer (the `- id: debrief` row of
`cordis.patch.yml`):

```yaml
- id: debrief
  config:
    cliPath: /opt/debrief/bin/debrief
    timeoutMs: 15000
    enableSetup: true
    enableDashboardRoute: true
    telegram:
      botToken: '123456:ABC…' # optional: Telegram Bot token
      chatId: '-100…' # optional: chat id to receive pushes
```

| Field                  | Type                      | Default                  | Description                                                                                                                                                                     |
| ---------------------- | ------------------------- | ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `cliPath`              | string                    | unset                    | Absolute path or PATH name of the kernel CLI (external mode; the auto mode's first choice). Point it at `mock/debrief.js` for a local demo.                                     |
| `kernelMode`           | `auto\|external\|managed` | `auto`                   | `auto`: an explicit cliPath/`DEBRIEF_CLI_PATH` prefers external, else bootstrap; `external`: always use cliPath (server); `managed`: always bootstrap.                          |
| `dataDir`              | string                    | `~/.dsh/debrief-runtime` | Runtime directory for the bootstrapped venv and marker (managed mode); env `DEBRIEF_DATA_DIR` falls back.                                                                       |
| `withCollectors`       | boolean                   | `false`                  | After bootstrap, additionally install `portfolio_agent_kernel[collectors]` from PyPI (networked, optional; failures don't block core commands; live quote refresh needs it).    |
| `timeoutMs`            | number                    | `15000`                  | Per-call kernel timeout in ms; expiry returns `DEBRIEF_TIMEOUT`.                                                                                                                |
| `enableSetup`          | boolean                   | `true`                   | Register the `debrief-setup` human command (idempotently registers 8 scheduled tasks).                                                                                          |
| `enableDashboardRoute` | boolean                   | `true`                   | Serve the read-only route `/api/debrief/dashboard?range=30\|90\|200\|365` through the DSH-authenticated connection fetch channel (owner cookie only).                           |
| `telegram.botToken`    | string                    | unset                    | Telegram Bot token; set together with chatId to enable pushes (skill-composed news/report digests, watchlist reminders, `notify test`). Injected as kernel `TELEGRAM_BOT_TOKEN`. |
| `telegram.chatId`      | string                    | unset                    | Chat id that receives pushes (numeric private id or `@channel`); injected as kernel `TELEGRAM_CHAT_ID`.                                                                         |

Unknown fields are ignored. The plugin never persists configuration; the profile
patch belongs to the user.

## Environment

| Variable               | Description                                                                                           |
| ---------------------- | ----------------------------------------------------------------------------------------------------- |
| `DEBRIEF_CLI_PATH`     | Fallback for `cliPath` (explicit config wins).                                                        |
| `DEBRIEF_DATA_DIR`     | Fallback for `dataDir`.                                                                               |
| `DEBRIEF_WHEELS_DIR`   | Wheel directory override (tests; usually unnecessary).                                                |
| `TELEGRAM_BOT_TOKEN`   | Kernel-side Telegram token (plugin `telegram.botToken` overrides).                                    |
| `TELEGRAM_CHAT_ID`     | Kernel-side Telegram chat id (plugin `telegram.chatId` overrides).                                    |
| `TELEGRAM_NEWS_PUSH`   | Raw news-item pushes (off by default; digests are pushed by the scheduled skills via `debrief_telegram`). Set `true` to re-enable.   |
| `TELEGRAM_REPORT_PUSH` | Raw report-summary pushes (off by default; digests are pushed by the scheduled skills via `debrief_telegram`). Set `true` to re-enable. |
| `PRICE_STALE_SECONDS`  | Seconds after which cached quotes count as stale (default 120); read commands refresh live beyond it. |
| `REMINDER_COOLDOWN_MINUTES` | Watchlist reminder cooldown in minutes (default 120): at most one push per instrument per window while the target zone stays hit. |
| `DEBRIEF_FX_<CCY>`     | Offline FX fallback: `<CCY>` units per 1 CNY (e.g. `DEBRIEF_FX_USD=7.2`).                             |

## Live quotes / FX / Telegram

- **Live quotes**: `holdings` / `watchlist` / `dashboard` / `analysis prepare`
  refresh stale quotes live by default (older than `PRICE_STALE_SECONDS`);
  `--refresh` forces a full refresh, `--no-refresh` reads the cache only. Without
  the collectors extra the kernel degrades silently to cached data.
- **FX**: the dashboard payload carries an `fx` block (free open.er-api.com, no
  key, seconds of latency accepted) which powers the CNY/USD/HKD total-assets
  switcher on the Portfolio page; on provider failure the page shows CNY only.
- **Telegram**: send-only. News and report digests are pushed by the scheduled
  skills through `debrief_telegram` (the kernel's raw news push and raw
  `report create` push are off by default so they cannot duplicate the skill
  digest or lose clickable source links). Check with `debrief notify status`,
  test with `notify test` (unconfigured → `DEBRIEF_TELEGRAM_UNCONFIGURED`).
- **Price-target reminders**: the worker compares every 15 minutes but only
  pushes inside the instrument's regular session (US 09:30–16:00 ET / CN
  09:30–11:30, 13:00–15:00 / HK 09:30–12:00, 13:00–16:00 / crypto 24/7; no
  weekends, exchange holidays not modelled yet), at most once per
  `REMINDER_COOLDOWN_MINUTES` (default 2h) while the target zone stays hit;
  re-crossing after leaving the zone alerts immediately.

## UI notes

- Up/down colors follow the host convention (red-up in the CN convention); all
  colors come from theme tokens (`--dsw-alias-*`). The `ui.upDown` palettes are
  host-controlled; the plugin only follows tokens and needs no extra config.
- Card and page copy is zh/en localized with a zh fallback.
