/**
 * Registry-ready tool definitions in the compiled raw-schema form, mirroring
 * what `defineTool` produces for the same author input. Eleven read tools
 * (including the dashboard aggregate, the news feed, and the Telegram notify
 * bridge) plus three whitelisted write tools used by the scheduled debrief
 * skills.
 */
import { runCli, type Envelope } from './cli.js'
import type { ContentBlock, JsonNode, ToolDefinition, ToolRunContext } from './types.js'
import { validate, arr, obj, opt, s } from './schema.js'
import { runEdit, type EditAction, type EditEntity } from './edits.js'
import {
  checkProfileWriteArgs,
  profileWriteShape,
  validateProfileWritePayload,
} from './profile.js'
import type { DebriefConfig } from './config.js'

const OUT_SCHEMA: JsonNode = { description: 'debrief kernel envelope' }

function jsonOut(_args: unknown, value: unknown): ContentBlock[] {
  return [{ type: 'text', text: JSON.stringify(value) }]
}

/** String property node in compiled form. */
const sProp = (description: string): JsonNode => ({ type: 'string', description })
/** Integer property node in compiled form. */
const iProp = (description: string): JsonNode => ({ type: 'integer', description })
/** Boolean property node in compiled form. */
const bProp = (description: string): JsonNode => ({ type: 'boolean', description })
/** Number property node in compiled form. */
const nProp = (description: string): JsonNode => ({ type: 'number', description })

interface ToolSpec {
  name: string
  description: string
  parameters: Record<string, JsonNode>
  required: readonly string[]
  /** CLI subcommand path, one element per argv token (`['memory', 'compact-write']`). */
  command: readonly string[]
  /** CLI argument vector for the command; empty for the passthrough tools. */
  argsOf?: (args: Record<string, unknown>) => readonly string[]
  /** Write kind whose validated payload travels on stdin (whitelisted writes). */
  writeKind?: 'reportCreate' | 'compactWrite' | 'memoryAdd' | 'profileWrite'
  /** v2 edit operation (holdings/watchlist add|update|remove), approval-gated. */
  edit?: { entity: EditEntity; action: EditAction }
  /** Non-write commands that still take a JSON payload on stdin (e.g. notify send). */
  stdinFrom?: (args: Record<string, unknown>) => string | undefined
  /** Extra conditional argument validation (e.g. mutually exclusive inputs). */
  checkArgs?: (args: Record<string, unknown>) => string | undefined
}

function missingRequired(args: Record<string, unknown>, key: string): boolean {
  const value = args[key]
  if (value === undefined || value === null || value === '') return true
  if (Array.isArray(value) && value.length === 0) return true
  return false
}

function tool(config: DebriefConfig, spec: ToolSpec): ToolDefinition {
  return {
    name: spec.name,
    description: spec.description,
    parameters: {
      type: 'object',
      properties: spec.parameters,
      ...(spec.required.length > 0 ? { required: spec.required } : {}),
    },
    output: { schema: OUT_SCHEMA, render: jsonOut },
    async execute(rawArgs, exec: ToolRunContext): Promise<Envelope> {
      const args = (rawArgs && typeof rawArgs === 'object' ? rawArgs : {}) as Record<string, unknown>
      for (const key of spec.required) {
        if (missingRequired(args, key)) {
          return {
            ok: false,
            schemaVersion: 1,
            error: { code: 'DEBRIEF_ARGS', message: `missing required argument ${key}` },
          }
        }
      }
      const checkFailure = spec.checkArgs ? spec.checkArgs(args) : undefined
      if (checkFailure !== undefined) {
        return { ok: false, schemaVersion: 1, error: { code: 'DEBRIEF_ARGS', message: checkFailure } }
      }
      if (spec.edit) {
        return runEdit(config, spec.edit.entity, spec.edit.action, args, exec.signal)
      }
      if (spec.writeKind) {
        const checked = validateWritePayload(spec.writeKind, args)
        if (!checked.ok || checked.stdin === undefined) {
          return {
            ok: false,
            schemaVersion: 1,
            error: checked.error ?? { code: 'DEBRIEF_ARGS', message: 'invalid write payload' },
          }
        }
        return runCli(config, [...spec.command], { signal: exec.signal, stdin: checked.stdin })
      }
      if (spec.stdinFrom) {
        const stdin = spec.stdinFrom(args)
        return runCli(config, [...spec.command], { signal: exec.signal, stdin })
      }
      if (spec.argsOf) {
        return runCli(config, [...spec.command, ...spec.argsOf(args)], { signal: exec.signal })
      }
      return runCli(config, [...spec.command], { signal: exec.signal })
    },
  }
}

