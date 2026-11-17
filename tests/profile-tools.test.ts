import { afterAll, describe, expect, it } from 'vitest'
import { chmodSync, existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { normalizeConfig } from '../src/host/config'
import { defineTools, validateWritePayload, writePayloadShapes } from '../src/host/tools'
import { checkProfileWriteArgs, profileWritePayload, PROFILE_SECTION_KEYS } from '../src/host/profile'

describe('profile tool registry', () => {
  const config = normalizeConfig({}, {})
  const tools = defineTools(config)
  const read = tools.find((tool) => tool.name === 'debrief_profile')!
  const write = tools.find((tool) => tool.name === 'debrief_profile_write')!

  it('debrief_profile takes no parameters and documents the evidence package (A2)', () => {
    // The tool() factory compiles parameters into {type:'object', properties} without a required key when empty.
    expect(read.parameters).toEqual({ type: 'object', properties: {} })
    expect(read.description).toContain('evidence package')
    expect(read.description).toContain('updatedBy')
    expect(read.description).toContain('debrief_memory')
  })

  it('debrief_profile_write is a whitelisted write whose sections carry NO updatedBy', () => {
    expect(write.description).toContain('Whitelisted write tool')
    expect(write.description).toContain('user_actions audit')
    expect(write.description).toContain('agent-authored')
    expect(write.description).toContain('protectUserSections')
    const parameters = write.parameters as { properties?: Record<string, unknown>; required?: string[] }
    expect(parameters.required).toBeUndefined() // empty required lists are omitted by the factory
    const sectionItems = (parameters.properties?.sections as { items?: { properties?: Record<string, unknown> } })
      ?.items?.properties
    expect(Object.keys(sectionItems ?? {}).sort()).toEqual(['content', 'key'])
  })
})

describe('profile write payload validation', () => {
  it('accepts a partial section write and remaps fields onto stdin', () => {
    const result = validateWritePayload('profileWrite', {
      sections: [
        // The model may copy compact-write style and inject updatedBy; the builder must strip it.
        { key: 'habits', content: '偏好右侧确认后分批建仓。', updatedBy: 'agent' },
        { key: 'advice', content: '不要追高。', updatedBy: 'agent' },
      ],
      evidenceRefs: [{ docId: 3441, quote: 'quote must not pass through' }],
      expectedVersion: 3,
      protectUserSections: true,
      markdown: 'smuggled',
    })
    expect(result.ok).toBe(true)
    const parsed = JSON.parse(result.stdin!) as Record<string, unknown>
    expect(parsed).toEqual({
      sections: [
        { key: 'habits', content: '偏好右侧确认后分批建仓。' },
        { key: 'advice', content: '不要追高。' },
      ],
      evidenceRefs: [{ docId: 3441 }],
      expectedVersion: 3,
      protectUserSections: true,
    })
  })

  it('requires at least one of sections or evidenceRefs', () => {
    const result = validateWritePayload('profileWrite', {})
    expect(result.ok).toBe(false)
    expect(result.error?.code).toBe('DEBRIEF_ARGS')
  })

  it('rejects unknown section keys', () => {
    const result = validateWritePayload('profileWrite', { sections: [{ key: 'nope', content: 'x' }] })
    expect(result.ok).toBe(false)
    expect(result.error?.message).toContain(PROFILE_SECTION_KEYS.join('/'))
  })

  it('rejects evidence refs without an integer docId', () => {
    const result = validateWritePayload('profileWrite', { evidenceRefs: [{ quote: 'no doc' }] })
    expect(result.ok).toBe(false)
  })

  it('exposes the same shape through writePayloadShapes', () => {
    expect(writePayloadShapes.profileWrite.type).toBe('object')
  })

  it('checkProfileWriteArgs covers the at-least-one rule and key whitelist', () => {
    expect(checkProfileWriteArgs({})).toContain('at least one')
    expect(checkProfileWriteArgs({ sections: [{ key: 'risk', content: 'x' }] })).toBeUndefined()
    expect(checkProfileWriteArgs({ evidenceRefs: [{ docId: 1 }] })).toBeUndefined()
    expect(checkProfileWriteArgs({ sections: [{ key: 'bogus', content: 'x' }] })).toContain('sections key must be')
  })

  it('profileWritePayload keeps only declared top-level fields', () => {
    const stdin = profileWritePayload({
      sections: [{ key: 'risk', content: '保守', updatedBy: 'user' }],
      title: 'hacked',
      unknown: true,
    })
    const parsed = JSON.parse(stdin) as Record<string, unknown>
    expect(parsed).toEqual({ sections: [{ key: 'risk', content: '保守' }] })
  })
})

describe.skipIf(process.platform === 'win32')('profile tool argv assembly', () => {
  const dir = mkdtempSync(join(tmpdir(), 'debrief-profile-argv-'))
  const logPath = join(dir, 'argv.log')
  const cliPath = join(dir, 'fake-debrief.cjs')
  writeFileSync(
    cliPath,
    [
      '#!/usr/bin/env node',
      "const fs = require('node:fs')",
      "let stdin = ''",
      "try { stdin = fs.readFileSync(0, 'utf8') } catch {}",
      `fs.appendFileSync(${JSON.stringify(logPath)}, JSON.stringify({ argv: process.argv.slice(2), stdin }) + '\\n')`,
      "process.stdout.write(JSON.stringify({ ok: true, schemaVersion: 1, data: { stub: true } }) + '\\n')",
      '',
    ].join('\n'),
  )
  chmodSync(cliPath, 0o755)
  const config = normalizeConfig({ cliPath, timeoutMs: 5000 }, {})
  const tools = defineTools(config)
  const byName = (name: string) => tools.find((tool) => tool.name === name)!
  const ctx = () => ({ signal: new AbortController().signal })

  function loggedCalls(): Array<{ argv: string[]; stdin: string }> {
    if (!existsSync(logPath)) return []
    return readFileSync(logPath, 'utf8')
      .split('\n')
      .filter((line) => line.trim() !== '')
      .map((line) => JSON.parse(line) as { argv: string[]; stdin: string })
  }

  afterAll(() => {
    rmSync(dir, { recursive: true, force: true })
  })

  it('debrief_profile runs profile get without arguments', async () => {
    rmSync(logPath, { force: true })
    const result = await byName('debrief_profile').execute({}, ctx())
    expect(result).toMatchObject({ ok: true })
    expect(loggedCalls()).toEqual([{ argv: ['profile', 'get', '--json'], stdin: '' }])
  })

  it('debrief_profile_write runs profile write --by agent with the remapped payload on stdin', async () => {
    rmSync(logPath, { force: true })
    const result = await byName('debrief_profile_write').execute(
      {
        sections: [{ key: 'decisions', content: '新决策：减仓半导体。', updatedBy: 'agent' }],
        evidenceRefs: [{ docId: 7, quote: 'strip me' }],
        expectedVersion: 2,
      },
      ctx(),
    )
    expect(result).toMatchObject({ ok: true })
    const calls = loggedCalls()
    expect(calls).toHaveLength(1)
    expect(calls[0]!.argv).toEqual(['profile', 'write', '--by', 'agent', '--json'])
    const stdin = JSON.parse(calls[0]!.stdin) as Record<string, unknown>
    expect(stdin).toEqual({
      sections: [{ key: 'decisions', content: '新决策：减仓半导体。' }],
      evidenceRefs: [{ docId: 7 }],
      expectedVersion: 2,
    })
  })

  it('rejects an invalid write before the CLI is invoked', async () => {
    rmSync(logPath, { force: true })
    const result = await byName('debrief_profile_write').execute({}, ctx())
    expect(result).toMatchObject({ ok: false, error: { code: 'DEBRIEF_ARGS' } })
    expect(loggedCalls()).toEqual([])
  })
})
