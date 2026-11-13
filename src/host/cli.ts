/**
 * Subprocess bridge to the debrief kernel CLI.
 *
 * Every call is `debrief <command> ... --json`; write commands additionally
 * receive their payload as JSON on stdin. Every outcome — including exec
 * failures, timeouts, and unparsable stdout — is normalized into the
 * canonical envelope, so a failed call is a structured value, never a throw.
 */
import { spawn } from 'node:child_process'
import { ensureKernel, resolveKernelEnv, type EnsureResult } from './kernel.js'
import type { DebriefConfig } from './config.js'

export interface EnvelopeOk {
  ok: true
  schemaVersion: number
  data: unknown
}

export interface EnvelopeError {
  ok: false
  schemaVersion: number
  error: { code: string; message: string }
}

export type Envelope = EnvelopeOk | EnvelopeError

const EXEC_ERROR_CODES: Record<string, string> = {
  ETIMEDOUT: 'DEBRIEF_TIMEOUT',
  ENOENT: 'DEBRIEF_CLI_NOT_FOUND',
  EACCES: 'DEBRIEF_CLI_NOT_EXECUTABLE',
}

const MAX_STDOUT = 8 * 1024 * 1024

/** Normalize a parsed CLI payload into the canonical envelope. */
export function normalizeEnvelope(value: unknown): Envelope {
  if (value && typeof value === 'object') {
    const record = value as Record<string, unknown>
    if (record.ok === false && record.error && typeof record.error === 'object') {
      const error = record.error as Record<string, unknown>
      if (typeof error.code === 'string') {
        return {
          ok: false,
          schemaVersion: typeof record.schemaVersion === 'number' ? record.schemaVersion : 1,
          error: { code: error.code, message: String(error.message ?? '') },
        }
      }
    }
    if (record.ok === true && 'data' in record) {
      return {
        ok: true,
        schemaVersion: typeof record.schemaVersion === 'number' ? record.schemaVersion : 1,
        data: record.data,
      }
    }
  }
  return {
    ok: false,
    schemaVersion: 1,
    error: { code: 'DEBRIEF_BAD_PAYLOAD', message: 'kernel returned an unexpected payload' },
  }
}

export function runCli(
  config: DebriefConfig,
  args: readonly string[],
  options: { signal?: AbortSignal; stdin?: string } = {},
): Promise<Envelope> {
  return ensureKernel(config).then((kernel) => {
    if (!kernel.ready) {
      return {
        ok: false,
        schemaVersion: 1,
        error: { code: kernel.errorCode ?? 'DEBRIEF_BOOTSTRAP', message: kernel.error ?? 'kernel is not ready' },
      } satisfies Envelope
    }
    return runCliResolved(kernel, config, args, options)
  })
}

function runCliResolved(
  kernel: EnsureResult,
  config: DebriefConfig,
  args: readonly string[],
  options: { signal?: AbortSignal; stdin?: string },
): Promise<Envelope> {
  return new Promise((resolve) => {
    if (options.signal?.aborted) {
      resolve({ ok: false, schemaVersion: 1, error: { code: 'DEBRIEF_ABORTED', message: 'cancelled' } })
      return
    }
    let child: ReturnType<typeof spawn>
    try {
      child = spawn(kernel.cliPath, [...kernel.prefixArgs, ...args, '--json'], {
        env: resolveKernelEnv(kernel, process.env, config.telegram),
        stdio: ['pipe', 'pipe', 'pipe'],
      })
    } catch (error) {
      resolve({
        ok: false,
        schemaVersion: 1,
        error: { code: 'DEBRIEF_EXEC', message: error instanceof Error ? error.message : String(error) },
      })
      return
    }

    let settled = false
    const settle = (envelope: Envelope): void => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      options.signal?.removeEventListener('abort', onAbort)
      resolve(envelope)
    }

    const stdoutChunks: Buffer[] = []
    const stderrChunks: Buffer[] = []
    let stdoutSize = 0
    let overflowed = false
    let timedOut = false

    const timer = setTimeout(() => {
      timedOut = true
      child.kill('SIGKILL')
    }, config.timeoutMs)
    const onAbort = (): void => {
      child.kill('SIGTERM')
    }
    if (options.signal) options.signal.addEventListener('abort', onAbort, { once: true })

    child.stdout.on('data', (chunk: Buffer) => {
      if (stdoutSize < MAX_STDOUT) {
        stdoutChunks.push(chunk)
        stdoutSize += chunk.length
      } else {
        overflowed = true
      }
    })
    child.stderr.on('data', (chunk: Buffer) => {
      if (stderrChunks.length < 4) stderrChunks.push(chunk)
    })
    child.on('error', (error: NodeJS.ErrnoException) => {
      if (options.signal?.aborted) {
        settle({ ok: false, schemaVersion: 1, error: { code: 'DEBRIEF_ABORTED', message: 'cancelled' } })
        return
      }
      settle({
        ok: false,
        schemaVersion: 1,
        error: {
          code: timedOut ? 'DEBRIEF_TIMEOUT' : (EXEC_ERROR_CODES[error.code ?? ''] ?? 'DEBRIEF_EXEC'),
          message: timedOut
            ? `kernel timed out after ${config.timeoutMs}ms`
            : error.code === 'ENOENT'
              ? `kernel CLI not found at ${JSON.stringify(kernel.cliPath)}`
              : error.message,
        },
      })
    })
    child.on('close', () => {
      if (options.signal?.aborted) {
        settle({ ok: false, schemaVersion: 1, error: { code: 'DEBRIEF_ABORTED', message: 'cancelled' } })
        return
      }
      if (timedOut) {
        settle({
          ok: false,
          schemaVersion: 1,
          error: { code: 'DEBRIEF_TIMEOUT', message: `kernel timed out after ${config.timeoutMs}ms` },
        })
        return
      }
      const stdout = Buffer.concat(stdoutChunks).toString('utf8')
      let parsed: unknown
      try {
        parsed = JSON.parse(stdout)
      } catch {
        parsed = undefined
      }
      if (parsed && typeof parsed === 'object' && 'ok' in (parsed as Record<string, unknown>)) {
        settle(normalizeEnvelope(parsed))
        return
      }
      const stderr = Buffer.concat(stderrChunks).toString('utf8').slice(0, 300)
      settle({
        ok: false,
        schemaVersion: 1,
        error: {
          code: overflowed ? 'DEBRIEF_OUTPUT_TOO_LARGE' : 'DEBRIEF_PARSE',
          message: overflowed
            ? `kernel stdout exceeded ${MAX_STDOUT} bytes`
            : `kernel returned invalid JSON${stderr ? ` · ${stderr}` : ''}`,
        },
      })
    })

    if (options.stdin !== undefined) {
      child.stdin.write(options.stdin)
    }
    child.stdin.end()
  })
}
