import { describe, expect, it } from 'vitest'
import { buildCreateRequest, loadSchedulePresets, runSetup, SETUP_COMMAND_NAME } from '../src/host/schedule'
import { normalizeConfig } from '../src/host/config'
import { fileURLToPath } from 'node:url'

const MOCK = fileURLToPath(new URL('../mock/debrief.js', import.meta.url))
const config = normalizeConfig({ cliPath: process.execPath, timeoutMs: 10000 }, {})

describe('setup command name', () => {
  it('matches the commands registry constraint /^[a-z][a-z0-9_-]*$/ (no spaces)', () => {
    expect(SETUP_COMMAND_NAME).toBe('debrief-setup')
    expect(SETUP_COMMAND_NAME).toMatch(/^[a-z][a-z0-9_-]*$/)
  })
})

describe('schedule presets', () => {
  const presets = loadSchedulePresets()

  it('loads all eight presets', () => {
    expect(presets.map((preset) => preset.title)).toEqual([
      '盘后分析 · 美股',
      '盘后分析 · A股',
      '盘后分析 · 港股',
      '盘后分析 · 加密',
      '每小时新闻摘要',
      '周复盘',
      '月度复盘',
      '每日记忆压缩',
    ])
  })

  it('declares TZID=Asia/Shanghai in every RRULE', () => {
    for (const preset of presets) {
      expect(preset.rrule).toContain('TZID=Asia/Shanghai')
      expect(preset.rrule.split('\n')[0]).toMatch(/^DTSTART;TZID=Asia\/Shanghai:\d{8}T\d{6}$/)
      expect(preset.rrule.split('\n')[1]).toMatch(/^RRULE:/)
    }
  })

  it('targets new_once and carries a prompt', () => {
    for (const preset of presets) {
      expect(preset.target).toBe('new_once')
      expect(preset.prompt.length).toBeGreaterThan(20)
    }
  })

  it('uses weekday rules for the equity markets and daily/hourly elsewhere', () => {
    const rrule = (title: string) => presets.find((preset) => preset.title === title)?.rrule ?? ''
    expect(rrule('盘后分析 · 美股')).toContain('FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR')
    expect(rrule('盘后分析 · A股')).toContain('FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR')
    expect(rrule('盘后分析 · 港股')).toContain('FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR')
    expect(rrule('盘后分析 · 加密')).toContain('FREQ=DAILY')
    expect(rrule('每小时新闻摘要')).toContain('FREQ=HOURLY')
    expect(rrule('周复盘')).toContain('FREQ=WEEKLY;BYDAY=SA')
    expect(rrule('月度复盘')).toContain('FREQ=MONTHLY;BYMONTHDAY=1')
    expect(rrule('每日记忆压缩')).toContain('FREQ=DAILY')
  })

  it('builds a ScheduleCreateRequest with rrule timing and new_once target', () => {
    const request = buildCreateRequest(presets[0]!)
    expect(request).toEqual({
      title: '盘后分析 · 美股',
      prompt: presets[0]!.prompt,
      timing: { kind: 'rrule', rrule: presets[0]!.rrule },
      target: { kind: 'new_once' },
    })
  })
})

describe('runSetup (idempotent registration)', () => {
  const basePresets = [
    {
      title: '任务 A',
      prompt: 'p',
      rrule: 'DTSTART;TZID=Asia/Shanghai:20261109T090000\nRRULE:FREQ=DAILY',
      target: 'new_once' as const,
      order: 1,
    },
    {
      title: '任务 B',
      prompt: 'p',
      rrule: 'DTSTART;TZID=Asia/Shanghai:20261109T090000\nRRULE:FREQ=DAILY',
      target: 'new_once' as const,
      order: 2,
    },
  ]

  const service = (existing: string[], scheduleAt: string) => ({
    async list() {
      return { items: existing.map((title) => ({ id: `id-${title}`, title })) }
    },
    async create(request: { title: string }) {
      return { id: `id-${request.title}`, title: request.title, scheduledAt: scheduleAt }
    },
  })

  it('creates missing tasks and skips existing titles', async () => {
    const outcome = await runSetup(
      service(['任务 A'], '2026-11-12T09:00:00+08:00'),
      { ...config, cliPath: MOCK },
      basePresets,
    )
    expect(outcome.created.map((item) => item.title)).toEqual(['任务 B'])
    expect(outcome.created[0]?.scheduledAt).toBe('2026-11-12T09:00:00+08:00')
    expect(outcome.skipped).toEqual(['任务 A'])
    expect(outcome.failed).toEqual([])
  })

  it('reports per-task failures instead of throwing', async () => {
    const flaky = {
      async list() {
        return { items: [] }
      },
      async create(request: { title: string }) {
        if (request.title === '任务 B') throw new Error('boom')
        return { id: `id-${request.title}`, title: request.title }
      },
    }
    const outcome = await runSetup(flaky, { ...config, cliPath: MOCK }, basePresets)
    expect(outcome.created.map((item) => item.title)).toEqual(['任务 A'])
    expect(outcome.failed.map((item) => item.title)).toEqual(['任务 B'])
  })

  it('throws when the kernel check fails', async () => {
    const badConfig = { ...config, cliPath: '/definitely/not/a/real/debrief-cli', timeoutMs: 5000 }
    await expect(runSetup(service([], ''), badConfig, basePresets)).rejects.toThrow(/kernel check failed/)
  })
})
