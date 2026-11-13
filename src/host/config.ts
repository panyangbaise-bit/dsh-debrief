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
  /** Optional Telegram bot credentials for the notify bridge and news pushes. */
  telegram?: { botToken?: string; chatId?: string }
}

export function normalizeConfig(raw: Partial<DebriefConfig> | undefined, env: NodeJS.ProcessEnv): DebriefConfig {
  const timeoutMs = Number(raw?.timeoutMs) || 15000
  const kernelMode =
    raw?.kernelMode === 'external' || raw?.kernelMode === 'managed'
      ? raw.kernelMode
      : raw?.kernelMode === 'auto'
        ? 'auto'
        : 'auto'
  return {
    cliPath: raw?.cliPath ?? env.DEBRIEF_CLI_PATH ?? undefined,
    kernelMode,
    dataDir: raw?.dataDir ?? env.DEBRIEF_DATA_DIR ?? undefined,
    withCollectors: raw?.withCollectors === true,
    timeoutMs: Number.isFinite(timeoutMs) ? Math.max(1000, timeoutMs) : 15000,
    enableSetup: raw?.enableSetup ?? true,
    enableDashboardRoute: raw?.enableDashboardRoute ?? true,
    telegram:
      raw?.telegram && (typeof raw.telegram.botToken === 'string' || typeof raw.telegram.chatId === 'string')
        ? { botToken: raw.telegram.botToken, chatId: raw.telegram.chatId }
        : undefined,
  }
}
