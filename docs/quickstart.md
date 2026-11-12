# Quick start · 快速开始

> English follows the Chinese section.

## 前提

- DeepSeek Harness ≥ 0.2.2-rc.1（`dsh web` 或桌面版）
- **安装即用**：内核已随插件内置（`kernel/wheels/`）。managed/auto 模式只需机器上有
  **uv 或 Python ≥3.11**（自举隔离 venv，全程离线）；采集依赖（collectors）为可选项。
  服务器部署走 external 模式指向外部内核 venv；本地演示可用仓库自带 mock（`mock/debrief.js`）。

## 安装

```sh
dsh plugin --profile web add dsh-debrief
```

在 profile 的 patch 层配置内核路径（`cordis.patch.yml`）：

```yaml
- id: debrief
  config:
    cliPath: /opt/debrief/bin/debrief
    timeoutMs: 15000
```

## 注册定时任务

在任意会话里输入：

```text
/debrief-setup
```

命令先执行 `debrief job list --json` 校验内核，然后幂等注册 8 个任务
（标题已存在则跳过）：

| 任务                         | 时间（Asia/Shanghai）            |
| ---------------------------- | -------------------------------- |
| 盘后分析 · 美股 / A股 / 港股 | 周一至周五 18:00 / 15:30 / 16:45 |
| 盘后分析 · 加密              | 每天 08:00                       |
| 每小时新闻摘要               | 每小时 :05                       |
| 周复盘                       | 周六 09:00                       |
| 月度复盘                     | 每月 1 日 09:00                  |
| 每日记忆压缩                 | 每天 02:30                       |

所有任务 `target = new_once`：每任务一个专属会话、串行交付、错过时段只补最新一次。
任务可在 DSH 的 Schedule 页面查看、暂停、删除。

## 立即体验

```sh
bash examples/demo.sh
```

或直接在会话里问：

- 「看下我的持仓」
- 「做一下美股盘后分析」
- 「搜索代码茅台」
- 「查记忆：建仓理由」
- 「最近有哪些定时任务在跑」

写工具只出现在定时 skill 会话：报告写回 `debrief_report_create`、
记忆压缩 `debrief_memory_compact_write`、决策沉淀 `debrief_memory_add`。

---

## Prerequisites

- DeepSeek Harness ≥ 0.2.2-rc.1 (`dsh web` or Desktop)
- **Installs-and-runs**: the kernel ships inside the plugin (`kernel/wheels/`).
  Managed/auto mode only needs **uv or Python ≥ 3.11** (offline bootstrap of an
  isolated venv); collectors stay optional. Server deployments use external mode
  against the external kernel venv; the bundled mock (`mock/debrief.js`) serves
  local demos.

## Install

```sh
dsh plugin --profile web add dsh-debrief
```

Configure the kernel path in the profile patch layer (`cordis.patch.yml`):

```yaml
- id: debrief
  config:
    cliPath: /opt/debrief/bin/debrief
    timeoutMs: 15000
```

## Register scheduled tasks

In any session run:

```text
/debrief-setup
```

The command validates the kernel (`debrief job list --json`) and idempotently
registers 8 tasks (an existing title is skipped):

| Task                        | Time (Asia/Shanghai)          |
| --------------------------- | ----------------------------- |
| After-market · US / CN / HK | Mon–Fri 18:00 / 15:30 / 16:45 |
| After-market · Crypto       | Daily 08:00                   |
| Hourly news digest          | Hourly at :05                 |
| Weekly review               | Saturday 09:00                |
| Monthly review              | 1st of month 09:00            |
| Daily memory compaction     | Daily 02:30                   |

Every task uses `target = new_once`: one dedicated session per task, serial
delivery, only the latest missed occurrence is delivered. Tasks are visible on
the Schedule page and can be paused or deleted.

## Try it now

```sh
bash examples/demo.sh
```

Or ask in a session:

- “Show my holdings”
- “Run an after-market analysis for US”
- “Search for 茅台”
- “Memory: position rationale”
- “List recent scheduled runs”

Write tools only appear in scheduled skill sessions: report write-back
(`debrief_report_create`), memory compaction (`debrief_memory_compact_write`),
decision sedimentation (`debrief_memory_add`).
