const DEFAULT_DASHBOARD_CACHE_MS = 20_000;
export function normalizeConfig(raw, env) {
    const timeoutMs = Number(raw?.timeoutMs) || 15000;
    const kernelMode = raw?.kernelMode === 'external' || raw?.kernelMode === 'managed'
        ? raw.kernelMode
        : raw?.kernelMode === 'auto'
            ? 'auto'
            : 'auto';
    const cacheMs = Number(raw?.dashboardCacheMs);
    const dashboardRefresh = raw?.dashboardRefresh === 'inline' || raw?.dashboardRefresh === 'never' || raw?.dashboardRefresh === 'background'
        ? raw.dashboardRefresh
        : 'background';
    return {
        cliPath: raw?.cliPath ?? env.DEBRIEF_CLI_PATH ?? undefined,
        kernelMode,
        dataDir: raw?.dataDir ?? env.DEBRIEF_DATA_DIR ?? undefined,
        withCollectors: raw?.withCollectors === true,
        timeoutMs: Number.isFinite(timeoutMs) ? Math.max(1000, timeoutMs) : 15000,
        enableSetup: raw?.enableSetup ?? true,
        enableDashboardRoute: raw?.enableDashboardRoute ?? true,
        dashboardCacheMs: raw?.dashboardCacheMs === undefined
            ? DEFAULT_DASHBOARD_CACHE_MS
            : Number.isFinite(cacheMs)
                ? Math.max(0, cacheMs)
                : DEFAULT_DASHBOARD_CACHE_MS,
        dashboardRefresh,
        pycachePrefix: raw?.pycachePrefix ?? env.DEBRIEF_PYCACHE_PREFIX ?? undefined,
        telegram: raw?.telegram && (typeof raw.telegram.botToken === 'string' || typeof raw.telegram.chatId === 'string')
            ? { botToken: raw.telegram.botToken, chatId: raw.telegram.chatId }
            : undefined,
    };
}
