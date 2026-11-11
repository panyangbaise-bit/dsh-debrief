/**
 * Plugin configuration, normalized once at activation.
 */
export interface DebriefConfig {
  /** Absolute path or PATH name of the debrief kernel CLI. */
  cliPath: string
  /** Per-call timeout in milliseconds. */
  timeoutMs: number
  /** Whether to register the `debrief-setup` human command (default true). */
  enableSetup?: boolean
  /** Whether to register the read-only dashboard JSON route (default true). */
  enableDashboardRoute?: boolean
}

export function normalizeConfig(raw: Partial<DebriefConfig> | undefined, env: NodeJS.ProcessEnv): DebriefConfig {
  const timeoutMs = Number(raw?.timeoutMs) || 15000
  return {
    cliPath: raw?.cliPath ?? env.DEBRIEF_CLI_PATH ?? 'debrief',
    timeoutMs: Number.isFinite(timeoutMs) ? Math.max(1000, timeoutMs) : 15000,
    enableSetup: raw?.enableSetup ?? true,
    enableDashboardRoute: raw?.enableDashboardRoute ?? true,
  }
}
