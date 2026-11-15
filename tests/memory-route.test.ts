import { describe, expect, it } from 'vitest'
import { MEMORY_PATH, registerMemoryRoute } from '../src/host/routes'
import { normalizeConfig } from '../src/host/config'
import type { Envelope } from '../src/host/cli'
import type { ConnectionFetchRoute, DebriefContext } from '../src/host/types'

const ok: Envelope = { ok: true, schemaVersion: 1, data: { stub: true } }

function harness() {
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
  const config = normalizeConfig({ enableDashboardRoute: true }, {} as NodeJS.ProcessEnv)
  registerMemoryRoute(ctx, config, {
    runCli: async (args, options) => {
      calls.push({ args: [...args], stdin: options?.stdin })
      return ok
    },
  })
  if (route === undefined) throw new Error('route was not registered')
  const request = (url: string, init: RequestInit): Promise<Response> => route!.fetch(new Request(url, init))
  return { calls, request }
}

describe('memory route', () => {
  it('lists active topics by default and retired with ?retired=1', async () => {
    const { calls, request } = harness()
    await request(`http://local${MEMORY_PATH}`, { method: 'GET' })
    await request(`http://local${MEMORY_PATH}?retired=1`, { method: 'GET' })
    expect(calls[0].args).toEqual(['memory', 'list', '--limit', '200'])
    expect(calls[1].args).toEqual(['memory', 'list', '--all', '--limit', '200'])
  })

  it('maps actions to kernel commands with the right stdin', async () => {
    const { calls, request } = harness()
    const post = (body: Record<string, unknown>): Promise<Response> =>
      request(`http://local${MEMORY_PATH}`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
      })
    await post({ action: 'retire', topic: 'ops-x' })
    await post({ action: 'restore', topic: 't' })
    await post({ action: 'update', topic: 't', summary: 's', confidence: 'high' })
    await post({ action: 'remove', topic: 't' })
    expect(calls[0].args).toEqual(['memory', 'compact-write'])
    expect(calls[0].stdin).toBe('{"topic":"ops-x","retire":true}')
    expect(calls[1].args).toEqual(['memory', 'update'])
    expect(calls[1].stdin).toBe('{"topic":"t","restore":true}')
    expect(calls[2].stdin).toBe('{"topic":"t","summary":"s","confidence":"high"}')
    expect(calls[3].args).toEqual(['memory', 'remove'])
  })

  it('rejects an unknown action without touching the kernel', async () => {
    const { calls, request } = harness()
    const response = await request(`http://local${MEMORY_PATH}`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ action: 'boom', topic: 't' }),
    })
    expect(response.status).toBe(400)
    expect(calls).toHaveLength(0)
  })

  it('requires a topic', async () => {
    const { calls, request } = harness()
    const response = await request(`http://local${MEMORY_PATH}`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ action: 'retire' }),
    })
    expect(response.status).toBe(400)
    expect(calls).toHaveLength(0)
  })
})