// ---- write payload shapes (validated before they reach the CLI) -------------

const metricShape = obj({ label: s(), value: s() }, ['label', 'value'])
const chartShape = obj({ title: opt(s()), unit: opt(s()), points: arr({ type: 'number' }) }, ['points'])
const evidenceRefShape = obj({ docId: { type: 'integer' }, quote: opt(s()) }, ['docId'])

export function reportCreatePayload(args: Record<string, unknown>): string {
  return JSON.stringify({
    market: args.market,
    title: args.title,
    summary: args.summary,
    ...(typeof args.fullText === 'string' && args.fullText !== '' ? { fullText: args.fullText } : {}),
    ...(Array.isArray(args.metrics) && args.metrics.length > 0 ? { metrics: args.metrics } : {}),
    ...(args.chart && typeof args.chart === 'object' ? { chart: args.chart } : {}),
    ...(typeof args.jobId === 'string' && args.jobId !== '' ? { jobId: args.jobId } : {}),
  })
}

export function compactWritePayload(args: Record<string, unknown>): string {
  if (args.retire === true) return JSON.stringify({ topic: args.topic, retire: true })
  return JSON.stringify({
    topic: args.topic,
    instruments: args.instruments,
    summary: args.summary,
    evidenceRefs: args.evidenceRefs,
    timeRange: args.timeRange,
    ...(typeof args.confidence === 'string' && args.confidence !== '' ? { confidence: args.confidence } : {}),
    ...(typeof args.caveats === 'string' && args.caveats !== '' ? { caveats: args.caveats } : {}),
  })
}

export function memoryAddPayload(args: Record<string, unknown>): string {
  return JSON.stringify({
    sourceType: args.sourceType,
    content: args.content,
    instruments: args.instruments,
    ...(typeof args.occurredAt === 'string' && args.occurredAt !== '' ? { occurredAt: args.occurredAt } : {}),
  })
}

/** Export the payload shapes for the test suite. */
export const writePayloadShapes = {
  reportCreate: obj(
    {
      market: s(),
      title: s(),
      summary: s(),
      fullText: opt(s()),
      metrics: opt(arr(metricShape)),
      chart: opt(chartShape),
      jobId: opt(s()),
    },
    ['market', 'title', 'summary'],
  ),
  compactWrite: obj(
    {
      topic: s(),
      retire: opt({ type: 'boolean' }),
      instruments: opt(arr(s())),
      summary: opt(s()),
      evidenceRefs: opt(arr(evidenceRefShape)),
      timeRange: opt(obj({ from: s(), to: s() }, ['from', 'to'])),
      confidence: opt(s()),
      caveats: opt(s()),
    },
    ['topic'],
  ),
  memoryAdd: obj(
    {
      sourceType: s(),
      content: s(),
      instruments: arr(s()),
      occurredAt: opt(s()),
    },
    ['sourceType', 'content', 'instruments'],
  ),
  profileWrite: profileWriteShape,
}

const WRITE_NOTE =
  ' Whitelisted write tool for scheduled debrief skill sessions; every write is recorded in the kernel user_actions audit ledger.'

