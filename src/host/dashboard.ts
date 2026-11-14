/**
 * Read-only Dashboard JSON route for the v1.5 page.
 *
 * Registered through `ctx.connection.fetch` — the authenticated exact-route
 * seam the Web carrier admits against the signed browser cookie. (A raw
 * `ctx.webServer.register` route carries no Peer and no authentication, so it
 * is deliberately NOT used here; deviation from the task's literal wording,
 * resolved by inspecting the current contracts.)
 *
 * Latency design: every miss used to block the page on a full kernel run
 * (interpreter + imports + live quote fetch + FX). The route now
 *  1. serves a short-lived in-memory payload cache (default 20 s),
 *  2. collapses concurrent misses into one kernel call (single flight),
 *  3. answers from cached prices (`--no-refresh`) and refreshes quotes in the
 *     background, so the next view is fresh and nobody waits for the network,
 *  4. keeps the last good payload when the kernel fails (stale-while-error).
 */
import { runCli, type Envelope } from './cli.js'
import type { ConnectionFetchRoute, DebriefContext } from './types.js'
import type { DebriefConfig } from './config.js'

export const DASHBOARD_PATH = '/api/debrief/dashboard'
const VALID_RANGES = new Set(['30', '90', '200', '365'])
const MIN_REFRESH_GAP_MS = 60_000

function jsonResponse(body: unknown, status: number): Response {
  return jsonResponseText(JSON.stringify(body), status)
}

function jsonResponseText(body: string, status: number): Response {
  return new Response(body, {
    status,
    headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' },
  })
}

export interface DashboardRouteDeps {
  /** Injectable kernel bridge (tests); defaults to the real subprocess call. */
  runCli?: (args: readonly string[], options?: { signal?: AbortSignal }) => Promise<Envelope>
  now?: () => number
}

interface CachedPayload {
  at: number
  body: string
  status: number
}

export function registerDashboardRoute(
  ctx: DebriefContext,
  config: DebriefConfig,
  deps: DashboardRouteDeps = {},
): () => void {
  if (config.enableDashboardRoute === false) return () => {}
  const run = deps.runCli ?? ((args, options) => runCli(config, args, options))
  const now = deps.now ?? Date.now
  const cacheMs = config.dashboardCacheMs ?? 20_000
  const mode = config.dashboardRefresh ?? 'background'
  const cache = new Map<string, CachedPayload>()
  const inflight = new Map<string, Promise<CachedPayload>>()
  let lastRefreshAt: number | undefined
  let refreshing = false

  /** Fire-and-forget quote refresh so the *next* view carries fresh prices. */
  const refreshInBackground = (range: string): void => {
    if (mode !== 'background' || refreshing) return
    if (lastRefreshAt !== undefined && now() - lastRefreshAt < Math.max(MIN_REFRESH_GAP_MS, cacheMs)) return
    refreshing = true
    lastRefreshAt = now()
    void run(['dashboard', '--range', range, '--refresh'])
      .catch(() => undefined)
      .finally(() => {
        refreshing = false
      })
  }

  const build = async (range: string): Promise<CachedPayload> => {
    const args = ['dashboard', '--range', range]
    if (mode !== 'inline') args.push('--no-refresh')
    const envelope = await run(args)
    if (!envelope.ok) return { at: now(), body: JSON.stringify(envelope), status: 502 }
    refreshInBackground(range)
    return { at: now(), body: JSON.stringify(envelope), status: 200 }
  }

  const payloadFor = async (range: string): Promise<CachedPayload> => {
    const cached = cache.get(range)
    if (cached !== undefined && cacheMs > 0 && now() - cached.at < cacheMs) return cached
    let pending = inflight.get(range)
    if (pending === undefined) {
      pending = build(range).finally(() => inflight.delete(range))
      inflight.set(range, pending)
    }
    const fresh = await pending
    if (fresh.status === 200) {
      cache.set(range, fresh)
      return fresh
    }
    // Kernel failure: keep showing the last good payload rather than an error
    // card. A cold start with nothing cached still surfaces the envelope.
    return cached ?? fresh
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
      const payload = await payloadFor(range)
      return jsonResponseText(payload.body, payload.status)
    },
  }
  let unregister: () => Promise<void>
  try {
    unregister = ctx.connection.fetch.register(route)
  } catch (error) {
    console.warn('[dsh-debrief] dashboard route registration failed:', error instanceof Error ? error.message : error)
    return () => {}
  }
  return () => void unregister()
}
