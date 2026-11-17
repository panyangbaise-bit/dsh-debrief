/**
 * Plugin configuration, normalized once at activation.
 */
export interface DebriefConfig {
  /** Absolute path or PATH name of the debrief kernel CLI (external mode). */
  cliPath?: string
  /**
   * Kernel resolution mode.
   * - `external`: use `cliPath` as-is (server deployment against a managed venv).
   * - `managed`: bootstrap an isolated venv from the bundled kernel wheels.
   * - `auto` (default): explicit `cliPath`/`DEBRIEF_CLI_PATH` wins, else managed.
   */
  kernelMode?: 'auto' | 'external' | 'managed'
  /** Runtime data directory for the managed venv (default `~/.dsh/debrief-runtime`). */
  dataDir?: string
  /** Opt-in: also install the networked collectors extra during bootstrap. */
  withCollectors?: boolean
  /** Per-call timeout in milliseconds. */
  timeoutMs: number
  /** Whether to register the `debrief-setup` human command (default true). */
  enableSetup?: boolean
  /** Whether to register the read-only portfolio JSON route (default true). */
  enableDashboardRoute?: boolean
  /**
   * How long the dashboard route may serve a cached payload before recomputing
   * (default 20000 ms; 0 disables the cache).
   */
  dashboardCacheMs?: number
  /**
   * How the dashboard refreshes quotes.
   * - `background` (default): answer from cached prices, refresh in the
   *   background so the next view is fresh.
   * - `inline`: block the response on a live refresh (pre-0.3 behaviour).
   * - `never`: always read cached prices (the scheduled worker owns freshness).
   */
  dashboardRefresh?: 'background' | 'inline' | 'never'
  /**
   * How long the profile route may serve a cached payload before recomputing
   * (default 5000 ms; 0 disables the cache). Single-flight and
   * stale-while-error stay active either way.
   */
  profileCacheMs?: number
  /**
   * Writable directory for Python bytecode caches (PYTHONPYCACHEPREFIX).
   * Defaults to `<dataDir>/pycache`; an empty string disables the injection.
   */
  pycachePrefix?: string
  /** Optional Telegram bot credentials for the notify bridge and news pushes. */
  telegram?: { botToken?: string; chatId?: string }
}

const DEFAULT_DASHBOARD_CACHE_MS = 20_000
const DEFAULT_PROFILE_CACHE_MS = 5000

export function normalizeConfig(raw: Partial<DebriefConfig> | undefined, env: NodeJS.ProcessEnv): DebriefConfig {
  const timeoutMs = Number(raw?.timeoutMs) || 15000
  const kernelMode =
    raw?.kernelMode === 'external' || raw?.kernelMode === 'managed'
      ? raw.kernelMode
      : raw?.kernelMode === 'auto'
        ? 'auto'
        : 'auto'
  const cacheMs = Number(raw?.dashboardCacheMs)
  const profileCacheMs = Number(raw?.profileCacheMs)
  const dashboardRefresh =
    raw?.dashboardRefresh === 'inline' || raw?.dashboardRefresh === 'never' || raw?.dashboardRefresh === 'background'
      ? raw.dashboardRefresh
      : 'background'
  return {
    cliPath: raw?.cliPath ?? env.DEBRIEF_CLI_PATH ?? undefined,
    kernelMode,
    dataDir: raw?.dataDir ?? env.DEBRIEF_DATA_DIR ?? undefined,
    withCollectors: raw?.withCollectors === true,
    timeoutMs: Number.isFinite(timeoutMs) ? Math.max(1000, timeoutMs) : 15000,
    enableSetup: raw?.enableSetup ?? true,
    enableDashboardRoute: raw?.enableDashboardRoute ?? true,
    dashboardCacheMs:
      raw?.dashboardCacheMs === undefined
        ? DEFAULT_DASHBOARD_CACHE_MS
        : Number.isFinite(cacheMs)
          ? Math.max(0, cacheMs)
          : DEFAULT_DASHBOARD_CACHE_MS,
    profileCacheMs:
      raw?.profileCacheMs === undefined
        ? DEFAULT_PROFILE_CACHE_MS
        : Number.isFinite(profileCacheMs)
          ? Math.max(0, profileCacheMs)
          : DEFAULT_PROFILE_CACHE_MS,
    dashboardRefresh,
    pycachePrefix: raw?.pycachePrefix ?? env.DEBRIEF_PYCACHE_PREFIX ?? undefined,
    telegram:
      raw?.telegram && (typeof raw.telegram.botToken === 'string' || typeof raw.telegram.chatId === 'string')
        ? { botToken: raw.telegram.botToken, chatId: raw.telegram.chatId }
        : undefined,
  }
}
