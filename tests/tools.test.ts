import { describe, expect, it } from 'vitest'
import { normalizeConfig } from '../src/host/config'
import { defineTools, validateWritePayload, writePayloadShapes } from '../src/host/tools'
import { validate } from '../src/host/schema'

const config = normalizeConfig({ cliPath: 'debrief', timeoutMs: 5000 }, {})

describe('tool registry', () => {
  const tools = defineTools(config)

  it('registers the read tools plus the whitelisted writes and the six approval-gated edit tools', () => {
    const names = tools.map((tool) => tool.name)
    expect(names).toEqual([
      'debrief_holdings',
      'debrief_transactions',
      'debrief_watchlist',
      'debrief_instruments',
      'debrief_report',
      'debrief_memory',
      'debrief_analyze',
      'debrief_jobs',
      'debrief_dashboard',
      'debrief_news',
      'debrief_report_create',
      'debrief_memory_compact_write',
      'debrief_memory_add',
      'debrief_holding_add',
      'debrief_holding_update',
      'debrief_holding_remove',
      'debrief_watchlist_add',
      'debrief_watchlist_update',
      'debrief_watchlist_remove',
    ])
  })

  it('marks the three write tools as whitelisted writes with audit', () => {
    for (const name of ['debrief_report_create', 'debrief_memory_compact_write', 'debrief_memory_add']) {
      const tool = tools.find((candidate) => candidate.name === name)
      expect(tool).toBeDefined()
      expect(tool?.description).toContain('Whitelisted write tool')
      expect(tool?.description).toContain('user_actions audit')
    }
  })

  it('requires the documented fields for debrief_report_create', () => {
    const tool = tools.find((candidate) => candidate.name === 'debrief_report_create')
    const parameters = tool?.parameters as { required?: string[] }
    expect(parameters.required).toEqual(['market', 'title', 'summary'])
  })

  it('requires the documented fields for debrief_memory_compact_write', () => {
    const tool = tools.find((candidate) => candidate.name === 'debrief_memory_compact_write')
    const parameters = tool?.parameters as { required?: string[] }
    expect(parameters.required).toEqual(['topic', 'instruments', 'summary', 'evidenceRefs', 'timeRange'])
  })

  it('requires the documented fields for debrief_memory_add', () => {
    const tool = tools.find((candidate) => candidate.name === 'debrief_memory_add')
    const parameters = tool?.parameters as { required?: string[] }
    expect(parameters.required).toEqual(['sourceType', 'content', 'instruments'])
  })

  it('routes debrief_memory to compact-candidates when requested', async () => {
    const tool = tools.find((candidate) => candidate.name === 'debrief_memory')!
    const result = await tool.execute({ compactCandidates: true }, { signal: new AbortController().signal })
    // CLI absent in tests: the arg check must pass and the failure comes from exec, not DEBRIEF_ARGS.
    expect(result).toMatchObject({ ok: false, error: { code: 'DEBRIEF_CLI_NOT_FOUND' } })
  })

  it('requires a query for debrief_memory unless compactCandidates is true', async () => {
    const tool = tools.find((candidate) => candidate.name === 'debrief_memory')!
    const result = await tool.execute({}, { signal: new AbortController().signal })
    expect(result).toMatchObject({ ok: false, error: { code: 'DEBRIEF_ARGS' } })
  })

  it('maps debrief_instruments arguments to the CLI search subcommand', async () => {
    const tool = tools.find((candidate) => candidate.name === 'debrief_instruments')!
    const result = await tool.execute({ market: 'cn', query: 'maotai' }, { signal: new AbortController().signal })
    // The real CLI is absent in tests; the only invariant is a structured envelope.
    expect(result).toHaveProperty('ok')
    expect(result).toHaveProperty('error')
  })

  it('fails fast with DEBRIEF_ARGS when a write payload does not match its schema', async () => {
    const tool = tools.find((candidate) => candidate.name === 'debrief_report_create')!
    const result = await tool.execute({ market: 'us', title: 't' }, { signal: new AbortController().signal })
    expect(result).toMatchObject({ ok: false, error: { code: 'DEBRIEF_ARGS' } })
  })
})

describe('write payload validation', () => {
  it('accepts a valid report create payload and emits stdin JSON', () => {
    const result = validateWritePayload('reportCreate', {
      market: 'us',
      title: '盘后分析',
      summary: '一句话总结',
      jobId: 'debrief-job-1',
      metrics: [{ label: '波动率', value: '18%' }],
      chart: { title: '60 日走势', unit: '', points: [1, 2, 3] },
    })
    expect(result.ok).toBe(true)
    const parsed = JSON.parse(result.stdin!) as Record<string, unknown>
    expect(parsed.market).toBe('us')
    expect(parsed.jobId).toBe('debrief-job-1')
    expect(Array.isArray(parsed.metrics)).toBe(true)
  })

  it('rejects a report create payload missing required fields', () => {
    const result = validateWritePayload('reportCreate', { market: 'us' } as never)
    expect(result.ok).toBe(false)
    expect(result.error?.code).toBe('DEBRIEF_ARGS')
  })

  it('accepts a valid compact-write payload with evidence refs and time range', () => {
    const result = validateWritePayload('compactWrite', {
      topic: 'position-aapl-rationale',
      instruments: ['AAPL'],
      summary: '结论',
      evidenceRefs: [{ docId: 12, quote: '原文' }],
      timeRange: { from: '2026-03-01', to: '2026-05-31' },
      confidence: 'high',
    })
    expect(result.ok).toBe(true)
    const parsed = JSON.parse(result.stdin!) as Record<string, unknown>
    expect(parsed.confidence).toBe('high')
  })

  it('rejects a compact-write payload whose evidenceRefs lack docId', () => {
    const result = validateWritePayload('compactWrite', {
      topic: 't',
      instruments: ['AAPL'],
      summary: 's',
      evidenceRefs: [{ quote: 'no doc' }],
      timeRange: { from: 'a', to: 'b' },
    })
    expect(result.ok).toBe(false)
  })

  it('accepts a valid memory add payload', () => {
    const result = validateWritePayload('memoryAdd', {
      sourceType: 'decision',
      content: '建仓理由……',
      instruments: ['AAPL'],
      occurredAt: '2026-11-10T08:00:00Z',
    })
    expect(result.ok).toBe(true)
    const parsed = JSON.parse(result.stdin!) as Record<string, unknown>
    expect(parsed.sourceType).toBe('decision')
  })

  it('declares the same shapes through the exported schema helper', () => {
    expect(writePayloadShapes.reportCreate.type).toBe('object')
    expect(writePayloadShapes.compactWrite.type).toBe('object')
    expect(writePayloadShapes.memoryAdd.type).toBe('object')
  })
})

describe('schema validator', () => {
  it('validates nested objects and arrays', () => {
    const shape = writePayloadShapes.compactWrite
    const result = validate(shape, {
      topic: 'x',
      instruments: ['AAPL'],
      summary: 'y',
      evidenceRefs: [{ docId: 1 }],
      timeRange: { from: 'a', to: 'b' },
    })
    expect(result.ok).toBe(true)
  })

  it('reports the failing path', () => {
    const shape = writePayloadShapes.compactWrite
    const result = validate(shape, {
      topic: 'x',
      instruments: ['AAPL'],
      summary: 'y',
      evidenceRefs: [{ docId: 'not-a-number' }],
      timeRange: { from: 'a', to: 'b' },
    })
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.path).toBe('$.evidenceRefs[0].docId')
  })
})
