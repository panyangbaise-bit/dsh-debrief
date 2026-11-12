import { afterAll, beforeEach, describe, expect, it } from 'vitest'
import { rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  WRITE_TOOL_NAMES,
  editCliArgs,
  gateWriteTools,
  runEdit,
  validateEditPayload,
  writeApprovalDecision,
} from '../src/host/edits'
import { runCli } from '../src/host/cli'
import { normalizeConfig } from '../src/host/config'
import { defineTools } from '../src/host/tools'

const MOCK = fileURLToPath(new URL('../mock/debrief.js', import.meta.url))
const MOCK_STATE = join(tmpdir(), 'debrief-mock-edits-test.json')
const config = normalizeConfig({ cliPath: process.execPath, timeoutMs: 10000 }, {})
const cli = (args: string[], stdin?: string) => runCli(config, [MOCK, ...args], stdin === undefined ? {} : { stdin })

beforeEach(() => {
  process.env.DEBRIEF_MOCK_STATE = MOCK_STATE
  try {
    rmSync(MOCK_STATE, { force: true })
  } catch {
    /* state file absent — fine */
  }
})

afterAll(() => {
  try {
    rmSync(MOCK_STATE, { force: true })
  } catch {
    /* already gone */
  }
})

describe('edit tool registration', () => {
  const tools = defineTools(config)

  it('registers all six edit tools with approval-flow descriptions', () => {
    for (const name of WRITE_TOOL_NAMES) {
      const tool = tools.find((candidate) => candidate.name === name)
      expect(tool).toBeDefined()
      expect(tool?.description).toContain('approval confirmation flow')
      expect(tool?.description).toContain('user_actions audit')
    }
  })

  it('declares the documented required fields', () => {
    const holdingAdd = tools.find((candidate) => candidate.name === 'debrief_holding_add')!
    expect((holdingAdd.parameters as { required?: string[] }).required).toEqual([
      'market',
      'symbol',
      'quantity',
      'cost',
    ])
    const watchlistAdd = tools.find((candidate) => candidate.name === 'debrief_watchlist_add')!
    expect((watchlistAdd.parameters as { required?: string[] }).required).toEqual(['market', 'symbol'])
    for (const name of [
      'debrief_holding_update',
      'debrief_holding_remove',
      'debrief_watchlist_update',
      'debrief_watchlist_remove',
    ]) {
      const tool = tools.find((candidate) => candidate.name === name)!
      expect((tool.parameters as { required?: string[] }).required ?? []).toEqual([])
    }
  })

  it('maps entity+action to the kernel CLI commands', () => {
    expect(editCliArgs('holding', 'add')).toEqual(['holdings', 'add'])
    expect(editCliArgs('holding', 'update')).toEqual(['holdings', 'update'])
    expect(editCliArgs('holding', 'remove')).toEqual(['holdings', 'remove'])
    expect(editCliArgs('watchlist', 'add')).toEqual(['watchlist', 'add'])
    expect(editCliArgs('watchlist', 'update')).toEqual(['watchlist', 'update'])
    expect(editCliArgs('watchlist', 'remove')).toEqual(['watchlist', 'remove'])
  })
})

describe('edit payload validation (kernel contract)', () => {
  it('accepts a holding add and emits the exact stdin payload', () => {
    const result = validateEditPayload('holding', 'add', {
      market: 'us',
      symbol: 'NVDA',
      name: '英伟达',
      quantity: 10,
      cost: 120.5,
    })
    expect(result.ok).toBe(true)
    if (result.ok)
      expect(JSON.parse(result.stdin)).toEqual({
        market: 'us',
        symbol: 'NVDA',
        name: '英伟达',
        quantity: 10,
        cost: 120.5,
      })
  })

  it('rejects a holding add missing quantity', () => {
    const result = validateEditPayload('holding', 'add', { market: 'us', symbol: 'NVDA' } as never)
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.error.code).toBe('DEBRIEF_ARGS')
  })

  it('accepts holding update by id and by market+symbol; rejects ambiguous selectors', () => {
    expect(validateEditPayload('holding', 'update', { id: 'hld-2', quantity: 15 }).ok).toBe(true)
    expect(validateEditPayload('holding', 'update', { market: 'us', symbol: 'NVDA', cost: 125 }).ok).toBe(true)
    expect(
      validateEditPayload('holding', 'update', { id: 'hld-2', market: 'us', symbol: 'NVDA', quantity: 1 }).ok,
    ).toBe(false)
    expect(validateEditPayload('holding', 'update', { quantity: 1 }).ok).toBe(false)
  })

  it('requires a patch field on update', () => {
    expect(validateEditPayload('holding', 'update', { id: 'hld-2' }).ok).toBe(false)
    expect(validateEditPayload('watchlist', 'update', { id: 'wl-1', targetPrice: 1300 }).ok).toBe(true)
    expect(validateEditPayload('watchlist', 'update', { id: 'wl-1', alert: true }).ok).toBe(true)
  })

  it('accepts watchlist add with optional targetPrice/alert and remove by market+symbol', () => {
    expect(
      validateEditPayload('watchlist', 'add', {
        market: 'cn',
        symbol: '600519',
        name: '贵州茅台',
        targetPrice: 1300,
        alert: true,
      }).ok,
    ).toBe(true)
    expect(validateEditPayload('watchlist', 'remove', { market: 'cn', symbol: '600519' }).ok).toBe(true)
  })
})