/** Validate a write payload against its declared shape and return the CLI stdin JSON. */
export function validateWritePayload(
  kind: 'reportCreate' | 'compactWrite' | 'memoryAdd' | 'profileWrite',
  args: Record<string, unknown>,
): {
  ok: boolean
  stdin?: string
  error?: { code: string; message: string }
} {
  if (kind === 'profileWrite') {
    // Shared with the /api/debrief/profile route (one operation, two callers).
    const checked = validateProfileWritePayload(args)
    return checked.ok ? { ok: true, stdin: checked.stdin } : { ok: false, error: checked.error }
  }
  const result = validate(writePayloadShapes[kind], args)
  if (!result.ok) {
    return { ok: false, error: { code: 'DEBRIEF_ARGS', message: `invalid payload: ${result.path} ${result.reason}` } }
  }
  const stdin =
    kind === 'reportCreate'
      ? reportCreatePayload(args)
      : kind === 'compactWrite'
        ? compactWritePayload(args)
        : memoryAddPayload(args)
  return { ok: true, stdin }
}

// ---- definitions -------------------------------------------------------------

/** debrief_news CLI argument vector (exported for the test suite). */
export function newsArgs(args: Record<string, unknown>): readonly string[] {
  return [
    'latest',
    ...(args.limit ? ['--limit', String(args.limit)] : []),
    ...(args.refresh === false ? ['--no-refresh'] : []),
    ...(args.notify === true ? ['--notify'] : []),
  ]
}

/** debrief_telegram CLI argument vector (exported for the test suite). */
export function telegramArgs(args: Record<string, unknown>): readonly string[] {
  return [String(args.action)]
}

/** `--refresh` suffix shared by the quote-backed read commands (exported for tests). */
export function refreshArgs(args: Record<string, unknown>): readonly string[] {
  return args.refresh === true ? ['--refresh'] : []
}

const REFRESH_NOTE =
  'When true, force-refresh quotes for every row right now (slow). When omitted, stale quotes refresh automatically.'

