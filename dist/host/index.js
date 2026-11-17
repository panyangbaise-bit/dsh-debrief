/**
 * dsh-debrief — Host plugin entry.
 *
 * Registers the read + whitelisted-write tools, the five scheduled skills,
 * the `debrief-setup` human command, and the authenticated dashboard route.
 * All model work belongs to the DSH agent; this plugin only bridges the
 * model-free debrief kernel over its local JSON CLI.
 */
import { normalizeConfig } from './config.js';
import { defineTools } from './tools.js';
import { loadSkills, registerSkills } from './skills.js';
import { loadSchedulePresets, registerSetupCommand } from './schedule.js';
import { registerDashboardRoute } from './dashboard.js';
import { registerEditRoutes, registerMemoryRoute } from './routes.js';
import { registerProfileRoute } from './profile.js';
import { gateWriteTools } from './edits.js';
/**
 * Hard dependencies per the inspected access contracts: a missing service
 * keeps the plugin inactive instead of half-activating (the earlier ctx.get
 * form silently skipped the setup command and the dashboard route on the
 * server profile). Registration calls stay try/catch-guarded as a safety net.
 */
export const inject = ['tools', 'commands', 'schedule', 'connection', 'skills'];
export { normalizeConfig };
export function apply(rawCtx, rawConfig) {
    const ctx = rawCtx;
    const config = normalizeConfig(rawConfig, process.env);
    ctx.effect(() => {
        const disposers = [];
        for (const definition of defineTools(config)) {
            disposers.push(ctx.tools.register(definition));
        }
        return () => disposers.forEach((dispose) => dispose());
    }, 'dsh-debrief: tools');
    ctx.effect(() => registerSkills(ctx, loadSkills()), 'dsh-debrief: skills');
    ctx.effect(() => {
        if (config.enableSetup === false)
            return () => { };
        return registerSetupCommand(ctx, config, loadSchedulePresets());
    }, 'dsh-debrief: setup command');
    ctx.effect(() => registerDashboardRoute(ctx, config), 'dsh-debrief: dashboard route');
    ctx.effect(() => registerEditRoutes(ctx, config), 'dsh-debrief: edit routes');
    ctx.effect(() => registerMemoryRoute(ctx, config), 'dsh-debrief: memory route');
    ctx.effect(() => registerProfileRoute(ctx, config), 'dsh-debrief: profile route');
    // v2 approval gate: agent-initiated portfolio writes ask the user through
    // the DSH approval confirmation flow; without approval support the ask
    // becomes a denial, so a write is refused instead of executed silently.
    ctx.effect(() => {
        try {
            return ctx.on('tools/pre-execute', (exec, next) => {
                return gateWriteTools(exec, next);
            });
        }
        catch (error) {
            console.warn('[dsh-debrief] tools/pre-execute listener registration failed:', error instanceof Error ? error.message : error);
            return () => { };
        }
    }, 'dsh-debrief: approval gate');
    return () => { };
}
