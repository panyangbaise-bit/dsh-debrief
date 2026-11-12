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

      // worker --dry-run must degrade to a structured envelope error for the
      // missing collectors extra — never an ImportError traceback.
      const worker = await execQuiet(result.cliPath, ['worker', '--dry-run', '--json'], { timeoutMs: 30000 })
      expect(worker.code).not.toBeNull()
      const parsed = JSON.parse(worker.stdout) as { ok?: boolean; error?: { code?: string; message?: string } }
      expect(parsed.ok).toBe(false)
      expect(parsed.error?.code).toBeTruthy()
    } finally {
      try {
        rmSync(dir, { recursive: true, force: true })
      } catch {
        /* best effort */
      }
    }
  }, 240000)
})
