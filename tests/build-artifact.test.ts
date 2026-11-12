import { describe, expect, it } from 'vitest'
import { existsSync, readFileSync } from 'node:fs'
import { execSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { hasTopLevelModuleSyntax, loaderWrapper, stripExports } from '../scripts/strip-client-exports.mjs'

const ROOT = fileURLToPath(new URL('..', import.meta.url))
const CLIENT = fileURLToPath(new URL('../dist/client.js', import.meta.url))

describe('strip-client-exports', () => {
  it('strips top-level declaration exports and leaves nested lines untouched', () => {
    const source = [
      'export const zh = { a: 1 }',
      'const inner = { export: 1 }',
      'export function hello() { return 1 }',
      '  export const indented = 2',
      'export const obj = (x) => ({',
      '  x,',
      '})',
    ].join('\n')
    const stripped = stripExports(source)
    const lines = stripped.split('\n')
    expect(lines[0]).toBe('const zh = { a: 1 }')
    expect(lines[1]).toBe('const inner = { export: 1 }')
    expect(lines[2]).toBe('function hello() { return 1 }')
    expect(lines[3]).toBe('  export const indented = 2') // nested: not a top-level export
    expect(lines[4]).toBe('const obj = (x) => ({')
    expect(hasTopLevelModuleSyntax(stripped)).toBe(false)
  })

  it('detects leftover top-level module syntax', () => {
    expect(hasTopLevelModuleSyntax('export { a }')).toBe(true)
    expect(hasTopLevelModuleSyntax('import x from "y"')).toBe(true)
    expect(hasTopLevelModuleSyntax('const x = 1')).toBe(false)
  })

  it('produces a wrapper-compilable artifact shape', () => {
    const content = 'const zh = { a: 1 }\nif (typeof window !== "undefined") window.__DSH__ = zh\n'
    expect(() => new Function(loaderWrapper(content))).not.toThrow()
  })
})

describe('built client artifact', () => {
  it('has zero top-level exports/imports and compiles in the loader wrapper', () => {
    if (!existsSync(CLIENT)) {
      // CI `test` job may run before `build`; build once so the artifact gate is real.
      execSync('npm run build', { cwd: ROOT, stdio: 'ignore' })
    }
    const content = readFileSync(CLIENT, 'utf8')
    const topLevel = content.split('\n').filter((line) => /^(export|import)\s/.test(line))
    expect(topLevel).toEqual([])
    expect(hasTopLevelModuleSyntax(content)).toBe(false)
    expect(() => new Function(loaderWrapper(content))).not.toThrow()
    // The stripped artifact must still self-register through the module loader.
    expect(content).toContain('window.__ModuleLoader__.load')
    expect(content).toContain('factory: clientFactory')
  })
})
