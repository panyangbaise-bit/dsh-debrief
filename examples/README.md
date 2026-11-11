# Examples · 示例

> English follows the Chinese section.

本目录提供零依赖的一键演示：用仓库自带 mock 内核跑通全部命令形态。

## 一键演示

```sh
bash examples/demo.sh
```

脚本依次演示：

1. 只读：holdings / transactions / watchlist / instruments search / report / memory search / analysis prepare / job list / dashboard / news latest
2. 白名单写：report create（stdin JSON）、memory compact-write（stdin JSON）、memory add（stdin JSON）
3. job 状态机：start → status → finish

## 在 DSH 里演示

把插件配置指向 mock（见 README「本地演示」），然后：

```text
/debrief-setup          # 注册 8 个定时任务（mock 也支持 job list 校验）
```

会话里问「看下我的持仓」「做一下美股盘后分析」即可看到卡片与 Dashboard 页面。

---

This directory offers a zero-dependency one-command demo using the bundled
mock kernel.

## One-command demo

```sh
bash examples/demo.sh
```

The script demonstrates: the read commands (holdings … news latest), the
whitelisted writes (report create / memory compact-write / memory add via stdin
JSON), and the job state machine (start → status → finish).

## Demo inside DSH

Point the plugin at the mock (see README “Local demo”), then run
`/debrief-setup` in a session and ask things like “Show my holdings” or “Run an
after-market analysis for US”.
