import { describe, expect, it } from 'vitest'
import { DASHBOARD_PATH, registerDashboardRoute, type DashboardRouteDeps } from '../src/host/dashboard'
import { normalizeConfig, type DebriefConfig } from '../src/host/config'
import type { Envelope } from '../src/host/cli'
import type { ConnectionFetchRoute, DebriefContext } from '../src/host/types'

const flush = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0))

function ok(data: Record<string, unknown>): Envelope {
  return { ok: true, schemaVersion: 1, data }
}

function harness(deps: DashboardRouteDeps, config?: Partial<DebriefConfig>) {
  const calls: string[][] = []
  let route: ConnectionFetchRoute | undefined
  const ctx = {
    connection: {
      fetch: {
        register(candidate: ConnectionFetchRoute) {
          route = candidate
          return async () => {}
        },
      },
    },
  } as unknown as DebriefContext
  const resolved = normalizeConfig({ enableDashboardRoute: true, ...config }, {} as NodeJS.ProcessEnv)
  const dispose = registerDashboardRoute(ctx, resolved, {
    runCli: async (args) => {
      calls.push([...args])
      return ok({ kpis: { totalAssets: 1 }, call: calls.length })
    },
    ...deps,
  })
  if (route === undefined) throw new Error('route was not registered')
  const get = (query: string): Promise<Response> => route!.fetch(new Request(`http://local${DASHBOARD_PATH}${query}`))
  return { calls, get, dispose }
}

describe('dashboard route', () => {
  it('rejects an unknown range without touching the kernel', async () => {
    const { calls, get } = harness({})
    const response = await get('?range=7')
    expect(response.status).toBe(400)
    expect(((await response.json()) as { error: { code: string } }).error.code).toBe('DEBRIEF_ARGS')
    expect(calls).toHaveLength(0)
  })

  it('answers from cached prices and never blocks on a live refresh', async () => {
    const { calls, get } = harness({})
    const response = await get('?range=90')
    expect(response.status).toBe(200)
    expect(calls[0]).toEqual(['dashboard', '--range', '90', '--no-refresh'])
    // The background refresh is scheduled, not awaited.
    await flush()
    expect(calls.some((args) => args.includes('--refresh'))).toBe(true)
  })

  it('serves the in-memory payload inside the TTL without a second kernel call', async () => {
    let clock = 1_000
    const { calls, get } = harness({ now: () => clock })
    await get('?range=90')
    await flush()
    const afterFirst = calls.length
    clock += 5_000
    const second = await get('?range=90')
    expect(second.status).toBe(200)
    expect(calls.length).toBe(afterFirst)
  })

  it('collapses concurrent misses into a single kernel call (single flight)', async () => {
    const { calls, get } = harness({})
    const responses = await Promise.all([get('?range=30'), get('?range=30'), get('?range=30')])
    expect(responses.map((response) => response.status)).toEqual([200, 200, 200])
    await flush()
    expect(calls.filter((args) => !args.includes('--refresh'))).toHaveLength(1)
  })

  it('keeps the last good payload when the kernel starts failing', async () => {
    let clock = 1_000
    let fail = false
    const calls: string[][] = []
    const { get } = harness({
      now: () => clock,
      runCli: async (args) => {
        calls.push([...args])
        if (args.includes('--refresh')) return ok({})
        return fail
          ? { ok: false, schemaVersion: 1, error: { code: 'DEBRIEF_INTERNAL', message: 'boom' } }
          : ok({ kpis: { totalAssets: 42 } })
      },
    })
    const first = await get('?range=90')
    expect(((await first.json()) as { data: { kpis: { totalAssets: number } } }).data.kpis.totalAssets).toBe(42)
    fail = true
    clock += 60_000
    const second = await get('?range=90')
    expect(second.status).toBe(200)
    expect(((await second.json()) as { data: { kpis: { totalAssets: number } } }).data.kpis.totalAssets).toBe(42)
  })

  it('inline mode blocks on a live refresh and schedules no background call', async () => {
    const { calls, get } = harness({}, { dashboardRefresh: 'inline' })
    await get('?range=90')
    await flush()
    expect(calls).toEqual([['dashboard', '--range', '90']])
  })

  it('never mode always reads cached prices and never refreshes', async () => {
    const { calls, get } = harness({}, { dashboardRefresh: 'never' })
    await get('?range=365')
    await flush()
    expect(calls).toEqual([['dashboard', '--range', '365', '--no-refresh']])
  })

  it('rate-limits background refreshes to one per interval', async () => {
    let clock = 1_000
    const { calls, get } = harness({ now: () => clock }, { dashboardCacheMs: 0 })
    await get('?range=90')
    await flush()
    clock += 1_000
    await get('?range=90')
    await flush()
    clock += 1_000
    await get('?range=90')
    await flush()
    expect(calls.filter((args) => args.includes('--refresh'))).toHaveLength(1)
  })

  it('caches per range, not across ranges', async () => {
    const { calls, get } = harness({})
    await get('?range=30')
    await get('?range=90')
    await flush()
    expect(calls.filter((args) => !args.includes('--refresh'))).toEqual([
      ['dashboard', '--range', '30', '--no-refresh'],
      ['dashboard', '--range', '90', '--no-refresh'],
    ])
  })

  it('does not register when the route is disabled', () => {
    const ctx = {
      connection: {
        fetch: {
          register() {
            throw new Error('should not register')
          },
        },
      },
    } as unknown as DebriefContext
    const config = normalizeConfig({ enableDashboardRoute: false }, {} as NodeJS.ProcessEnv)
    expect(() => registerDashboardRoute(ctx, config)).not.toThrow()
  })
})
