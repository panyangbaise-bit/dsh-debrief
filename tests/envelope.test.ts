import { describe, expect, it } from 'vitest'
import {
  dictT,
  en,
  envelopeOf,
  interpolate,
  pickT,
  renderModel,
  validate,
  zh,
  obj,
  arr,
  num,
  opt,
  s,
} from '../src/client'

describe('locale dictionaries', () => {
  it('keeps en key-complete against zh', () => {
    const zhKeys = Object.keys(zh)
    const enKeys = Object.keys(en)
    expect(enKeys.sort()).toEqual(zhKeys.sort())
    for (const key of zhKeys) {
      expect(typeof en[key]).toBe('string')
      expect(typeof zh[key]).toBe('string')
    }
  })

  it('covers every card, header, state, empty, and error-code string', () => {
    const required = [
      'holdings.title',
      'transactions.title',
      'watchlist.title',
      'report.title',
      'memory.title',
      'analyze.title',
      'jobs.title',
      'dashboard.title',
      'news.title',
      'write.reportCreated',
      'write.compacted',
      'write.added',
      'page.panel',
      'page.loadFailed',
      'page.empty',
      'common.retryHint',
      'error.DEBRIEF_TIMEOUT',
      'error.DEBRIEF_CLI_NOT_FOUND',
      'error.DEBRIEF_PARSE',
    ]
    for (const key of required) {
      expect(zh[key], `missing zh key ${key}`).toBeTruthy()
      expect(en[key], `missing en key ${key}`).toBeTruthy()
    }
  })

  it('interpolates {params}', () => {
    expect(interpolate('共 {total} 笔', { total: 48 })).toBe('共 48 笔')
    expect(interpolate('命中 {count} 条', {})).toBe('命中 {count} 条')
  })

  it('falls back to the zh dictionary when no injected t is available', () => {
    const t = pickT(undefined)
    expect(t('holdings.title')).toBe('持仓总览')
    expect(dictT(zh)('missing.key')).toBe('missing.key')
  })

  it('prefers the injected locale service', () => {
    const injected = (key: string) => (key === 'holdings.title' ? 'POSITIONS' : key)
    expect(pickT(injected)('holdings.title')).toBe('POSITIONS')
  })
})

describe('tool result envelope parsing', () => {
  it('returns PENDING before the block settles', () => {
    const result = envelopeOf(undefined)
    expect(result.error).toEqual({ code: 'PENDING', message: '' })
    expect(result.data).toBeNull()
  })

  it('returns the error envelope for a failed tool call', () => {
    const result = envelopeOf({ kind: 1, isError: true, error: { code: 'DEBRIEF_TIMEOUT', message: 'slow' } })
    expect(result.error).toEqual({ code: 'DEBRIEF_TIMEOUT', message: 'slow' })
  })

  it('parses args and a settled ok envelope', () => {
    const result = envelopeOf({
      kind: 1,
      isError: false,
      call: { argsRaw: '{"status":"open"}' },
      content: [{ type: 'text', text: '{"ok":true,"schemaVersion":1,"data":{"totalMarketValue":123}}' }],
    })
    expect(result.args).toEqual({ status: 'open' })
    expect(result.error).toBeNull()
    expect(result.data).toEqual({ totalMarketValue: 123 })
  })

  it('parses a settled error envelope', () => {
    const result = envelopeOf({
      kind: 1,
      isError: false,
      call: { argsRaw: '{}' },
      content: [{ type: 'text', text: '{"ok":false,"error":{"code":"DEBRIEF_ARGS","message":"bad"}}' }],
    })
    expect(result.error).toEqual({ code: 'DEBRIEF_ARGS', message: 'bad' })
  })

  it('degrades to DEBRIEF_PARSE for non-JSON tool output', () => {
    const result = envelopeOf({
      kind: 1,
      isError: false,
      call: { argsRaw: '{}' },
      content: [{ type: 'text', text: 'not json' }],
    })
    expect(result.error?.code).toBe('DEBRIEF_PARSE')
  })
})

describe('render models (card fallback path)', () => {
  it('accepts a valid holdings payload', () => {
    const result = renderModel('debrief_holdings', {
      totalMarketValue: 1234567,
      dayPnl: 15120,
      dayPnlPct: 1.24,
      totalPnl: 95860,
      totalPnlPct: 8.42,
      asOf: '2026-11-10 09:30',
      positions: [{ symbol: 'AAPL', name: '苹果', market: 'US' }],
    })
    expect(result.ok).toBe(true)
    if (result.ok) expect(Array.isArray(result.model.positions)).toBe(true)
  })

  it('accepts a valid dashboard payload', () => {
    const result = renderModel('debrief_dashboard', {
      kpis: { totalAssets: 1234567, dayPnl: 1, dayPnlPct: 1, totalPnl: 2, totalPnlPct: 2, annualPct: 12.6 },
      series: { range: 90, equity: [1, 2, 3], returns: [0, 1, 2] },
      composition: [{ name: '苹果', value: 12 }],
      holdings: [{ symbol: 'AAPL', name: '苹果', market: 'US' }],
      watchlist: [{ symbol: 'NVDA', name: '英伟达', market: 'US' }],
    })
    expect(result.ok).toBe(true)
  })

  it('degrades (never crashes) on a malformed dashboard payload', () => {
    const result = renderModel('debrief_dashboard', { kpis: { totalAssets: 'not-a-number' } })
    expect(result.ok).toBe(false)
  })

  it('degrades on a non-object payload', () => {
    expect(renderModel('debrief_holdings', null).ok).toBe(false)
    expect(renderModel('debrief_holdings', 42).ok).toBe(false)
  })

  it('keeps unknown tool kinds permissive (unknown versions must not crash the slot)', () => {
    const result = renderModel('debrief_something_else', { hello: 'world' })
    expect(result.ok).toBe(true)
  })
})

describe('client schema validator parity', () => {
  const shape = obj(
    {
      topic: s(),
      instruments: arr(s()),
      evidence: opt(arr(obj({ docId: { type: 'integer' } }))),
      weight: opt(num()),
    },
    ['topic', 'instruments'],
  )

  it('accepts valid values', () => {
    expect(validate(shape, { topic: 'x', instruments: ['AAPL'], evidence: [{ docId: 1 }], weight: 0.5 }).ok).toBe(true)
  })

  it('rejects invalid values with a path', () => {
    const result = validate(shape, { topic: 'x', instruments: ['AAPL'], evidence: [{ docId: 'x' }] })
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.path).toBe('$.evidence[0].docId')
  })
})
