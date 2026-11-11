# Configuration · 配置

> English follows the Chinese section.

插件在 profile patch 层配置（`cordis.patch.yml` 的 `- id: debrief` 行）：

```yaml
- id: debrief
  config:
    cliPath: /opt/debrief/bin/debrief
    timeoutMs: 15000
    enableSetup: true
    enableDashboardRoute: true
```

| 配置项                 | 类型    | 默认                                       | 说明                                                                                                                            |
| ---------------------- | ------- | ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------- |
| `cliPath`              | string  | `debrief`（或环境变量 `DEBRIEF_CLI_PATH`） | 内核 CLI 的绝对路径或 PATH 名。指向 `mock/debrief.js` 即可本地演示。                                                            |
| `timeoutMs`            | number  | `15000`                                    | 单次内核调用超时（毫秒），超时返回 `DEBRIEF_TIMEOUT`。                                                                          |
| `enableSetup`          | boolean | `true`                                     | 是否注册 `debrief-setup` 人类命令（幂等注册 8 个定时任务）。                                                                    |
| `enableDashboardRoute` | boolean | `true`                                     | 是否注册只读路由 `/api/debrief/dashboard?range=30\|90\|200\|365`（经 DSH 认证的 connection fetch 通道，仅 owner cookie 可达）。 |

未在 schema 内的字段会被忽略。插件不持久化配置：修改 profile patch 由用户自行编辑。

## 环境变量

| 变量               | 说明                                       |
| ------------------ | ------------------------------------------ |
| `DEBRIEF_CLI_PATH` | `cliPath` 的兜底来源（显式 config 优先）。 |

## UI 相关说明

- 涨跌色遵循宿主主题约定（CN 红涨绿跌），颜色全部走 theme token（`--dsw-alias-*`）；
  `ui.upDown` 的两套色板（cn / intl）由宿主控制，插件跟随 token，不额外配置。
- 卡片与 Dashboard 页面文案走 zh/en locale，缺省回退 zh。

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
```

| Field                  | Type    | Default                               | Description                                                                                                                                           |
| ---------------------- | ------- | ------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| `cliPath`              | string  | `debrief` (or env `DEBRIEF_CLI_PATH`) | Absolute path or PATH name of the kernel CLI. Point it at `mock/debrief.js` for a local demo.                                                         |
| `timeoutMs`            | number  | `15000`                               | Per-call kernel timeout in ms; expiry returns `DEBRIEF_TIMEOUT`.                                                                                      |
| `enableSetup`          | boolean | `true`                                | Register the `debrief-setup` human command (idempotently registers 8 scheduled tasks).                                                                |
| `enableDashboardRoute` | boolean | `true`                                | Serve the read-only route `/api/debrief/dashboard?range=30\|90\|200\|365` through the DSH-authenticated connection fetch channel (owner cookie only). |

Unknown fields are ignored. The plugin never persists configuration; the profile
patch belongs to the user.

## Environment

| Variable           | Description                                    |
| ------------------ | ---------------------------------------------- |
| `DEBRIEF_CLI_PATH` | Fallback for `cliPath` (explicit config wins). |

## UI notes

- Up/down colors follow the host convention (red-up in the CN convention); all
  colors come from theme tokens (`--dsw-alias-*`). The `ui.upDown` palettes are
  host-controlled; the plugin only follows tokens and needs no extra config.
- Card and page copy is zh/en localized with a zh fallback.
