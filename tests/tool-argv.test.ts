import { afterAll, describe, expect, it } from 'vitest'
import { chmodSync, existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { normalizeConfig } from '../src/host/config'
import { defineTools } from '../src/host/tools'

/**
 * Regression guard for argv assembly: a tool's CLI subcommand path must reach
 * the kernel as separate argv tokens. Passing the joined string
 * (`'memory compact-write'`) makes argparse answer DEBRIEF_USAGE
 * "invalid command line", which is exactly how the write tools failed before.
 */
const dir = mkdtempSync(join(tmpdir(), 'debrief-argv-'))
const logPath = join(dir, 'argv.log')
const cliPath = join(dir, 'fake-debrief.cjs')

writeFileSync(
  cliPath,
  [
    '#!/usr/bin/env node',
    "const fs = require('node:fs')",
    "try { fs.readFileSync(0, 'utf8') } catch {}",
    `fs.appendFileSync(${JSON.stringify(logPath)}, JSON.stringify(process.argv.slice(2)) + '\\n')`,
    "process.stdout.write(JSON.stringify({ ok: true, schemaVersion: 1, data: { stub: true } }) + '\\n')",
    '',
  ].join('\n'),
)
chmodSync(cliPath, 0o755)

const config = normalizeConfig({ cliPath, timeoutMs: 5000 }, {})
const tools = defineTools(config)
const byName = (name: string) => tools.find((tool) => tool.name === name)!
const ctx = () => ({ signal: new AbortController().signal })

function loggedArgv(): string[][] {
  if (!existsSync(logPath)) return []
  return readFileSync(logPath, 'utf8')
    .split('\n')
    .filter((line) => line.trim() !== '')
    .map((line) => JSON.parse(line) as string[])
}

const compactPayload = {
  topic: 'position-us-qqq-rationale',
  instruments: ['US:QQQ'],
  summary: '结论',
  evidenceRefs: [{ docId: 12 }],
  timeRange: { from: '2026-10-01', to: '2026-10-31' },
}

afterAll(() => {
  rmSync(dir, { recursive: true, force: true })
})

describe.skipIf(process.platform === 'win32')('tool argv assembly', () => {
  it('splits the compact-write subcommand into separate argv tokens', async () => {
    rmSync(logPath, { force: true })
    const result = await byName('debrief_memory_compact_write').execute(compactPayload, ctx())
    expect(result).toMatchObject({ ok: true })
    expect(loggedArgv()).toEqual([['memory', 'compact-write', '--json']])
  })

  it('splits the memory add subcommand into separate argv tokens', async () => {
    rmSync(logPath, { force: true })
    const result = await byName('debrief_memory_add').execute(
      { sourceType: 'decision', content: '建仓理由', instruments: ['US:QQQ'] },
      ctx(),
    )
    expect(result).toMatchObject({ ok: true })
    expect(loggedArgv()).toEqual([['memory', 'add', '--json']])
  })

  it('splits the report create subcommand into separate argv tokens', async () => {
    rmSync(logPath, { force: true })
    const result = await byName('debrief_report_create').execute(
      { market: 'us', title: '盘后分析', summary: '一句话总结' },
      ctx(),
    )
    expect(result).toMatchObject({ ok: true })
    expect(loggedArgv()).toEqual([['report', 'create', '--json']])
  })

  it('keeps single-word read subcommands as one token', async () => {
    rmSync(logPath, { force: true })
    await byName('debrief_holdings').execute({}, ctx())
    expect(loggedArgv()).toEqual([['holdings', '--json']])
  })

  it('splits the approval-gated edit subcommands into separate argv tokens', async () => {
    rmSync(logPath, { force: true })
    await byName('debrief_holding_add').execute({ market: 'us', symbol: 'QQQ', quantity: 1, cost: 100 }, ctx())
    expect(loggedArgv()).toEqual([['holdings', 'add', '--json']])
  })

  it('keeps the notify subcommand when stdinFrom is present (telegram send)', async () => {
    // Regression: the stdinFrom branch used to drop argsOf, so the kernel saw
    // `notify --json` without notify_command → DEBRIEF_USAGE invalid command line.
    rmSync(logPath, { force: true })
    const result = await byName('debrief_telegram').execute({ action: 'send', text: '盘后复盘' }, ctx())
    expect(result).toMatchObject({ ok: true })
    expect(loggedArgv()).toEqual([['notify', 'send', '--json']])
  })

  it('keeps the notify subcommand when stdinFrom is present (telegram status)', async () => {
    rmSync(logPath, { force: true })
    const result = await byName('debrief_telegram').execute({ action: 'status' }, ctx())
    expect(result).toMatchObject({ ok: true })
    expect(loggedArgv()).toEqual([['notify', 'status', '--json']])
  })

  it('passes since/until through to transactions', async () => {
    rmSync(logPath, { force: true })
    await byName('debrief_transactions').execute({ since: '2026-11-09T00:00:00', until: '2026-11-14T00:00:00' }, ctx())
    expect(loggedArgv()).toEqual([
      ['transactions', '--since', '2026-11-09T00:00:00', '--until', '2026-11-14T00:00:00', '--json'],
    ])
  })

  it('passes since/until through to the job list', async () => {
    rmSync(logPath, { force: true })
    await byName('debrief_jobs').execute({ since: '2026-11-09T00:00:00', until: '2026-11-14T00:00:00' }, ctx())
    expect(loggedArgv()).toEqual([
      ['job', 'list', '--since', '2026-11-09T00:00:00', '--until', '2026-11-14T00:00:00', '--json'],
    ])
  })

  it('routes report list to the list subcommand', async () => {
    rmSync(logPath, { force: true })
    await byName('debrief_report').execute({ list: true, market: 'cn' }, ctx())
    expect(loggedArgv()).toEqual([['report', 'list', '--market', 'cn', '--json']])
  })
})
