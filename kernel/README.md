# debrief 数据内核（随插件内置）

本目录是 `dsh-debrief` 自带的数据内核（Python，无模型、无 Agent），也是 npm 包
`kernel/wheels/` 里内核 wheel 的源码出处。插件通过本地子进程调用内核：

```text
dsh-debrief (Host) ──subprocess: debrief <command> --json──> kernel (SQLite)
```

- 运行时 SQLite 单库（持仓/成交/自选/报告/记忆/任务台账），所有模型工作都在
  DSH agent 侧完成。
- **managed 模式**（默认装插件即用）：npm 包内置 `kernel/wheels/`，首次调用时在
  `~/.dsh/debrief-runtime/venv` 离线自举（需要 `uv` 或 Python ≥3.11）。
- **external 模式**：自行部署内核（服务器/systemd），用 profile patch 的
  `cliPath` 指向即可。

## 目录

| 路径          | 内容                                                                                                                        |
| ------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `src/`        | 内核源码（`debrief/` CLI 与业务、`db/`、`common/`、`domain/`、`memory/`、`adapters/`、`scheduler/`、`notifier/`、`tests/`） |
| `wheels/`     | 随 npm 包分发的离线轮子：内核 wheel（纯 Python）+ 8 个依赖轮子                                                              |
| `docs/cli.md` | CLI 契约：每个命令的 JSON envelope、错误码、设计决策记录                                                                    |

## 重建内核 wheel

内容一变**必须升版本号**（uv/pip 缓存以「文件名+版本」为键，禁止同版本覆盖）。

```sh
cd kernel/src
uv build                      # 或 python -m build（需要 build 包）
# 产物 dist/portfolio_agent_kernel-<version>-py3-none-any.whl
cp dist/*.whl ../wheels/      # 旧版本轮子请删除，只保留当前版本
```

内核版本与 `src/pyproject.toml`、`src/debrief/__init__.py`、wheel METADATA 三处保持
一致；`kernel/wheels/` 必须恰好包含一个内核轮子（仓库测试会校验）。

## 完整内核（含行情采集 worker）

内核 wheel 含全部纯 Python 模块与 core 依赖（sqlalchemy / requests /
python-dotenv）：CLI 读写、实时新闻、汇率、Telegram notify 在只装 wheel 的
managed venv 中即可运行。行情实时刷新与采集 worker 需要额外依赖（akshare、
yfinance、apscheduler 等，`[collectors]` extra）：

```sh
uv pip install "portfolio-agent-kernel[collectors] @ file:./src"
debrief worker            # APScheduler 数据采集 + 提醒比对（无模型调用）
```

详细命令契约见 [docs/cli.md](docs/cli.md)。
