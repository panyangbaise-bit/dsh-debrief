# Changelog

All notable changes to this project will be documented in this file. The format
is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
版本由 [release-please](https://github.com/googleapis/release-please) 自动管理。

## [Unreleased]

### Added

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
