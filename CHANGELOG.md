# Changelog

All notable changes to this project will be documented in this file. The format
is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
版本由 [release-please](https://github.com/googleapis/release-please) 自动管理。

## [Unreleased]

### Added

- **Dashboard payload freshness** — the dashboard payload carries `pricesAsOf`
  (latest `price_cache.fetched_at`, UTC ISO-8601) so the page can state how old
  a cached quote is; the Portfolio header renders it next to the range chips.
- **Dashboard route cache** — `/api/debrief/dashboard` keeps a short-lived
  in-memory payload per range (`dashboardCacheMs`, default 20 s), collapses
  concurrent misses into one kernel call, and answers from cached prices while
  a background refresh keeps the next view fresh (`dashboardRefresh`:
  `background` default / `inline` / `never`, at most one refresh per 60 s).
  A kernel failure now serves the last good payload instead of an error card.
- **`pycachePrefix`** — kernel subprocesses get `PYTHONPYCACHEPREFIX`
  (default `<dataDir>/pycache`) so a read-only, root-owned venv no longer
  recompiles pandas/akshare on every call. Bootstrap installs with
  `uv pip install --compile` and runs `compileall` over the venv afterwards.

### Fixed

- **场外基金搜不到** — the CN open-end fund catalog was capped at 6 000 codes,
  but akshare returns ≈28 000 sorted by code, so every `01xxxx`/`02xxxx` fund
  (including 华夏半导体材料设备ETF联接C `020357` and 华夏科创50ETF联接C
  `011613`) fell outside the cap and never reached the picker. The cap is now
  40 000 and the sync also stores `拼音缩写`, so `hxbd` finds 华夏半导体….
  Quotes were never the problem: the CN adapter already fetched OTC-fund NAV.
- **Symbol lookups no longer wait on the live suggest** — an exact code match
  (e.g. `020357`) answers from the local catalog in ~30 ms instead of a
  ~1.5 s eastmoney round-trip; the live fallback still covers names and
  instruments the catalog does not know.

- **目录同步不再因东财限流而整类缺失** — 06:10 的 `catalog-sync` 里
  `cn_stock`（连接重置）、`cn_etf`（502）、`hk_stock`/`us_stock`（push2 限流）
  长期全部失败，本地目录此前只有基金和加密两类，股票/ETF 搜索只能靠 1–2 s 的
  实时 suggest。A 股与 ETF 现在各有备用源：A 股列表失败时改用上交所
  （主板 + 科创板）与深交所官方名单（实测 5 579 条，含北交所 920xxx），
  ETF 失败时改用新浪 ETF 榜（927 条，自动去掉 sh/sz 前缀）。
  港股/美股仍只有东财一个源，失败时回退实时 suggest（未变）。

### Changed

- **目录主键扩成 (market, symbol, asset_class)**（migration v15，内核 0.4.0）：
  `000001` 既是平安银行（深市股票）也是华夏成长混合（场外基金），旧的两列
  唯一键每轮同步都会丢掉其中一个。SQLite 不能原地删约束，v15 重建表并搬数据；
  这次同步后目录里 CN 股票 5 579 / ETF 927 / 场外基金 28 346，**1943 个代码
  同时存在两个资产类别**。
- **选择器输出带前缀的 symbol**：裸码含义唯一时保持裸码（600519、020357、
  510300），有歧义时返回 `stock:000001` / `fund:000001`——`resolve_cn_symbol`
  本来就认这个前缀，写入自选/持仓后行情解析不再落到「Ambiguous CN symbol」。
- 同一标的被两个源重复收录时（510300 既在 ETF 榜也在基金列表）按名称去重，
  保留代码本身蕴含的类别，避免选择器出现两个一模一样的条目；选择器新增
  股票/基金/ETF 类别徽标。

- **港股/美股目录补上官方备用源** — 两者此前只有东方财富 push2 一个来源，
  限流时目录为空、搜索回退到 1–2 s 的实时 suggest。现在：
  美股备用 **Nasdaq Trader SymDir**（`nasdaqlisted.txt` + `otherlisted.txt`，
  13 248 条，含 5 787 只 ETF，类别股代码统一成 `BRK-A` 形式），
  港股备用 **HKEX List of Securities**（3 279 条，含 453 只 ETF；文件里
  权证/牛熊证/债券占绝大多数，按 Category 过滤，代码补零到 5 位）。
  四个市场目录现在都有本地覆盖：US 13 248 / HK 3 279 / CN 34 852 / CC 1 688，
  搜索 4–29 ms。

### Known limitations



- 美股备用源只覆盖 NASDAQ/NYSE/AMEX/Arca（Nasdaq Trader 目录不含 OTC/粉单），
  粉单标的仍需实时 suggest 才能搜到；本机的 `SPCX` 在主目录里，不受影响。

### Fixed

- **盘后分析的记忆候选永远为空** — `cmd_analysis_prepare` 用裸代码（`NVDA`）
  去精确匹配带市场前缀的记忆（`US:NVDA`），集合比对永远落空，四个盘后报告
  全部「记忆候选 0」。现在忽略市场前缀匹配，候选同时覆盖长期摘要 + 未压缩的
  decision/trade 短期证据，并携带可引用的 `evidenceDocIds`；`ops-*`/`run:` 噪声
  不入候选，无标的的市场回退到本市场记忆，纪律类主题（discipline/strategy/
  risk/rule）无标的地全局兜底。
- **盘后新闻不再四个市场吃同一锅** — 单一 wallstreetcn 流偏美股/宏观，A股盘后
  曾拿到 5/10 条英伟达治理消息。`cmd_analysis_prepare` 现按市场关键词给新闻打
  标并只保留目标市场 + 中性条目（`_scope_news`）。
- **长期记忆不再被任务台账污染** — `run` 源类型（prices/reminders/news 台账）
  从压缩候选里排除；此前 127 条长期记忆里 92 条是这类 `ops-*` 执行日志。
- **周/月复盘拿得到「本周」数据** — `debrief_transactions`、`debrief_jobs`
  增加 `since`/`until`（ISO-8601 窗口），`debrief_report` 增加 `list: true`
  窗口列表（此前只能读「最新一份」）。
- **美股盘后时点修正** — 从 Beijing 18:00（= 美东 05:00，美股未开盘，快照恒为
  持平）改到 **Beijing 次日 05:30**（美股收盘后），当日涨跌终于可量化。
- **新闻任务标题与节奏对齐** — 标题改「每4小时新闻摘要」，与 INTERVAL=4 一致。
- 四个盘后 prompt 增加「先陈述数据边界」硬约束（报价时点/交易时段、记忆是否
  命中、新闻是否跨市场；持平快照不得当作当日涨跌）。

- **已平仓标的重买报 DEBRIEF_CONFLICT** — 添加持仓时，若该 (market, symbol)
  已有一条 `shares=0 / status=closed` 的历史记录，`holdings add` 只会看到
  「记录已存在」并拒绝。现在这种记录按「重买」处理：复用原记录、置为 open、
  写入新的买入流水（notes=`reopen`），审计记为 `holding.add / reopen …`；
  真正还有持仓的重复添加仍然返回冲突。

### Added

- **涨跌配色开关** — 投资组合页头部新增「绿涨红跌 / 红涨绿跌」切换（与国际/ A股
  两种习惯对齐，选择存 localStorage 跨刷新保留，默认红涨绿跌，与插件原配色一致）。
- **收益数值着色** — 今日收益、总收益、年化收益，以及持仓盈亏%、自选涨跌%、
  图表末端标签，统一按涨跌染色；颜色按数额符号判定（为零才退回百分比），
  页面级 CSS 变量 `--dbr-up/--dbr-down` 由配色开关整体切换。

### Fixed

- **总收益恒为 ¥0** — `build_holdings_payload` 只给「当前持仓的市场」取汇率，
  而 `calculate_portfolio_totals` 会把已平仓的历史持仓（本例的港股/加密）也算
  进去；只要有一个已平仓市场缺汇率，整个函数就返回 `None`，页面于是显示
  「总收益 ¥0 0.00%」。现在汇率覆盖账本里所有市场（含已平仓），实测
  总收益 -4,373.73 / -3.09%（原为 0）。
- **涨跌色不生效** — `.dbr-v`、`.dbr-table td` 等规则以更高优先级覆盖了
  `.dbr-up/.dbr-down`，页面内所有涨跌数字实际无颜色。改为 `.dbr-page .dbr-up`
  级别的选择器，KPI 数值、持仓盈亏%、自选涨跌%、距离%、图表末端标签统一着色。
- **币种与配色收进下拉** — 头部不再平铺两组 chip，改为一个「CNY · 红涨绿跌」
  下拉菜单（币种 + 涨跌配色两段），支持点击外部/Esc 关闭，选择仍持久化。

### Changed

- **记忆只捕获「值得记的」**（内核 0.6.0）— capture 白名单去掉 `run`/`news`：
  任务台账、新闻只留在各自的业务表，不再生成记忆文档（此前每天 ~160 条 run
  文档 + 全部新闻镜像）。交易、持仓/自选变更、纪律、反馈、报告照常入记忆。
  词法索引跳过 run/news，向量嵌入只给 decision/trade/report 三类。
- **长期记忆支持遗忘**（migration v16，`retired_at`）— `memory compact-write`
  接受 `retire: true` 归档一个 topic（保留审计、不再参与检索）；
  `compact-candidates` 额外返回 `retireCandidates`（`ops-*` 主题 + 超
  `MEMORY_RETIRE_DAYS`（默认 180 天）未更新的低置信度主题）；检索与盘后
  记忆候选统一排除已退役和 `ops-*` 主题。
- **盘后输入包附带记忆索引** — dashboard payload 新增 `memories`（12 条
  topic + 一句话摘要 + 置信度），投资组合页底部新增「长期记忆」面板；
  详情仍经 `debrief_memory` 检索。
- **问答沉淀引导** — `debrief_memory_add` 说明改为「任何会话都可用来沉淀
  投资问答/决策」；每日压缩技能新增退役步骤与 conversation 晋升步骤（用户
  问答与决策同等对待，不得丢弃），周复盘技能核对本周问答是否已沉淀。

### Performance

- **Portfolio page: 4.2 s → 0.6 s** (3 concurrent: 8.6 s → 1.35 s). Three
  independent causes were removed:
  - adapters were imported before the staleness check, so every view paid the
    akshare/yfinance import tax even when no quote needed refreshing; the
    refresh now returns before importing anything and registers only the
    markets that actually have a stale target (`_register_adapters(markets)`);
  - the collectors were installed without bytecode, into a root-owned venv the
    Host cannot write to, so Python recompiled ≈2 000 modules per request
    (pandas 1 440 / numpy 487 / akshare 398 / yfinance 34 had no `.pyc`);
  - the page blocked on a live quote fetch, three FX HTTP calls and a fresh
    subprocess on every view.
- **One FX call per dashboard build** — the provider answer is cached in
  process (`DEBRIEF_FX_CACHE_SECONDS`, default 3600) and reused by the holdings
  conversion and the fx panel instead of three separate requests;
  `DEBRIEF_FX_TIMEOUT` (default 5 s) bounds a hung provider.

### Changed

- Catalog search prefilters in SQL before ranking, so a 28 k-row CN catalog
  still answers in ~20–35 ms per keystroke.
- Dashboard reads default to `--no-refresh`; quote freshness is owned by the
  background refresh (or the scheduled worker). `dashboardRefresh: inline`
  restores the pre-0.3 blocking behaviour.
- The Portfolio page keeps the previous payload on screen while another range
  loads (plus a per-range client cache) instead of blanking to a skeleton.
- Kernel wheel `portfolio_agent_kernel-0.3.0` ships the full adapter/scheduler/
  notifier surface that `debrief worker` needs (the previous build script
  produced a slim wheel that did not match the committed artifact).

### Added

- **Live news read path** — the kernel gains the missing `news latest` command
  (the `debrief_news` tool previously targeted a nonexistent CLI subcommand and
  always returned `DEBRIEF_USAGE`). `news latest` fetches WallStreetCN live,
  persists new items (headline-deduped) and returns the latest batch; the tool
  exposes `limit`, `refresh` (default true; `refresh:false` maps to
  `--no-refresh`) and `notify` (pushes new items to Telegram via `--notify`).
- **Real-time quotes on read** — `holdings` / `watchlist` / `dashboard` /
  `analysis prepare` refresh stale quotes live by default (new
  `price_cache.fetched_at` column + migration v14; stale = older than
  `PRICE_STALE_SECONDS`, default 120 s); `--refresh` forces a full refresh,
  `--no-refresh` reads the cache only. Without the collectors extra the kernel
  degrades silently to cached prices. Payloads carry `pricesRefreshed` /
  `priceErrors` and every position/watchlist row carries its `currency`.
- **Currency units + display-currency switcher** — the Portfolio page labels
  holding/watchlist prices with their native currency (CN stocks and funds CNY,
  US and crypto USD, HK HKD) and adds CNY/USD/HKD chips that convert total
  assets, P&L and the equity chart via the free open.er-api.com feed; the
  dashboard payload embeds an `fx` block (null on provider failure → CNY only)
  and the kernel exposes `debrief fx [--base X]`.
- **Telegram pushes (send-only)** — reports push when `report create` writes
  them back, news pushes when the worker collects new items (both toggleable
  via `TELEGRAM_REPORT_PUSH` / `TELEGRAM_NEWS_PUSH`); new `debrief notify
  status|test` command and a `debrief_telegram` tool; plugin Config gains
  `telegram.botToken` / `telegram.chatId` which are injected into every kernel
  subprocess.

- Self-contained kernel distribution: `kernel/wheels/` bundles the slim kernel
  wheel (`portfolio_agent_kernel-0.2.0-py3-none-any.whl`) plus its offline
  dependency closure (sqlalchemy/requests/python-dotenv/certifi/
  charset-normalizer/idna/urllib3/typing_extensions, pure-python wheels,
  ~2.6MB). On first use in `kernelMode: managed` (or `auto` without an
  explicit `cliPath`) the Host bootstraps an isolated venv into
  `~/.dsh/debrief-runtime/` (Config `dataDir` overrides): `uv venv` when uv is
  on PATH, else `python3.11|3.12|3.13 -m venv` (neither → structured
  `DEBRIEF_NO_PYTHON`); then `pip install --no-index --find-links
  <kernel/wheels> portfolio_agent_kernel` fully offline. A marker file caches
  the wheel fingerprint and a mismatch rebuilds; a directory lock serializes
  concurrent bootstraps (`DEBRIEF_KERNEL_INITIALIZING` on timeout). Bootstrap
  output is captured separately and never pollutes the CLI envelope.
- Install bypasses the uv/pip cache (`--no-cache` / `--no-cache-dir`) —
  caches key by filename+version, so a same-version wheel override would
  otherwise hit a stale cached package — followed by a content self-check
  (`import adapters, debrief`) that fails bootstraps as
  `DEBRIEF_BOOTSTRAP_INCOMPLETE` with a dataDir-cleanup hint.
- `ensureKernel` runs before every `runCli` call (zero overhead once ready);
  `external` mode is the unchanged passthrough for server deployments.
- Managed mode injects `DATABASE_URL=sqlite:///<dataDir>/portfolio.db` into
  every kernel subprocess unless the user configured one (external mode passes
  the environment through untouched); `/debrief-setup` reports the db path.
- `/debrief-setup` reports kernel status (mode/launcher/data dir/wheel) and
  bootstraps first in managed mode; failures carry Chinese repair steps
  (`DEBRIEF_NO_PYTHON` / `DEBRIEF_NO_WHEEL` / `DEBRIEF_BOOTSTRAP` /
  `DEBRIEF_CLI_NOT_FOUND`).
- Opt-in `withCollectors` installs the networked collectors extra after the
  offline base (non-fatal on failure; defaults to off).
- Tests: mode resolution, uv/python detection, wheel-dir resolution, marker
  reuse/rebuild, lock timeout/stale-steal, structured error paths, runCli
  prefix — all with mocked uv/python under a temp data dir, no network; plus a
  real integration test that bootstraps the bundled wheel offline with uv and
  runs the console script (skipped where uv is unavailable).

### Fixed

- Whitelisted write tools passed their multi-word subcommand to the kernel as a
  single argv token (`'memory compact-write'`), so argparse answered
  `DEBRIEF_USAGE invalid command line` and every write failed:
  `debrief_memory_compact_write`, `debrief_memory_add` and
  `debrief_report_create` were affected. `ToolSpec.command` is now an argv token
  array (`['memory', 'compact-write']`) and is spread into `runCli`, so read,
  write and approval-gated edit tools all reach the CLI as separate tokens.
  Covered by `tests/tool-argv.test.ts`, which records the argv a fake CLI
  receives (three cases fail on the previous implementation).

## [0.2.0] - 2026-11-12

### Added

- v2 portfolio editing through one implementation, two callers (UserActions
  pattern): six approval-gated agent tools (`debrief_holding_add/update/remove`,
  `debrief_watchlist_add/update/remove` → kernel `holdings|watchlist
  add|update|remove --json` with stdin payloads), a Client-callable POST route
  `/api/debrief/mutate`, and the Dashboard modal — all executing the same Host
  operation (`runEdit`).
- DSH approval confirmation flow for agent-initiated writes: a
  `tools/pre-execute` listener returns `ask` (bilingual display reasons) for
  the six write tools; without approval support the framework converts the ask
  into a denial, so writes are refused with a structured error instead of
  executing silently.
- Authenticated read route `/api/debrief/instruments?market=&query=` for the
  search-style instrument picker.
- Dashboard editing UI: “+ 添加持仓 / + 添加自选” open a modal with market
  chips, a debounced (250ms) keyboard-navigable instrument picker (held
  marker, empty/error states, requestId race guard), quantity/cost or target
  price/alert-switch forms; row-level 编辑/删除 with prefilled edit forms and
  double-confirm removal; success toast + automatic data refresh; all copy
  zh/en localized.
- Six keyed toolview cards for the write tools (write-result card with audit
  note).
- Mock kernel extended with `holdings add|update|remove` and `watchlist
  add|update|remove` matching the real kernel responses
  (`DEBRIEF_CONFLICT` / `DEBRIEF_NOT_FOUND` / `DEBRIEF_USAGE`), with an
  isolated state-file override (`DEBRIEF_MOCK_STATE`) for tests.
- Tests for edit payload validation, approval decisions, mock round-trips
  (add→conflict→update→remove), form validation, and mutation request
  building.

### Fixed

- renderModel lost undeclared payload fields (the whitelist validator dropped
  quantity/cost/price/marketValue/pnlPct/weight/changePct/targetPrice/
  distancePct/alert from dashboard holdings/watchlist rows, blanking every
  table cell). The client validator now validates declared fields but never
  drops undeclared keys, and all kind schemas are complete; regression tests
  assert renderModel output deep-equals input.

### Changed

- Watchlist `alert` semantics: the GET list's `alert` reflects the combined
  alerting state (switch on and price touched); the write commands return the
  stored switch value. The edit modal prefills from `alertEnabled` when
  present, falling back to `alert` (documented in docs/ui.md).

## [0.1.0] - 2026-11-11

### Added

- TypeScript strict migration: `src/host/*` (tools bridge) and a single-file
  `src/client.ts` browser half; `tsc` builds `dist/index.js` + `dist/client.js`;
  `exports`/`main`/`files` point at `dist`.
- 13 tools in the compiled raw-schema registry form: 9 read tools
  (`debrief_holdings`, `debrief_transactions`, `debrief_watchlist`,
  `debrief_instruments`, `debrief_report`, `debrief_memory`, `debrief_analyze`,
  `debrief_jobs`, `debrief_dashboard`) plus `debrief_news` and the three
  whitelisted write tools `debrief_report_create`, `debrief_memory_compact_write`,
  `debrief_memory_add` (stdin JSON payloads, kernel `user_actions` audit).
- `runCli` extended with stdin payload support, abort handling, output caps, and
  normalized error envelopes with stable error codes.
- Five bilingual scheduled skills registered through `ctx.skills.register`:
  `debrief-after-market`, `debrief-news`, `debrief-weekly`, `debrief-monthly`,
  `debrief-compact` (workflows per design §2.5, IRON constraints included).
- `schedule/*.json` presets (8 tasks, RRULE with explicit
  `TZID=Asia/Shanghai`, target `new_once`) and the human command
  `debrief-setup`: kernel validation (`job list --json`) plus idempotent
  list-then-create registration with a summary report.
- Dashboard page v1.5: authenticated read-only route
  `/api/debrief/dashboard?range=…` (registered through `ctx.connection.fetch`)
  and a Client page in the `main` slot with a `sidebar.panellist` navigation
  entry — KPI row, equity/returns SVG charts, composition donut, holdings and
  watchlist tables, range chips, IntersectionObserver lazy loading, responsive
  layout, v2 add-entry placeholders.
- Full zh/en locale coverage: all card titles, table headers, states, empty
  states, page copy, and error-code explanations route through the
  `dsh-client-locale` service with a zh fallback.
- Dependency-free schema validation module (the plugin's zod stand-in; the
  devDependencies budget stays at typescript/vitest/eslint/prettier).
- Mock kernel (`mock/debrief.js`) extended with `report create`,
  `memory compact-write`, `memory add`, `memory compact-candidates`,
  `news latest`, and `job start|status|finish`, with file-backed state.
- Vitest suite (61 tests): tool schemas, CLI argument mapping and stdin writes,
  envelope parsing, render models, card fallback paths, schedule presets,
  skills, and locale parity.
- Engineering baseline: ESLint + Prettier with 0-warning gates, GitHub Actions
  CI (lint → typecheck → test → build → publish) and release-please semantic
  versioning.
- Docs (`docs/`×10), bilingual README, `examples/` one-command demo,
  CODE_OF_CONDUCT / CONTRIBUTING / SECURITY.md, LICENSE.

### Fixed

- Renamed the human command from `debrief setup` to `debrief-setup`: the
  commands registry requires names matching `/^[a-z][a-z0-9_-]*$/`, and the
  old name threw during registration and failed the whole plugin activation.
  Command registration is now also wrapped so a future registration failure
  degrades gracefully instead of taking the plugin down.
- Removed top-level `export` statements from the built `dist/client.js`: the
  Web Host wraps the served client file inside a `factory(require)` function
  body, where module syntax is a SyntaxError ("Failed to load plugins …
  import failed"). A zero-dependency postbuild step
  (`scripts/strip-client-exports.mjs`) strips declaration exports from the
  artifact (the TypeScript source keeps them for the vitest imports), verifies
  zero remaining top-level module syntax, and compile-checks the result inside
  the loader's exact wrapper shape.
- Switched service access to the inspected hard-dependency form —
  `inject: ['tools', 'commands', 'schedule', 'connection', 'skills']` with
  `ctx.commands` / `ctx.schedule` / `ctx.connection` / `ctx.skills`. The
  previous `ctx.get(...)` fallback could not reach commands/schedule/connection
  on the server profile, so `debrief-setup` and the dashboard route were
  silently never registered (startup journal warnings). Registration calls
  remain try/catch-guarded as a safety net.