export function defineTools(config: DebriefConfig): ToolDefinition[] {
  return [
    tool(config, {
      name: 'debrief_holdings',
      description:
        'Read the current portfolio holdings: symbol, name, quantity, cost, last price, market value, unrealized PnL, and weight.',
      parameters: {
        status: sProp("Only open positions when 'open'; all positions when omitted."),
        refresh: bProp(REFRESH_NOTE),
      },
      required: [],
      command: ['holdings'],
      argsOf: (a) => [...(a.status ? ['--status', String(a.status)] : []), ...refreshArgs(a)],
    }),
    tool(config, {
      name: 'debrief_transactions',
      description: 'List executed trades, newest first, with pagination and an optional ISO-8601 date window.',
      parameters: {
        ticker: sProp('Optional symbol filter, e.g. AAPL.'),
        limit: iProp('Page size. Default 20, max 100.'),
        offset: iProp('Zero-based row offset. Default 0.'),
        since: sProp('Optional ISO-8601 start (inclusive), e.g. 2026-11-09T00:00:00.'),
        until: sProp('Optional ISO-8601 end (exclusive).'),
      },
      required: [],
      command: ['transactions'],
      argsOf: (a) => [
        ...(a.ticker ? ['--ticker', String(a.ticker)] : []),
        ...(a.limit ? ['--limit', String(a.limit)] : []),
        ...(a.offset ? ['--offset', String(a.offset)] : []),
        ...(a.since ? ['--since', String(a.since)] : []),
        ...(a.until ? ['--until', String(a.until)] : []),
      ],
    }),
    tool(config, {
      name: 'debrief_watchlist',
      description:
        'Read the watchlist: instruments under observation with target price, distance to target, and alert state.',
      parameters: { refresh: bProp(REFRESH_NOTE) },
      required: [],
      command: ['watchlist'],
      argsOf: refreshArgs,
    }),
    tool(config, {
      name: 'debrief_instruments',
      description:
        'Search investable instruments for adding holdings or watchlist entries. Stocks/ETFs/funds resolve through the local akshare catalog with a live suggest fallback; crypto resolves through CoinGecko. Returns symbol, name, market, currency, and asset class per match.',
      parameters: {
        market: sProp('One of: us, cn, hk, crypto.'),
        query: sProp('Code, name, or pinyin fragment; at least 2 characters.'),
      },
      required: ['market', 'query'],
      command: ['instruments'],
      argsOf: (a) => ['search', '--market', String(a.market), '--query', String(a.query)],
    }),
    tool(config, {
      name: 'debrief_report',
      description:
        'Read an analysis report from the report center: summary, metrics, and chart payload references. By id, the latest of a market, or a list window (list: true) for weekly/monthly reviews.',
      parameters: {
        id: sProp('Report id; takes precedence over market and list.'),
        market: sProp('One of: us, cn, hk, crypto. Latest report of that market when id is omitted.'),
        list: bProp('List reports in a window (newest first) instead of the single latest.'),
        since: sProp('Optional ISO-8601 start (inclusive), for list.'),
        until: sProp('Optional ISO-8601 end (exclusive), for list.'),
        limit: iProp('Page size for list. Default 50, max 100.'),
      },
      required: [],
      command: ['report'],
      argsOf: (a) =>
        a.id
          ? ['--id', String(a.id)]
          : a.list
            ? [
                'list',
                ...(a.market ? ['--market', String(a.market)] : []),
                ...(a.since ? ['--since', String(a.since)] : []),
                ...(a.until ? ['--until', String(a.until)] : []),
                ...(a.limit ? ['--limit', String(a.limit)] : []),
              ]
            : ['latest', ...(a.market ? ['--market', String(a.market)] : [])],
    }),
    tool(config, {
      name: 'debrief_memory',
      description:
        'Search long-term and short-term investment memory. Long-term hits come first as structured summaries with confidence and evidence citations; short-term hits follow as fine-grained evidence snapshots. With compactCandidates=true, returns the out-of-window uncompacted candidates for the daily compaction skill instead.',
      parameters: {
        query: sProp('Topic, instrument, or decision phrase to retrieve. Optional when compactCandidates is true.'),
        compactCandidates: bProp('Return the out-of-window compaction candidate list (for the debrief-compact skill).'),
      },
      required: [],
      command: ['memory'],
      argsOf: (a) =>
        a.compactCandidates === true ? ['compact-candidates'] : ['search', '--query', String(a.query ?? '')],
      checkArgs: (a) =>
        a.compactCandidates === true || (typeof a.query === 'string' && a.query.trim() !== '')
          ? undefined
          : 'query is required unless compactCandidates is true',
    }),
    tool(config, {
      name: 'debrief_analyze',
      description:
        'Prepare an after-market analysis input package for one market: recent quotes, news, and candidate memory evidence. Synthesize the conclusion yourself from the package, then present it; the package is bounded and ready to read.',
      parameters: { market: sProp('One of: us, cn, hk, crypto.'), refresh: bProp(REFRESH_NOTE) },
      required: ['market'],
      command: ['analysis'],
      argsOf: (a) => ['prepare', '--market', String(a.market), ...refreshArgs(a)],
    }),
    tool(config, {
      name: 'debrief_jobs',
      description:
        'List recent scheduled-task runs from the job ledger: kind, time, status, duration, and error code when failed. Pass since/until to scope to a week or month.',
      parameters: {
        limit: iProp('Page size. Default 50, max 100.'),
        since: sProp('Optional ISO-8601 start (inclusive).'),
        until: sProp('Optional ISO-8601 end (exclusive).'),
      },
      required: [],
      command: ['job'],
      argsOf: (a) => [
        'list',
        ...(a.limit ? ['--limit', String(a.limit)] : []),
        ...(a.since ? ['--since', String(a.since)] : []),
        ...(a.until ? ['--until', String(a.until)] : []),
      ],
    }),
    tool(config, {
      name: 'debrief_dashboard',
      description:
        'Read the dashboard aggregate: KPIs (total assets, daily and total return), equity and cumulative-return series, portfolio composition, holdings, and watchlist in one payload.',
      parameters: {
        range: sProp('Series length in days: 30, 90, 200, or 365. Default 90.'),
        refresh: bProp(REFRESH_NOTE),
      },
      required: [],
      command: ['dashboard'],
      argsOf: (a) => [...(a.range ? ['--range', String(a.range)] : []), ...refreshArgs(a)],
    }),
    tool(config, {
      name: 'debrief_news',
      description:
        'Read the latest news feed: live-fetch (with persistence) on each call, or read the last collected batch with refresh=false. Returns title, source, published time, summary and URL; filter for relevance yourself.',
      parameters: {
        limit: iProp('Maximum items. Default 20, max 100.'),
        refresh: bProp('When false, skip the live fetch and read the last collected batch only. Default true.'),
        notify: bProp(
          'Legacy: when true, newly fetched RAW items are pushed to Telegram (no digest). Prefer composing a digest and pushing it with debrief_telegram action "send". Default false.',
        ),
      },
      required: [],
      command: ['news'],
      argsOf: newsArgs,
    }),
    tool(config, {
      name: 'debrief_telegram',
      description:
        'Send or inspect the Telegram notification channel used for debrief pushes. ' +
        '"send" pushes an agent-composed digest/alert message (markdown bold and [text](url) links become Telegram HTML, long messages are split automatically); ' +
        '"test" sends a fixed test message; "status" reports whether Telegram is configured (token is masked).',
      parameters: {
        action: sProp(
          '"send" pushes text to the configured chat; "test" sends a fixed test message; "status" reports configuration state.',
        ),
        text: sProp(
          'Message to push when action is "send" (required for send). Keep it concise; markdown **bold**, bullet lists, and [text](url) links are converted to Telegram HTML.',
        ),
      },
      required: ['action'],
      checkArgs: (a) =>
        a.action === 'send' && (typeof a.text !== 'string' || a.text.trim() === '')
          ? 'action "send" requires a non-empty text'
          : undefined,
      command: ['notify'],
      argsOf: telegramArgs,
      stdinFrom: (a) => (a.action === 'send' ? JSON.stringify({ text: String(a.text ?? '') }) : undefined),
    }),
    tool(config, {
      name: 'debrief_report_create',
      description:
        'Write an analysis report produced by the DSH agent back to the kernel report center and mark the job ledger entry. Runs `report create --json` with the payload on stdin.' +
        WRITE_NOTE,
      parameters: {
        market: sProp('Market the report covers: us, cn, hk, crypto, or weekly/monthly for reviews.'),
        title: sProp('Report title.'),
        summary: sProp('Structured conclusion: one-line summary, key changes, portfolio impact, action signals.'),
        fullText: sProp('Optional full analysis text.'),
        metrics: {
          type: 'array',
          description: 'Optional metric rows.',
          items: {
            type: 'object',
            description: 'A labeled metric.',
            properties: { label: sProp('Metric label.'), value: sProp('Metric value.') },
            required: ['label', 'value'],
          },
        },
        chart: {
          type: 'object',
          description: 'Optional SVG chart payload.',
          properties: {
            title: sProp('Chart title.'),
            unit: sProp('Value unit.'),
            points: { type: 'array', description: 'Sampled series points.', items: { type: 'number' } },
          },
          required: ['points'],
        },
        jobId: sProp('Optional job_runs ledger id from debrief_analyze; links the report to its run.'),
      },
      required: ['market', 'title', 'summary'],
      command: ['report', 'create'],
      writeKind: 'reportCreate',
    }),
    tool(config, {
      name: 'debrief_memory_compact_write',
      description:
        'Write one compacted long-term memory summary generated by the DSH agent back to the kernel; same topic re-compacts as version+1. Runs `memory compact-write --json` with the payload on stdin.' +
        WRITE_NOTE,
      parameters: {
        topic: sProp('Stable topic key, e.g. position-aapl-rationale.'),
        instruments: {
          type: 'array',
          description: 'Related instruments.',
          items: sProp('Symbol.'),
        },
        summary: sProp('Structured summary: conclusion, rationale, conditions.'),
        evidenceRefs: {
          type: 'array',
          description: 'Short-term evidence citations; each docId must come from compact-candidates.',
          items: {
            type: 'object',
            properties: {
              docId: { type: 'integer', description: 'Memory document id.' },
              quote: sProp('Optional short quote from the source document.'),
            },
            required: ['docId'],
          },
        },
        timeRange: {
          type: 'object',
          description: 'Covered time window.',
          properties: { from: sProp('ISO start.'), to: sProp('ISO end.') },
          required: ['from', 'to'],
        },
        confidence: sProp('high, medium, or low.'),
        caveats: sProp('Known limitations and unknowns.'),
        retire: bProp('Retire (archive) this topic instead of writing a summary — forgetting, e.g. for ops-* noise or stale low-confidence memories. Only `topic` is required when retiring.'),
      },
      required: ['topic'],
      command: ['memory', 'compact-write'],
      writeKind: 'compactWrite',
    }),
    tool(config, {
      name: 'debrief_memory_add',
      description:
        'Append one decision or observation snapshot to short-term memory evidence. Use it in ANY session to sediment durable investment facts: user trade decisions, risk/discipline statements, and investment Q&A conclusions (sourceType=conversation). The daily compaction promotes durable entries into long-term memory. Runs `memory add --json` with the payload on stdin.' +
        WRITE_NOTE,
      parameters: {
        sourceType: sProp('Snapshot kind: decision, trade, report, note, or conversation.'),
        content: sProp('Snapshot text; quote the original decision verbatim when available.'),
        instruments: {
          type: 'array',
          description: 'Related instruments.',
          items: sProp('Symbol.'),
        },
        occurredAt: sProp('Optional ISO timestamp; defaults to now.'),
      },
      required: ['sourceType', 'content', 'instruments'],
      command: ['memory', 'add'],
      writeKind: 'memoryAdd',
    }),
    // ---- v2 edits: one operation, two callers (UserActions pattern) ---------
    // Agent-initiated writes pass the DSH approval confirmation flow
    // (tools/pre-execute `ask`); the kernel audits every write.
    tool(config, {
      name: 'debrief_holding_add',
      description:
        'Add a holding to the portfolio through the kernel `holdings add` command (payload on stdin). Triggers the DSH approval confirmation flow before execution; every write is recorded in the kernel user_actions audit ledger.',
      parameters: {
        market: sProp('Market: us, cn, hk, or crypto.'),
        symbol: sProp('Instrument symbol.'),
        name: sProp('Optional display name.'),
        quantity: nProp('Held quantity.'),
        cost: nProp('Average cost per unit.'),
      },
      required: ['market', 'symbol', 'quantity', 'cost'],
      command: ['holdings', 'add'],
      edit: { entity: 'holding', action: 'add' },
    }),
    tool(config, {
      name: 'debrief_holding_update',
      description:
        'Update a holding (quantity and/or cost) through the kernel `holdings update` command (payload on stdin). Identify it by id, or by market+symbol. Triggers the DSH approval confirmation flow before execution; every write is recorded in the kernel user_actions audit ledger.',
      parameters: {
        id: sProp('Holding id; use id OR market+symbol.'),
        market: sProp('Market: us, cn, hk, or crypto (with symbol).'),
        symbol: sProp('Instrument symbol (with market).'),
        quantity: nProp('New held quantity.'),
        cost: nProp('New average cost per unit.'),
      },
      required: [],
      command: ['holdings', 'update'],
      edit: { entity: 'holding', action: 'update' },
    }),
    tool(config, {
      name: 'debrief_holding_remove',
      description:
        'Remove a holding through the kernel `holdings remove` command (payload on stdin). Identify it by id, or by market+symbol. Triggers the DSH approval confirmation flow before execution; every write is recorded in the kernel user_actions audit ledger.',
      parameters: {
        id: sProp('Holding id; use id OR market+symbol.'),
        market: sProp('Market: us, cn, hk, or crypto (with symbol).'),
        symbol: sProp('Instrument symbol (with market).'),
      },
      required: [],
      command: ['holdings', 'remove'],
      edit: { entity: 'holding', action: 'remove' },
    }),
    tool(config, {
      name: 'debrief_watchlist_add',
      description:
        'Add a watchlist entry through the kernel `watchlist add` command (payload on stdin). Triggers the DSH approval confirmation flow before execution; every write is recorded in the kernel user_actions audit ledger.',
      parameters: {
        market: sProp('Market: us, cn, hk, or crypto.'),
        symbol: sProp('Instrument symbol.'),
        name: sProp('Optional display name.'),
        targetPrice: nProp('Optional target price that arms the alert.'),
        alert: bProp('Optional alert state; defaults to the kernel default.'),
      },
      required: ['market', 'symbol'],
      command: ['watchlist', 'add'],
      edit: { entity: 'watchlist', action: 'add' },
    }),
    tool(config, {
      name: 'debrief_watchlist_update',
      description:
        'Update a watchlist entry (target price and/or alert state) through the kernel `watchlist update` command (payload on stdin). Identify it by id, or by market+symbol. Triggers the DSH approval confirmation flow before execution; every write is recorded in the kernel user_actions audit ledger.',
      parameters: {
        id: sProp('Watchlist entry id; use id OR market+symbol.'),
        market: sProp('Market: us, cn, hk, or crypto (with symbol).'),
        symbol: sProp('Instrument symbol (with market).'),
        targetPrice: nProp('New target price.'),
        alert: bProp('New alert state.'),
      },
      required: [],
      command: ['watchlist', 'update'],
      edit: { entity: 'watchlist', action: 'update' },
    }),
    tool(config, {
      name: 'debrief_watchlist_remove',
      description:
        'Remove a watchlist entry through the kernel `watchlist remove` command (payload on stdin). Identify it by id, or by market+symbol. Triggers the DSH approval confirmation flow before execution; every write is recorded in the kernel user_actions audit ledger.',
      parameters: {
        id: sProp('Watchlist entry id; use id OR market+symbol.'),
        market: sProp('Market: us, cn, hk, or crypto (with symbol).'),
        symbol: sProp('Instrument symbol (with market).'),
      },
      required: [],
      command: ['watchlist', 'remove'],
      edit: { entity: 'watchlist', action: 'remove' },
    }),
    // ---- investment memory profile (whitelisted write; kernel caller-derived updatedBy) ----
    tool(config, {
      name: 'debrief_profile',
      description:
        'Read the investment memory profile: six digest sections (portfolio, habits, discipline, risk, advice, decisions) with per-section content and updatedBy, the profile version, evidence docIds, the verbatim trading_discipline excerpt, and the pre-assembled evidence package (active long-term topics, holdings/transaction structure, recent decision documents). The evidence package is the ONLY allowed input when regenerating the digest — never search memory freely for generation; free search (debrief_memory) is only for answering questions. Read this before rewriting sections so you have the current version for expectedVersion and know which sections the user hand-edited.',
      parameters: {},
      required: [],
      command: ['profile', 'get'],
    }),
    tool(config, {
      name: 'debrief_profile_write',
      description:
        'Write investment memory profile sections back to the kernel. Partial update: only the sections listed in `sections` change; omitted sections keep their current content. The kernel derives updatedBy from the caller, so this tool writes every listed section as agent-authored. Pass `expectedVersion` (the version you just read) for optimistic concurrency; on mismatch the kernel answers DEBRIEF_CONFLICT — re-read and merge. When `protectUserSections` is true, sections whose current updatedBy is "user" are left untouched and reported in `preserved` — always set it for scheduled regeneration, never when the user explicitly asked to change a section.' +
        WRITE_NOTE,
      parameters: {
        sections: {
          type: 'array',
          description: 'Sections to write (partial update). Each item: key and the full new content.',
          items: {
            type: 'object',
            properties: {
              key: sProp('One of: portfolio, habits, discipline, risk, advice, decisions.'),
              content: sProp('Full new text of this section; empty string clears it.'),
            },
            required: ['key', 'content'],
          },
        },
        evidenceRefs: {
          type: 'array',
          description: 'Replaces the whole evidence-reference list; each docId must exist in memory documents.',
          items: {
            type: 'object',
            properties: { docId: { type: 'integer', description: 'Memory document id.' } },
            required: ['docId'],
          },
        },
        expectedVersion: iProp('Optional version from the debrief_profile read; mismatch answers DEBRIEF_CONFLICT.'),
        protectUserSections: bProp('True = skip sections the user hand-edited (updatedBy "user"); use for scheduled regeneration.'),
      },
      required: [],
      command: ['profile', 'write', '--by', 'agent'],
      writeKind: 'profileWrite',
      checkArgs: checkProfileWriteArgs,
    }),
  ]
}
