# Contributing · 贡献指南

感谢关注 dsh-debrief！中文优先但双语响应；讨论请走 GitHub Issues。

## 先做三件事

1. **查现有 issue**：特性请求/问题先搜再发。
2. **先讨论再动手**：架构级改动（工具契约、slot 注册方式、存储语义）先开 issue 对齐，避免返工。
3. **小步提交**：一个 PR 只解决一件事；写操作相关改动必须包含内核审计与幂等性说明。

## 开发环境

```sh
npm install
npm run verify   # typecheck + lint + format + build（含 client 产物 export 剥离）+ test 全绿才可提交
```

## 质量门禁（合并必须全绿）

- `npm run typecheck`：TypeScript strict，`tsc --noEmit` 0 错误。
- `npm run lint`：ESLint 0 warning（JS 文件；TS 由 tsc 把关）。
- `npm run format:check`：Prettier 全绿。
- `npm test`：vitest 全绿；新增功能必须带测试。
- `npm run build`：构建成功，dist 与 src 同步提交。

## 代码约定

- **零运行时依赖是硬约束**：新增依赖需在 issue 中说明必要性并取得共识。
  devDependencies 仅 typescript / vitest / eslint / prettier。
- **契约先行**：工具参数/payload、envelope、错误码是内核契约的投影——改动前
  先对齐内核 CLI 与设计文档；错误码加入稳定表（docs/tools.md）与 locale 错误码表。
- **客户端单文件**：`src/client.ts` 保持无 import（Web Host 只服务 `./client` 导出）；
  React 取自宿主模块表；文案一律走 locale 字典（zh/en 同步，测试校验 key 齐）。
- **卡片不 crash**：渲染模型校验失败必须走降级路径，绝不让 slot 崩溃。
- **注释与提交信息**：中英皆可，保持简洁；涉及契约的注释写清依据。

## 目录约定

| 路径              | 内容                                                    |
| ----------------- | ------------------------------------------------------- |
| `src/host/`       | Host 插件（tools/cli/schema/skills/schedule/dashboard） |
| `src/client.ts`   | 浏览器端（卡片 + Dashboard 页面）                       |
| `skills/*.md`     | 技能正文（header 三行 + 中英双语 body）                 |
| `schedule/*.json` | 任务预置（title/prompt/rrule/order/target）             |
| `mock/debrief.js` | 模拟内核（与内核契约同构）                              |
| `tests/`          | vitest 单测                                             |
| `docs/`           | 用户文档（中英双语）                                    |

## 发布

版本与 CHANGELOG 由 release-please 自动管理：合并到 main 后按
Conventional Commits 生成 release PR，发布自动触发 npm publish。提交信息用
`feat:` / `fix:` / `docs:` / `chore:` 前缀。
