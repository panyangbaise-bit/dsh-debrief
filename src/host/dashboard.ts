/**
 * Read-only Dashboard JSON route for the v1.5 page.
 *
 * Registered through `ctx.connection.fetch` — the authenticated exact-route
 * seam the Web carrier admits against the signed browser cookie. (A raw
 * `ctx.webServer.register` route carries no Peer and no authentication, so it
 * is deliberately NOT used here; deviation from the task's literal wording,
 * resolved by inspecting the current contracts.)
 */
import { runCli } from './cli.js'
import type { ConnectionFetchRoute, DebriefContext } from './types.js'
import type { DebriefConfig } from './config.js'

export const DASHBOARD_PATH = '/api/debrief/dashboard'
const VALID_RANGES = new Set(['30', '90', '200', '365'])

function jsonResponse(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' },
  })
}

export function registerDashboardRoute(ctx: DebriefContext, config: DebriefConfig): () => void {
  if (config.enableDashboardRoute === false) return () => {}
  const connection = ctx.get('connection') as
    { fetch?: { register(route: ConnectionFetchRoute): () => Promise<void> } } | undefined
  if (!connection?.fetch) {
    console.warn('[dsh-debrief] connection service unavailable — dashboard route not registered')
    return () => {}
  }
  const route: ConnectionFetchRoute = {
    path: DASHBOARD_PATH,
    methods: ['GET', 'HEAD'],
    requestBody: 'buffered',
    async fetch(request) {
      const url = new URL(request.url)
      const range = url.searchParams.get('range') ?? '90'
      if (!VALID_RANGES.has(range)) {
        return jsonResponse(
          {
            ok: false,
            schemaVersion: 1,
            error: { code: 'DEBRIEF_ARGS', message: 'range must be one of 30, 90, 200, 365' },
          },
          400,
        )
      }
      const envelope = await runCli(config, ['dashboard', '--range', range])
      return jsonResponse(envelope, envelope.ok ? 200 : 502)
    },
  }
  let unregister: () => Promise<void>
  try {
    unregister = connection.fetch.register(route)
  } catch (error) {
    console.warn('[dsh-debrief] dashboard route registration failed:', error instanceof Error ? error.message : error)
    return () => {}
  }
  return () => void unregister()
}
