# Changelog

All notable changes to this project will be documented in this file. The format
is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
版本由 [release-please](https://github.com/googleapis/release-please) 自动管理。

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
