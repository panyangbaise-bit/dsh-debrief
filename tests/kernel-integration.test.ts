import { describe, expect, it } from 'vitest'
import { existsSync, mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { ensureKernel, execQuiet, findKernelWheel, wheelsDir } from '../src/host/kernel'

// Real end-to-end bootstrap: needs uv on PATH; skipped in environments without it.
const uvProbe = await execQuiet('uv', ['--version'], { timeoutMs: 10000 })
const uvAvailable = uvProbe.code === 0

const wheel = findKernelWheel(wheelsDir())

describe.skipIf(!uvAvailable || wheel === undefined)('integration: real offline bootstrap', () => {
  it('bootstraps the bundled kernel wheel with uv, fully offline, and runs the CLI', async () => {
    const dir = mkdtempSync(join(tmpdir(), 'dsh-debrief-integration-'))
    try {
      const env = { DEBRIEF_DATA_DIR: join(dir, 'runtime'), DEBRIEF_WHEELS_DIR: wheelsDir(), PATH: process.env.PATH }
      const result = await ensureKernel({ kernelMode: 'managed', dataDir: env.DEBRIEF_DATA_DIR }, env)
      expect(result.ready).toBe(true)
      expect(result.mode).toBe('managed')
      expect(existsSync(result.cliPath)).toBe(true)

      // The installed console script answers --help.
      const help = await execQuiet(result.cliPath, ['--help'], { timeoutMs: 30000 })
      expect(help.code).toBe(0)

      // Content self-check: the fixed wheel must ship the adapters module
      // (guards the --no-cache install against stale same-version caches).
      const venvPython = join(env.DEBRIEF_DATA_DIR as string, 'venv', 'bin', 'python')
      const content = await execQuiet(venvPython, ['-c', 'import adapters, debrief'], { timeoutMs: 30000 })
      expect(content.code, `import adapters, debrief failed: ${content.stderr}`).toBe(0)

      // worker --dry-run must degrade to a structured envelope error for the
      // missing collectors extra — never an ImportError traceback.
      const worker = await execQuiet(result.cliPath, ['worker', '--dry-run', '--json'], { timeoutMs: 30000 })
      expect(worker.code).not.toBeNull()
      const parsed = JSON.parse(worker.stdout) as { ok?: boolean; error?: { code?: string; message?: string } }
      expect(parsed.ok).toBe(false)
      expect(parsed.error?.code).toBeTruthy()

      // From kernel 0.2.2 the CLI honors DATABASE_URL without --db; assert a
      // real read command works under the URL runCli injects in managed mode.
      const versionMatch = /portfolio_agent_kernel-(\d+)\.(\d+)\.(\d+)-/.exec(wheel ?? '')
      const major = Number(versionMatch?.[1] ?? 0)
      const minor = Number(versionMatch?.[2] ?? 0)
      const patch = Number(versionMatch?.[3] ?? 0)
      if (major > 0 || (major === 0 && (minor > 2 || (minor === 2 && patch >= 2)))) {
        const search = await execQuiet(
          result.cliPath,
          ['instruments', 'search', '--market', 'us', '--query', 'aapl', '--json'],
          { env: { DATABASE_URL: result.dbUrl ?? '' }, timeoutMs: 60000 },
        )
        expect(search.code).toBe(0)
        const searchBody = JSON.parse(search.stdout) as { ok?: boolean; error?: { code?: string } }
        expect(searchBody, `instruments search failed: ${search.stdout.slice(0, 200)}`).toMatchObject({ ok: true })
      }
    } finally {
      try {
        rmSync(dir, { recursive: true, force: true })
      } catch {
        /* best effort */
      }
    }
  }, 240000)
})
