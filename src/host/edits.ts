/**
 * v2 write operations — one implementation, two callers (UserActions pattern):
 *
 * 1. The Host operation: `runEdit` validates the payload against the exact
 *    kernel contract and runs the CLI once (`holdings|watchlist add|update|
 *    remove --json`, payload on stdin). The kernel audits every write into
 *    its user_actions ledger and answers conflict codes DEBRIEF_CONFLICT.
 * 2. The Client-callable entry: POST /api/debrief/mutate (connection.fetch,
 *    owner cookie) — the Dashboard modal submits through this route.
 * 3. The agent tools: debrief_holding_* / debrief_watchlist_* call the same
 *    `runEdit`. Agent-initiated writes additionally pass the DSH approval
 *    confirmation flow: a tools/pre-execute listener returns `ask` for these
 *    names; when approval support is unavailable the framework converts the
 *    ask into a denial, so a write is refused instead of silently executed.
 */
import { runCli, type Envelope } from './cli.js'
import { validate, n, obj, opt, s, b } from './schema.js'
import type { DebriefConfig } from './config.js'
import type { PreToolDecision, ToolExecutionLike } from './types.js'

export type EditEntity = 'holding' | 'watchlist'
export type EditAction = 'add' | 'update' | 'remove'

/** Agent tools gated by the approval confirmation flow. */
export const WRITE_TOOL_NAMES: ReadonlySet<string> = new Set([
  'debrief_holding_add',
  'debrief_holding_update',
  'debrief_holding_remove',
  'debrief_watchlist_add',
  'debrief_watchlist_update',
  'debrief_watchlist_remove',
])

export const APPROVAL_REASONS = {
  en: 'This write changes portfolio data and is recorded in the kernel user_actions audit. Approve to proceed.',
  zh: '该写操作会修改组合数据并写入内核 user_actions 审计。请确认是否执行。',
} as const

/** The approval decision asked for every v2 write tool. */
export function writeApprovalDecision(name: string): PreToolDecision {
  return {
    kind: 'ask',
    reason: `${name}: ${APPROVAL_REASONS.en}`,
    displayReason: { en: APPROVAL_REASONS.en, zh: APPROVAL_REASONS.zh },
  }
}

/**
 * tools/pre-execute gate: own the decision for write tools (ask for approval),
 * delegate everything else to the waterfall.
 */
export function gateWriteTools(
  exec: ToolExecutionLike,
  next: () => Promise<PreToolDecision> | PreToolDecision,
): Promise<PreToolDecision> | PreToolDecision {
  if (WRITE_TOOL_NAMES.has(exec.name)) return writeApprovalDecision(exec.name)
  return next()
}

// ---- kernel payload shapes (task-5 contract) ---------------------------------

const marketShape = s()
const symbolShape = s()
const idShape = s()

const holdingAddShape = obj(
  {
    market: marketShape,
    symbol: symbolShape,
    name: opt(s()),
    quantity: n(),
    cost: n(),
  },
  ['market', 'symbol', 'quantity', 'cost'],
)

const holdingUpdateShape = obj(
  {
    id: opt(idShape),
    market: opt(marketShape),
    symbol: opt(symbolShape),
    quantity: opt(n()),
    cost: opt(n()),
  },
  [],
)

const holdingRemoveShape = obj(
  {
    id: opt(idShape),
    market: opt(marketShape),
    symbol: opt(symbolShape),
  },
  [],
)

const watchlistAddShape = obj(
  {
    market: marketShape,
    symbol: symbolShape,
    name: opt(s()),
    targetPrice: opt(n()),
    alert: opt(b()),
  },
  ['market', 'symbol'],
)

const watchlistUpdateShape = obj(
  {
    id: opt(idShape),
    market: opt(marketShape),
    symbol: opt(symbolShape),
    targetPrice: opt(n()),
    alert: opt(b()),
  },
  [],
)

const watchlistRemoveShape = obj(
  {
    id: opt(idShape),
    market: opt(marketShape),
    symbol: opt(symbolShape),
  },
  [],
)

type EditShapeKey =
  'holdingAdd' | 'holdingUpdate' | 'holdingRemove' | 'watchlistAdd' | 'watchlistUpdate' | 'watchlistRemove'

function shapeKey(entity: EditEntity, action: EditAction): EditShapeKey {
  if (entity === 'holding') {
    return action === 'add' ? 'holdingAdd' : action === 'update' ? 'holdingUpdate' : 'holdingRemove'
  }
  return action === 'add' ? 'watchlistAdd' : action === 'update' ? 'watchlistUpdate' : 'watchlistRemove'
}

const SHAPES: Record<EditShapeKey, ReturnType<typeof obj>> = {
  holdingAdd: holdingAddShape,
  holdingUpdate: holdingUpdateShape,
  holdingRemove: holdingRemoveShape,
  watchlistAdd: watchlistAddShape,
  watchlistUpdate: watchlistUpdateShape,
  watchlistRemove: watchlistRemoveShape,
}

/** update/remove must carry id XOR (market+symbol); update needs one field to change. */
function editCheckArgs(entity: EditEntity, action: EditAction, args: Record<string, unknown>): string | undefined {
  const id = typeof args.id === 'string' && args.id !== ''
  const bySymbol =
    typeof args.market === 'string' && args.market !== '' && typeof args.symbol === 'string' && args.symbol !== ''
  if (action === 'update' || action === 'remove') {
    if (id === bySymbol) return 'exactly one of id or market+symbol is required'
    if (!id && !bySymbol) return 'id or market+symbol is required'
  }
  if (action === 'update') {
    const patch = entity === 'holding' ? ['quantity', 'cost'] : ['targetPrice', 'alert']
    if (!patch.some((key) => args[key] !== undefined)) return `at least one of ${patch.join('/')} is required`
  }
  return undefined
}

export function validateEditPayload(
  entity: EditEntity,
  action: EditAction,
  args: Record<string, unknown>,
): { ok: true; stdin: string } | { ok: false; error: { code: string; message: string } } {
  const shape = SHAPES[shapeKey(entity, action)]
  const result = validate(shape, args)
  if (!result.ok) {
    return { ok: false, error: { code: 'DEBRIEF_ARGS', message: `invalid payload: ${result.path} ${result.reason}` } }
  }
  const conditional = editCheckArgs(entity, action, args)
  if (conditional !== undefined) {
    return { ok: false, error: { code: 'DEBRIEF_ARGS', message: conditional } }
  }
  return { ok: true, stdin: JSON.stringify(result.value) }
}

/** CLI argument vector for one edit operation. */
export function editCliArgs(entity: EditEntity, action: EditAction): readonly string[] {
  return [entity === 'holding' ? 'holdings' : 'watchlist', action]
}

/** The single Host operation both callers execute. */
export function runEdit(
  config: DebriefConfig,
  entity: EditEntity,
  action: EditAction,
  args: Record<string, unknown>,
  signal?: AbortSignal,
): Promise<Envelope> {
  const checked = validateEditPayload(entity, action, args)
  if (!checked.ok) {
    return Promise.resolve({ ok: false, schemaVersion: 1, error: checked.error })
  }
  return runCli(config, editCliArgs(entity, action), { signal, stdin: checked.stdin })
}
