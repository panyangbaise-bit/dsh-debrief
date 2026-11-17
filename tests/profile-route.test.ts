import { describe, expect, it } from 'vitest'
import { PROFILE_PATH, registerProfileRoute } from '../src/host/profile'
import { normalizeConfig } from '../src/host/config'
import type { Envelope } from '../src/host/cli'
import type { ConnectionFetchRoute, DebriefContext } from '../src/host/types'

const okProfile: Envelope = {
  ok: true,
  schemaVersion: 1,
  data: { version: 1, generated: true, sections: [], markdown: '', evidenceRefs: [], discipline: null },
}

function harness(options: { clock?: () => number } = {}) {
  const calls: Array<{ args: string[]; stdin?: string }> = []
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
  const config = normalizeConfig({}, {} as NodeJS.ProcessEnv)
  let nowValue = 1_000_000
  const now = options.clock ?? (() => nowValue)
  const advance = (ms: number): void => {
    nowValue += ms
  }
  const failures = new Set<number>()
  let sequence = 0
  registerProfileRoute(ctx, config, {
    now,
    runCli: async (args, runOptions) => {
      sequence += 1
      const call = sequence
      calls.push({ args: [...args], stdin: runOptions?.stdin })
      if (failures.has(call)) {
        return { ok: false, schemaVersion: 1, error: { code: 'DEBRIEF_INTERNAL', message: 'boom' } }
      }
      return okProfile
    },
  })
  if (route === undefined) throw new Error('route was not registered')
  const request = (url: string, init: RequestInit): Promise<Response> => route!.fetch(new Request(url, init))
  return { calls, request, advance, failures }
}

describe('profile route', () => {
  it('GET answers from profile get with no extra arguments', async () => {
    const { calls, request } = harness()
    const response = await request(`http://local${PROFILE_PATH}`, { method: 'GET' })
    expect(response.status).toBe(200)
    expect(calls).toEqual([{ args: ['profile', 'get'] }])
    const body = (await response.json()) as Envelope
    expect(body.ok).toBe(true)
  })

  it('collapses concurrent GET misses into one kernel call (single-flight)', async () => {
    const { calls, request } = harness({ clock: () => 1_000_000 })
    await Promise.all([
      request(`http://local${PROFILE_PATH}`, { method: 'GET' }),
      request(`http://local${PROFILE_PATH}`, { method: 'GET' }),
      request(`http://local${PROFILE_PATH}`, { method: 'GET' }),
    ])
    expect(calls).toHaveLength(1)
  })

  it('serves the short cache within the TTL and recomputes after expiry', async () => {
    const { calls, request, advance } = harness()
    await request(`http://local${PROFILE_PATH}`, { method: 'GET' })
    await request(`http://local${PROFILE_PATH}`, { method: 'GET' })
    expect(calls).toHaveLength(1)
    advance(6000)
    await request(`http://local${PROFILE_PATH}`, { method: 'GET' })
    expect(calls).toHaveLength(2)
  })

  it('keeps the last good payload on a kernel failure (stale-while-error)', async () => {
    const { calls, request, failures, advance } = harness()
    await request(`http://local${PROFILE_PATH}`, { method: 'GET' })
    expect(calls).toHaveLength(1)
    advance(6000)
    failures.add(2)
    const response = await request(`http://local${PROFILE_PATH}`, { method: 'GET' })
    expect(response.status).toBe(200) // stale 200 payload
    const body = (await response.json()) as Envelope
    expect(body.ok).toBe(true)
  })

  it('POST validates the payload, writes as --by user, and invalidates the cache', async () => {
    const { calls, request, advance } = harness()
    await request(`http://local${PROFILE_PATH}`, { method: 'GET' })
    const response = await request(`http://local${PROFILE_PATH}`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        sections: [{ key: 'habits', content: '分批建仓。', updatedBy: 'user' }],
        expectedVersion: 1,
      }),
    })
    expect(response.status).toBe(200)
    expect(calls).toHaveLength(2)
    expect(calls[1]).toEqual({
      args: ['profile', 'write', '--by', 'user'],
      stdin: JSON.stringify({ sections: [{ key: 'habits', content: '分批建仓。' }], expectedVersion: 1 }),
    })
    // POST must have dropped the cached GET payload: the next GET recomputes.
    advance(0)
    await request(`http://local${PROFILE_PATH}`, { method: 'GET' })
    expect(calls).toHaveLength(3)
  })

  it('rejects a non-JSON body with 400', async () => {
    const { request } = harness()
    const response = await request(`http://local${PROFILE_PATH}`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: 'not json',
    })
    expect(response.status).toBe(400)
  })

  it('rejects an invalid payload with 400 and never calls the kernel', async () => {
    const { calls, request } = harness()
    const response = await request(`http://local${PROFILE_PATH}`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ sections: [{ key: 'nope', content: 'x' }] }),
    })
    expect(response.status).toBe(400)
    expect(calls).toHaveLength(0)
  })

  it('maps DEBRIEF_CONFLICT to 409', async () => {
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
    const config = normalizeConfig({}, {} as NodeJS.ProcessEnv)
    registerProfileRoute(ctx, config, {
      runCli: async (args) => {
        if (args[0] === 'profile' && args[1] === 'write') {
          return {
            ok: false,
            schemaVersion: 1,
            error: { code: 'DEBRIEF_CONFLICT', message: 'expectedVersion mismatch: current version 5' },
          }
        }
        return okProfile
      },
    })
    const response = await route!.fetch(
      new Request(`http://local${PROFILE_PATH}`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ sections: [{ key: 'risk', content: '保守' }] }),
      }),
    )
    expect(response.status).toBe(409)
  })

  it('maps DEBRIEF_VALIDATION to 400', async () => {
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
    registerProfileRoute(ctx, normalizeConfig({}, {} as NodeJS.ProcessEnv), {
      runCli: async () => ({
        ok: false,
        schemaVersion: 1,
        error: { code: 'DEBRIEF_VALIDATION', message: 'sections key must be one of …' },
      }),
    })
    const response = await route!.fetch(
      new Request(`http://local${PROFILE_PATH}`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ sections: [{ key: 'risk', content: '保守' }] }),
      }),
    )
    expect(response.status).toBe(400)
  })

  it('passes other kernel failures through as 502', async () => {
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
    registerProfileRoute(ctx, normalizeConfig({}, {} as NodeJS.ProcessEnv), {
      runCli: async () => ({ ok: false, schemaVersion: 1, error: { code: 'DEBRIEF_TIMEOUT', message: 'slow' } }),
    })
    const response = await route!.fetch(new Request(`http://local${PROFILE_PATH}`, { method: 'GET' }))
    expect(response.status).toBe(502)
  })
})