describe('approval gate (tools/pre-execute)', () => {
  it('asks for approval on every write tool with bilingual display reasons', () => {
    for (const name of WRITE_TOOL_NAMES) {
      const decision = writeApprovalDecision(name)
      expect(decision.kind).toBe('ask')
      if (decision.kind === 'ask') {
        expect(decision.displayReason?.en).toBeTruthy()
        expect(decision.displayReason?.zh).toBeTruthy()
      }
    }
  })

  it('delegates non-write tools to the waterfall', async () => {
    const next = () => Promise.resolve({ kind: 'allow' as const })
    const decision = await gateWriteTools({ name: 'debrief_holdings' }, next)
    expect(decision).toEqual({ kind: 'allow' })
  })

  it('owns the decision for write tools (next is never called)', async () => {
    let called = false
    const next = () => {
      called = true
      return Promise.resolve({ kind: 'allow' as const })
    }
    const decision = gateWriteTools({ name: 'debrief_holding_add' }, next)
    expect(decision).toMatchObject({ kind: 'ask' })
    expect(called).toBe(false)
  })
})

describe('runEdit against the mock kernel', () => {
  it('add → conflict → update → remove round-trip', async () => {
    const added = await cli(
      ['holdings', 'add'],
      JSON.stringify({ market: 'us', symbol: 'QQQ', quantity: 5, cost: 500 }),
    )
    expect(added.ok).toBe(true)
    if (added.ok) {
      const row = added.data as Record<string, unknown>
      expect(row.market).toBe('US')
      expect(row.quantity).toBe(5)
    }
    const conflict = await cli(
      ['holdings', 'add'],
      JSON.stringify({ market: 'us', symbol: 'QQQ', quantity: 1, cost: 2 }),
    )
    expect(conflict.ok).toBe(false)
    if (!conflict.ok) expect(conflict.error.code).toBe('DEBRIEF_CONFLICT')
    const updated = await cli(['holdings', 'update'], JSON.stringify({ market: 'us', symbol: 'QQQ', quantity: 8 }))
    expect(updated.ok).toBe(true)
    if (updated.ok) expect((updated.data as Record<string, unknown>).status).toBe('updated')
    const removed = await cli(['holdings', 'remove'], JSON.stringify({ market: 'us', symbol: 'QQQ' }))
    expect(removed.ok).toBe(true)
    if (removed.ok) expect((removed.data as Record<string, unknown>).status).toBe('removed')
    const missing = await cli(['holdings', 'update'], JSON.stringify({ market: 'us', symbol: 'QQQ', quantity: 1 }))
    expect(missing.ok).toBe(false)
    if (!missing.ok) expect(missing.error.code).toBe('DEBRIEF_NOT_FOUND')
  })

  it('watchlist add returns the stored alert switch value', async () => {
    const added = await cli(
      ['watchlist', 'add'],
      JSON.stringify({ market: 'cn', symbol: '601318', name: '中国平安', targetPrice: 55, alert: true }),
    )
    expect(added.ok).toBe(true)
    if (added.ok) {
      const row = added.data as Record<string, unknown>
      expect(row.market).toBe('CN')
      expect(row.alert).toBe(true)
      expect(row.targetPrice).toBe(55)
    }
    const updated = await cli(
      ['watchlist', 'update'],
      JSON.stringify({ market: 'cn', symbol: '601318', targetPrice: null, alert: false }),
    )
    expect(updated.ok).toBe(true)
  })

  it('reports kernel usage errors as DEBRIEF_USAGE', async () => {
    const result = await cli(['holdings', 'add'], '')
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.error.code).toBe('DEBRIEF_USAGE')
  })
})

describe('runEdit host operation', () => {
  it('validates before spawning and returns DEBRIEF_ARGS on bad payloads', async () => {
    const env = await runEdit(config, 'holding', 'add', { market: 'us', symbol: 'X' })
    expect(env.ok).toBe(false)
    if (!env.ok) expect(env.error.code).toBe('DEBRIEF_ARGS')
  })

  it('returns the kernel envelope for valid payloads (CLI missing in tests → structured exec error)', async () => {
    const env = await runEdit(
      { ...config, cliPath: '/definitely/not/a/real/debrief-cli', timeoutMs: 5000 },
      'holding',
      'add',
      {
        market: 'us',
        symbol: 'X',
        quantity: 1,
        cost: 2,
      },
    )
    expect(env.ok).toBe(false)
    if (!env.ok) expect(env.error.code).toBe('DEBRIEF_CLI_NOT_FOUND')
  })
})
