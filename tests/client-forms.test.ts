import { describe, expect, it } from 'vitest'
import {
  buildMutationRequest,
  editSelector,
  parseInstrumentsPayload,
  validateHoldingForm,
  validateWatchForm,
} from '../src/client'

describe('holding form validation', () => {
  const base = { market: 'us', symbol: 'AAPL', name: '苹果', quantity: '10', cost: '180.2' }

  it('accepts a complete form', () => {
    expect(validateHoldingForm(base)).toBeNull()
  })

  it('requires a selection, a positive quantity, and a non-negative cost', () => {
    expect(validateHoldingForm({ ...base, symbol: '' })).toBe('edit.needSelection')
    expect(validateHoldingForm({ ...base, quantity: '' })).toBe('edit.invalidQuantity')
    expect(validateHoldingForm({ ...base, quantity: '0' })).toBe('edit.invalidQuantity')
    expect(validateHoldingForm({ ...base, quantity: 'abc' })).toBe('edit.invalidQuantity')
    expect(validateHoldingForm({ ...base, cost: '' })).toBe('edit.invalidCost')
    expect(validateHoldingForm({ ...base, cost: '-1' })).toBe('edit.invalidCost')
  })
})

describe('watchlist form validation', () => {
  it('requires a selection; target price is optional but must be positive when present', () => {
    expect(validateWatchForm({ market: 'cn', symbol: '', targetPrice: '', alert: false })).toBe('edit.needSelection')
    expect(validateWatchForm({ market: 'cn', symbol: '600519', targetPrice: '', alert: false })).toBeNull()
    expect(validateWatchForm({ market: 'cn', symbol: '600519', targetPrice: '1300', alert: true })).toBeNull()
    expect(validateWatchForm({ market: 'cn', symbol: '600519', targetPrice: '-1', alert: false })).toBe(
      'edit.invalidTarget',
    )
  })
})

describe('mutation request building', () => {
  it('builds the POST body the mutate route expects', () => {
    expect(buildMutationRequest('holding', 'add', { market: 'us', symbol: 'AAPL', quantity: 10, cost: 180 })).toEqual({
      entity: 'holding',
      action: 'add',
      payload: { market: 'us', symbol: 'AAPL', quantity: 10, cost: 180 },
    })
    expect(buildMutationRequest('watchlist', 'remove', { market: 'cn', symbol: '600519' })).toEqual({
      entity: 'watchlist',
      action: 'remove',
      payload: { market: 'cn', symbol: '600519' },
    })
  })

  it('prefers id selectors for row edits (kernel contract: id OR market+symbol)', () => {
    expect(editSelector({ id: 'hld-2', market: 'US', symbol: 'NVDA' })).toEqual({ id: 'hld-2' })
    expect(editSelector({ market: 'US', symbol: 'NVDA' })).toEqual({ market: 'US', symbol: 'NVDA' })
  })
})

describe('instruments payload parsing', () => {
  it('normalizes a valid payload and keeps items lossless', () => {
    const payload = {
      query: 'maotai',
      market: 'cn',
      source: 'akshare catalog (daily sync) + eastmoney suggest fallback',
      items: [
        {
          market: 'CN',
          symbol: '600519',
          name: '贵州茅台',
          currency: 'CNY',
          assetClass: 'stock',
          pinyin: 'maotai',
          held: true,
        },
      ],
    }
    const parsed = parseInstrumentsPayload(payload)
    expect(parsed.ok).toBe(true)
    if (parsed.ok) {
      expect(parsed.value.market).toBe('cn')
      expect(parsed.value.items).toEqual(payload.items)
    }
  })

  it('rejects payloads without items', () => {
    expect(parseInstrumentsPayload({ query: 'x' }).ok).toBe(false)
    expect(parseInstrumentsPayload(null).ok).toBe(false)
  })
})
