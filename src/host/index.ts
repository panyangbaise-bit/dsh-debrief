/**
 * dsh-debrief — Host plugin entry.
 *
 * Registers the read + whitelisted-write tools, the five scheduled skills,
 * the `debrief-setup` human command, and the authenticated dashboard route.
 * All model work belongs to the DSH agent; this plugin only bridges the
 * model-free debrief kernel over its local JSON CLI.
 */
import { normalizeConfig } from './config.js'
import { defineTools } from './tools.js'
import { loadSkills, registerSkills } from './skills.js'
import { loadSchedulePresets, registerSetupCommand } from './schedule.js'
import { registerDashboardRoute } from './dashboard.js'
import type { DebriefContext, ToolDefinition } from './types.js'
import type { DebriefConfig } from './config.js'

export const inject = ['tools']

export { normalizeConfig }
export type { DebriefConfig } from './config.js'

export function apply(rawCtx: DebriefContext, rawConfig?: Partial<DebriefConfig>): () => void {
  const ctx = rawCtx
  const config = normalizeConfig(rawConfig, process.env)

  ctx.effect(() => {
    const disposers: Array<() => void> = []
    for (const definition of defineTools(config)) {
      disposers.push(ctx.tools.register(definition as ToolDefinition))
    }
    return () => disposers.forEach((dispose) => dispose())
  }, 'dsh-debrief: tools')

  ctx.effect(() => registerSkills(ctx, loadSkills()), 'dsh-debrief: skills')

  ctx.effect(() => {
    if (config.enableSetup === false) return () => {}
    return registerSetupCommand(ctx, config, loadSchedulePresets())
  }, 'dsh-debrief: setup command')

  ctx.effect(() => registerDashboardRoute(ctx, config), 'dsh-debrief: dashboard route')

  return () => {}
}
