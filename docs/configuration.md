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
```

| 配置项                 | 类型                      | 默认                     | 说明                                                                                                                                     |
| ---------------------- | ------------------------- | ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `cliPath`              | string                    | 未设置                   | 内核 CLI 的绝对路径或 PATH 名（external 模式；auto 模式的优先选择）。指向 `mock/debrief.js` 即可本地演示。                               |
| `kernelMode`           | `auto\|external\|managed` | `auto`                   | `auto`：显式 cliPath/`DEBRIEF_CLI_PATH` 优先 external，否则自举；`external`：始终用 cliPath（服务器部署）；`managed`：始终自举内置内核。 |
| `dataDir`              | string                    | `~/.dsh/debrief-runtime` | 自举 venv 与 marker 的运行时目录（managed 模式）；环境变量 `DEBRIEF_DATA_DIR` 兜底。                                                     |
| `withCollectors`       | boolean                   | `false`                  | 自举完成后额外从 PyPI 联网安装 `portfolio_agent_kernel[collectors]`（采集依赖，可选；失败不阻断核心读写）。                              |
| `timeoutMs`            | number                    | `15000`                  | 单次内核调用超时（毫秒），超时返回 `DEBRIEF_TIMEOUT`。                                                                                   |
| `enableSetup`          | boolean                   | `true`                   | 是否注册 `debrief-setup` 人类命令（幂等注册 8 个定时任务）。                                                                             |
| `enableDashboardRoute` | boolean                   | `true`                   | 是否注册只读路由 `/api/debrief/dashboard?range=30\|90\|200\|365`（经 DSH 认证的 connection fetch 通道，仅 owner cookie 可达）。          |

未在 schema 内的字段会被忽略。插件不持久化配置：修改 profile patch 由用户自行编辑。

## 内核模式与自举（managed）

插件 npm 包内置 `kernel/wheels/`（slim 内核轮子 + 8 个纯 Python 离线依赖轮子，
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

| 变量                 | 说明                                            |
| -------------------- | ----------------------------------------------- |
| `DEBRIEF_CLI_PATH`   | `cliPath` 的兜底来源（auto 模式视为显式配置）。 |
| `DEBRIEF_DATA_DIR`   | `dataDir` 的兜底来源。                          |
| `DEBRIEF_WHEELS_DIR` | 轮子目录覆盖（测试用，一般不需要）。            |

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
```

| Field                  | Type                      | Default                  | Description                                                                                                                                            |
| ---------------------- | ------------------------- | ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `cliPath`              | string                    | unset                    | Absolute path or PATH name of the kernel CLI (external mode; the auto mode's first choice). Point it at `mock/debrief.js` for a local demo.            |
| `kernelMode`           | `auto\|external\|managed` | `auto`                   | `auto`: an explicit cliPath/`DEBRIEF_CLI_PATH` prefers external, else bootstrap; `external`: always use cliPath (server); `managed`: always bootstrap. |
| `dataDir`              | string                    | `~/.dsh/debrief-runtime` | Runtime directory for the bootstrapped venv and marker (managed mode); env `DEBRIEF_DATA_DIR` falls back.                                              |
| `withCollectors`       | boolean                   | `false`                  | After bootstrap, additionally install `portfolio_agent_kernel[collectors]` from PyPI (networked, optional; failures don't block core commands).        |
| `timeoutMs`            | number                    | `15000`                  | Per-call kernel timeout in ms; expiry returns `DEBRIEF_TIMEOUT`.                                                                                       |
| `enableSetup`          | boolean                   | `true`                   | Register the `debrief-setup` human command (idempotently registers 8 scheduled tasks).                                                                 |
| `enableDashboardRoute` | boolean                   | `true`                   | Serve the read-only route `/api/debrief/dashboard?range=30\|90\|200\|365` through the DSH-authenticated connection fetch channel (owner cookie only).  |

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
