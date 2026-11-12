import { afterAll, beforeEach, describe, expect, it } from 'vitest'
import { rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { normalizeEnvelope, runCli } from '../src/host/cli'
import { normalizeConfig } from '../src/host/config'

const MOCK = fileURLToPath(new URL('../mock/debrief.js', import.meta.url))
const MOCK_STATE = join(tmpdir(), 'debrief-mock-cli-test.json')
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

describe('envelope normalization', () => {
  it('normalizes an ok envelope', () => {
    const env = normalizeEnvelope({ ok: true, schemaVersion: 1, data: { a: 1 } })
    expect(env).toEqual({ ok: true, schemaVersion: 1, data: { a: 1 } })
  })

  it('normalizes an error envelope with code and message', () => {
    const env = normalizeEnvelope({ ok: false, schemaVersion: 1, error: { code: 'E_X', message: 'boom' } })
    expect(env).toEqual({ ok: false, schemaVersion: 1, error: { code: 'E_X', message: 'boom' } })
  })

  it('rejects an unexpected payload', () => {
    const env = normalizeEnvelope({ hello: 'world' })
    expect(env).toEqual({
      ok: false,
      schemaVersion: 1,
      error: { code: 'DEBRIEF_BAD_PAYLOAD', message: expect.any(String) },
    })
  })
})

describe('runCli against the mock kernel', () => {
  it('runs holdings and parses the ok envelope', async () => {
    const env = await cli(['holdings'])
    expect(env.ok).toBe(true)
    if (env.ok) {
      const data = env.data as Record<string, unknown>
      expect(data.totalMarketValue).toBe(1234567)
      expect(Array.isArray(data.positions)).toBe(true)
    }
  })

  it('passes flags through to the CLI', async () => {
    const env = await cli(['transactions', '--ticker', 'AAPL'])
    expect(env.ok).toBe(true)
    if (env.ok) {
      const data = env.data as Record<string, unknown>
      const items = data.items as Array<Record<string, unknown>>
      expect(items.every((item) => item.symbol === 'AAPL')).toBe(true)
    }
  })

  it('writes the report create payload on stdin and returns { id, status }', async () => {
    const env = await cli(
      ['report', 'create'],
      JSON.stringify({ market: 'us', title: '盘后分析', summary: '一句话总结', jobId: 'debrief-job-2048' }),
    )
    expect(env.ok).toBe(true)
    if (env.ok) {
      const data = env.data as Record<string, unknown>
      expect(typeof data.id).toBe('string')
      expect(data.status).toBe('created')
    }
  })

  it('rejects a report create without stdin payload', async () => {
    const env = await cli(['report', 'create'], '')
    expect(env.ok).toBe(false)
    if (!env.ok) expect(env.error.code).toBe('DEBRIEF_ARGS')
  })

  it('compacts memory with the stdin payload and returns { id, version }', async () => {
    const payload = {
      topic: 'position-aapl-rationale',
      instruments: ['AAPL'],
      summary: '结论',
      evidenceRefs: [{ docId: 12, quote: '原文' }],
      timeRange: { from: '2026-03-01', to: '2026-05-31' },
      confidence: 'high',
    }
    const env = await cli(['memory', 'compact-write'], JSON.stringify(payload))
    expect(env.ok).toBe(true)
    if (env.ok) {
      const data = env.data as Record<string, unknown>
      expect(typeof data.id).toBe('string')
      expect(data.version).toBe(1)
    }
  })

  it('adds a memory snapshot and returns { docId }', async () => {
    const env = await cli(
      ['memory', 'add'],
      JSON.stringify({ sourceType: 'decision', content: '建仓理由', instruments: ['AAPL'] }),
    )
    expect(env.ok).toBe(true)
    if (env.ok) {
      const data = env.data as Record<string, unknown>
      expect(typeof data.docId).toBe('number')
    }
  })

  it('runs the job lifecycle: start → status → finish', async () => {
    const started = await cli(['job', 'start'], JSON.stringify({ kind: '盘后分析 · 美股' }))
    expect(started.ok).toBe(true)
    if (!started.ok) return
    const { id } = started.data as Record<string, unknown>
    const status = await cli(['job', 'status', '--id', String(id)])
    expect(status.ok).toBe(true)
    if (status.ok) expect((status.data as Record<string, unknown>).status).toBe('running')
    const finished = await cli(['job', 'finish'], JSON.stringify({ id, status: 'succeeded', durationSec: 42 }))
    expect(finished.ok).toBe(true)
    if (finished.ok) expect((finished.data as Record<string, unknown>).status).toBe('succeeded')
  })

  it('returns a structured error for an unknown command', async () => {
    const env = await cli(['nope'])
    expect(env.ok).toBe(false)
    if (!env.ok) expect(env.error.code).toBe('DEBRIEF_USAGE')
  })

  it('returns DEBRIEF_PARSE when stdout is not JSON', async () => {
    const env = await runCli({ cliPath: process.execPath, timeoutMs: 10000 }, [
      '-e',
      'process.stdout.write("not json")',
    ])
    expect(env.ok).toBe(false)
    if (!env.ok) expect(env.error.code).toBe('DEBRIEF_PARSE')
  })

  it('returns DEBRIEF_CLI_NOT_FOUND for a missing executable', async () => {
    const env = await runCli({ cliPath: '/definitely/not/a/real/debrief-cli', timeoutMs: 5000 }, ['holdings'])
    expect(env.ok).toBe(false)
    if (!env.ok) expect(env.error.code).toBe('DEBRIEF_CLI_NOT_FOUND')
  })

  it('returns DEBRIEF_ABORTED for a pre-aborted signal', async () => {
    const controller = new AbortController()
    controller.abort()
    const env = await runCli(config, ['holdings'], { signal: controller.signal })
    expect(env.ok).toBe(false)
    if (!env.ok) expect(env.error.code).toBe('DEBRIEF_ABORTED')
  })

  it('honours the dashboard range flag', async () => {
    const env = await cli(['dashboard', '--range', '200'])
    expect(env.ok).toBe(true)
    if (env.ok) {
      const data = env.data as Record<string, unknown>
      const series = data.series as Record<string, unknown>
      expect(series.range).toBe(200)
    }
  })
})
