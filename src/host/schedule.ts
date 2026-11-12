/**
 * Schedule presets (schedule/*.json) and the human command `debrief-setup`.
 *
 * `debrief-setup` validates the kernel (`job list --json`), then idempotently
 * registers every preset through ctx.schedule.create — a task whose title
 * already exists is skipped. Presets declare explicit `TZID=Asia/Shanghai`
 * RRULEs and target `new_once` (one dedicated session per task, serial
 * delivery, only the latest missed occurrence is delivered).
 */
import { readFileSync, readdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { runCli } from './cli.js'
import type {
  DebriefContext,
  ScheduleCreateRequest,
  ScheduleListResult,
  SchedulePreset,
  ScheduleService,
} from './types.js'
import type { DebriefConfig } from './config.js'

const SCHEDULES_DIR = new URL('../../schedule/', import.meta.url)

export function loadSchedulePresets(): SchedulePreset[] {
  const presets: SchedulePreset[] = []
  let files: string[]
  try {
    files = readdirSync(fileURLToPath(SCHEDULES_DIR))
      .filter((name) => name.endsWith('.json'))
      .sort()
  } catch (error) {
    console.warn('[dsh-debrief] cannot read schedule directory:', error instanceof Error ? error.message : error)
    return presets
  }
  for (const file of files) {
    try {
      const raw = JSON.parse(
        readFileSync(fileURLToPath(new URL(`../../schedule/${file}`, import.meta.url)), 'utf8'),
      ) as Record<string, unknown>
      if (
        typeof raw.title !== 'string' ||
        typeof raw.prompt !== 'string' ||
        typeof raw.rrule !== 'string' ||
        raw.target !== 'new_once'
      ) {
        throw new Error('expected { title, prompt, rrule, target: "new_once" }')
      }
      presets.push({
        title: raw.title,
        prompt: raw.prompt,
        rrule: raw.rrule,
        target: 'new_once',
        ...(typeof raw.order === 'number' ? { order: raw.order } : {}),
      })
    } catch (error) {
      console.warn(`[dsh-debrief] skipping schedule preset ${file}:`, error instanceof Error ? error.message : error)
    }
  }
  return presets.sort((a, b) => (a.order ?? Number.POSITIVE_INFINITY) - (b.order ?? Number.POSITIVE_INFINITY))
}

export function buildCreateRequest(preset: SchedulePreset): ScheduleCreateRequest {
  return {
    title: preset.title,
    prompt: preset.prompt,
    timing: { kind: 'rrule', rrule: preset.rrule },
    target: { kind: 'new_once' },
  }
}

export interface SetupOutcome {
  created: Array<{ title: string; scheduledAt?: string }>
  skipped: string[]
  failed: Array<{ title: string; message: string }>
}

export async function runSetup(
  schedule: ScheduleService,
  config: DebriefConfig,
  presets: SchedulePreset[],
): Promise<SetupOutcome> {
  const kernel = await runCli(config, ['job', 'list'])
  if (!kernel.ok) {
    throw new Error(`kernel check failed: ${kernel.error.code} · ${kernel.error.message}`)
  }
  const page = await schedule.list({ limit: 500 })
  const existing = new Set(page.items.map((item) => item.title))
  const outcome: SetupOutcome = { created: [], skipped: [], failed: [] }
  for (const preset of presets) {
    if (existing.has(preset.title)) {
      outcome.skipped.push(preset.title)
      continue
    }
    try {
      const entry = await schedule.create(buildCreateRequest(preset))
      outcome.created.push({ title: entry.title, scheduledAt: entry.scheduledAt })
      existing.add(entry.title)
    } catch (error) {
      outcome.failed.push({ title: preset.title, message: error instanceof Error ? error.message : String(error) })
    }
  }
  return outcome
}

/**
 * The human command name. The commands registry requires names matching
 * /^[a-z][a-z0-9_-]*$/ (no spaces, lowercase start); a violating name throws
 * during registration and fails the whole plugin activation.
 */
export const SETUP_COMMAND_NAME = 'debrief-setup'

export function registerSetupCommand(
  ctx: DebriefContext,
  config: DebriefConfig,
  presets: SchedulePreset[],
): () => void {
  try {
    return ctx.commands.register({
      name: SETUP_COMMAND_NAME,
      description: '校验 debrief 内核并幂等注册全部定时复盘任务（盘后 ×4 市场 / 新闻 / 周复盘 / 月度 / 记忆压缩）',
      async handler() {
        try {
          const outcome = await runSetup(ctx.schedule, config, presets)
          const lines = ['debrief-setup 完成']
          if (outcome.created.length > 0) {
            lines.push('已注册：')
            for (const item of outcome.created) {
              lines.push(`  · ${item.title}（下次 ${item.scheduledAt ?? '按 RRULE 计算'}）`)
            }
          }
          if (outcome.skipped.length > 0) lines.push(`已存在跳过：${outcome.skipped.join('、')}`)
          if (outcome.failed.length > 0) {
            lines.push('注册失败：')
            for (const item of outcome.failed) lines.push(`  · ${item.title} — ${item.message}`)
          }
          lines.push('内核 CLI：' + config.cliPath + '；任务可在 Schedule 页面查看、暂停或删除。')
          return { kind: 'success', text: lines.join('\n') }
        } catch (error) {
          return {
            kind: 'error',
            text: `debrief-setup 失败：${error instanceof Error ? error.message : String(error)}`,
          }
        }
      },
    })
  } catch (error) {
    // A registration failure must never take the whole plugin down.
    console.warn(
      '[dsh-debrief] `debrief-setup` command registration failed:',
      error instanceof Error ? error.message : error,
    )
    return () => {}
  }
}
