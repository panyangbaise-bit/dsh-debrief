export function normalizeConfig(raw, env) {
    const timeoutMs = Number(raw?.timeoutMs) || 15000;
    return {
        cliPath: raw?.cliPath ?? env.DEBRIEF_CLI_PATH ?? 'debrief',
        timeoutMs: Number.isFinite(timeoutMs) ? Math.max(1000, timeoutMs) : 15000,
        enableSetup: raw?.enableSetup ?? true,
        enableDashboardRoute: raw?.enableDashboardRoute ?? true,
    };
}
