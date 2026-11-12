import { afterEach, describe, expect, it } from 'vitest'
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  utimesSync,
  writeFileSync,
  chmodSync,
  existsSync,
} from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  acquireBootstrapLock,
  detectBootstrapTool,
  ensureKernel,
  findKernelWheel,
  resolveKernelMode,
  wheelsDir,
  type EnsureResult,
} from '../src/host/kernel'
import { runCli } from '../src/host/cli'
import { normalizeConfig } from '../src/host/config'

const MOCK = fileURLToPath(new URL('../mock/debrief.js', import.meta.url))

const tmp = mkdtempSync(join(tmpdir(), 'dsh-debrief-kernel-test-'))
const cleanup: string[] = [tmp]

function tempDir(label: string): string {
  const dir = join(tmp, label)
  mkdirSync(dir, { recursive: true })
  cleanup.push(dir)
  return dir
}

afterEach(() => {
  delete process.env.DEBRIEF_DATA_DIR
  delete process.env.DEBRIEF_WHEELS_DIR
  for (const dir of cleanup.splice(1)) {
    try {
      rmSync(dir, { recursive: true, force: true })
    } catch {
      /* best effort */
    }
  }
})

interface FakeResult {
  ok: true
  code: number | null
  stdout: string
  stderr: string
  error?: string
}

/** Write an executable shell script into the temp PATH dir. */
function fakeTool(dir: string, name: string, script: string): void {
  writeFileSync(join(dir, name), `#!/bin/sh\n${script}\n`)
  chmodSync(join(dir, name), 0o755)
}

/** Build a temp PATH with fake uv and a fake kernel-debrief installer. */
function fakeEnvironment(): { bin: string; env: Record<string, string | undefined>; log: string[] } {
  const bin = tempDir(`bin-${Math.random().toString(36).slice(2)}`)
  const log: string[] = []
  fakeTool(
    bin,
    'uv',
    [
      'echo "uv $@" >> "$LOG"',
      'case "$1" in',
      '  venv)',
      '    VENV="$4"',
      '    mkdir -p "$VENV/bin"',
      '    cat > "$VENV/bin/debrief" <<"EOF"',
      '#!/bin/sh',
      'echo "{\\"ok\\":true,\\"schemaVersion\\":1,\\"data\\":{\\"status\\":\\"ok\\"}}"',
      'EOF',
      '    chmod +x "$VENV/bin/debrief"',
      '    cp "$VENV/bin/debrief" "$VENV/bin/python"',
      '    exit 0',
      '    ;;',
      '  pip)',
      '    exit 0',
      '    ;;',
      'esac',
      'exit 0',
    ].join('\n'),
  )
  return {
    bin,
    env: {
      PATH: bin,
      DEBRIEF_DATA_DIR: join(tmp, `data-${Math.random().toString(36).slice(2)}`),
      LOG: join(bin, 'calls.log'),
    },
    log,
  }
}

/** Exec stub capturing invocations; delegates to a real process when configured. */
function recordingExec(records: string[]): typeof import('../src/host/kernel').execQuiet {
  return async (command, args) => {
    records.push(`${command} ${args.join(' ')}`)
    return { code: 0, stdout: '', stderr: '' }
  }
}

function fakeWheelsDir(wheelNames: string[]): string {
  const dir = tempDir(`wheels-${Math.random().toString(36).slice(2)}`)
  for (const name of wheelNames) {
    writeFileSync(join(dir, name), 'FAKE-WHEEL')
  }
  return dir
}

function rawConfig(overrides: Record<string, unknown> = {}): ReturnType<typeof normalizeConfig> {
  return normalizeConfig({ timeoutMs: 5000, ...overrides }, {})
}

describe('kernel mode resolution', () => {
  it('resolves explicit modes and cliPath precedence', () => {
    expect(resolveKernelMode({ kernelMode: 'external' })).toEqual({ mode: 'external', cliPath: 'debrief' })
    expect(resolveKernelMode({ kernelMode: 'external', cliPath: '/opt/debrief/bin/debrief' })).toEqual({
      mode: 'external',
      cliPath: '/opt/debrief/bin/debrief',
    })
    expect(resolveKernelMode({ kernelMode: 'managed', cliPath: '/x' })).toEqual({ mode: 'managed', cliPath: '' })
    expect(resolveKernelMode({ kernelMode: 'auto', cliPath: '/x' })).toEqual({ mode: 'external', cliPath: '/x' })
    expect(resolveKernelMode({ kernelMode: 'auto' })).toEqual({ mode: 'managed', cliPath: '' })
  })
})

describe('wheel directory resolution', () => {
  it('returns the newest kernel wheel and ignores dependency wheels', () => {
    const dir = fakeWheelsDir([
      'sqlalchemy-2.1.8-py3-none-any.whl',
      'portfolio_agent_kernel-0.2.0-py3-none-any.whl',
      'portfolio_agent_kernel-0.3.0-py3-none-any.whl',
    ])
    expect(findKernelWheel(dir)).toBe('portfolio_agent_kernel-0.3.0-py3-none-any.whl')
  })

  it('returns undefined when the slim wheel is missing from a wheels dir', () => {
    const dir = fakeWheelsDir(['sqlalchemy-2.1.8-py3-none-any.whl'])
    expect(findKernelWheel(dir)).toBeUndefined()
  })
})

describe('bootstrap tool detection', () => {
  it('prefers uv when it is on PATH', async () => {
    const { bin } = fakeEnvironment()
    fakeTool(bin, 'uv', 'echo uv 0.5.0')
    const tool = await detectBootstrapTool({ PATH: bin })
    expect(tool).toEqual({ ok: true, tool: 'uv', toolPath: 'uv' })
  })

  it('falls back to python3.11+ with a version check', async () => {
    const bin = tempDir('pybin')
    fakeTool(bin, 'python3.11', 'echo 3.11')
    const tool = await detectBootstrapTool({ PATH: bin })
    expect(tool).toEqual({ ok: true, tool: 'python', toolPath: 'python3.11', version: '3.11' })
  })

  it('rejects python < 3.11 and empty PATH', async () => {
    const old = tempDir('oldpy')
    fakeTool(old, 'python3.11', 'echo 3.9')
    expect((await detectBootstrapTool({ PATH: old })).ok).toBe(false)
    expect((await detectBootstrapTool({ PATH: tempDir('empty') })).ok).toBe(false)
  })
})

describe('managed bootstrap (mocked uv, offline)', () => {
  it('bootstraps once, writes a marker, and reuses it on later calls', async () => {
    const { bin, env } = fakeEnvironment()
    const records: string[] = []
    const exec = recordingExec(records)
    const wheelDir = fakeWheelsDir(['portfolio_agent_kernel-0.2.0-py3-none-any.whl'])
    const config = rawConfig({ kernelMode: 'managed', dataDir: env.DEBRIEF_DATA_DIR })

    // The recording exec does not create the venv; emulate the fake uv side effects here.
    const fakeExec = async (command: string, args: readonly string[]): Promise<FakeResult> => {
      records.push(`${command} ${args.join(' ')}`)
      if (command === 'uv' && args[0] === 'venv') {
        const venv = String(args[3])
        mkdirSync(join(venv, 'bin'), { recursive: true })
        writeFileSync(join(venv, 'bin', 'debrief'), '#!/bin/sh\necho ok\n')
        chmodSync(join(venv, 'bin', 'debrief'), 0o755)
        writeFileSync(join(venv, 'bin', 'python'), '#!/bin/sh\necho ok\n')
        chmodSync(join(venv, 'bin', 'python'), 0o755)
      }
      // venv python self-check (import adapters, debrief)
      if (command.endsWith(join('bin', 'python')) && args[0] === '-c') {
        return { ok: true, code: 0, stdout: '', stderr: '' }
      }
      return { ok: true, code: 0, stdout: '', stderr: '' }
    }

    const first = await ensureKernel(config, env, fakeExec as never, wheelDir)
    expect(first.ready).toBe(true)
    expect(first.mode).toBe('managed')
    expect(first.cliPath).toBe(join(env.DEBRIEF_DATA_DIR as string, 'venv', 'bin', 'debrief'))
    expect(first.wheel).toBe('portfolio_agent_kernel-0.2.0-py3-none-any.whl')

    const marker = JSON.parse(readFileSync(join(env.DEBRIEF_DATA_DIR as string, 'kernel.json'), 'utf8')) as {
      cliPath: string
      wheel: string
    }
    expect(marker.cliPath).toBe(first.cliPath)
    expect(marker.wheel).toContain('portfolio_agent_kernel-0.2.0-py3-none-any.whl')

    const callsBefore = records.length
    const second = await ensureKernel(config, env, fakeExec as never, wheelDir)
    expect(second.ready).toBe(true)
    expect(records.length).toBe(callsBefore) // fast path: no new bootstrap calls

    // Install bypassed the cache and the content self-check ran.
    expect(records.some((record) => record.includes('--no-cache'))).toBe(true)
    expect(records.some((record) => record.includes('import adapters, debrief'))).toBe(true)
  })

  it('reports DEBRIEF_BOOTSTRAP_INCOMPLETE when the content self-check fails', async () => {
    const { env } = fakeEnvironment()
    const fakeExec = async (command: string, args: readonly string[]): Promise<FakeResult> => {
      if (command === 'uv' && args[0] === 'venv') {
        const venv = String(args[3])
        mkdirSync(join(venv, 'bin'), { recursive: true })
        writeFileSync(join(venv, 'bin', 'debrief'), '#!/bin/sh\necho ok\n')
        chmodSync(join(venv, 'bin', 'debrief'), 0o755)
        writeFileSync(join(venv, 'bin', 'python'), '#!/bin/sh\necho ok\n')
        chmodSync(join(venv, 'bin', 'python'), 0o755)
        return { ok: true, code: 0, stdout: '', stderr: '' }
      }
      if (command.endsWith(join('bin', 'python')) && args[0] === '-c') {
        return { ok: true, code: 1, stdout: '', stderr: 'ModuleNotFoundError: No module named adapters' }
      }
      return { ok: true, code: 0, stdout: '', stderr: '' }
    }
    const wheelDir = fakeWheelsDir(['portfolio_agent_kernel-0.2.0-py3-none-any.whl'])
    const config = rawConfig({ kernelMode: 'managed', dataDir: env.DEBRIEF_DATA_DIR })
    const result = await ensureKernel(config, env, fakeExec as never, wheelDir)
    expect(result.ready).toBe(false)
    expect(result.errorCode).toBe('DEBRIEF_BOOTSTRAP_INCOMPLETE')
    expect(result.error).toContain('adapters')
  })

  it('rebuilds when the bundled wheel fingerprint changes', async () => {
    const { env } = fakeEnvironment()
    const records: string[] = []
    const fakeExec = async (command: string, args: readonly string[]): Promise<FakeResult> => {
      records.push(`${command} ${args.join(' ')}`)
      if (command === 'uv' && args[0] === 'venv') {
        const venv = String(args[3])
        mkdirSync(join(venv, 'bin'), { recursive: true })
        writeFileSync(join(venv, 'bin', 'debrief'), '#!/bin/sh\necho ok\n')
        chmodSync(join(venv, 'bin', 'debrief'), 0o755)
        writeFileSync(join(venv, 'bin', 'python'), '#!/bin/sh\necho ok\n')
        chmodSync(join(venv, 'bin', 'python'), 0o755)
      }
      // venv python self-check (import adapters, debrief)
      if (command.endsWith(join('bin', 'python')) && args[0] === '-c') {
        return { ok: true, code: 0, stdout: '', stderr: '' }
      }
      return { ok: true, code: 0, stdout: '', stderr: '' }
    }
    const wheelDir = fakeWheelsDir(['portfolio_agent_kernel-0.2.0-py3-none-any.whl'])
    const config = rawConfig({ kernelMode: 'managed', dataDir: env.DEBRIEF_DATA_DIR })
    await ensureKernel(config, env, fakeExec as never, wheelDir)
    const afterFirst = records.length

    // Replace the wheel with a newer one (fingerprint changes).
    writeFileSync(join(wheelDir, 'portfolio_agent_kernel-0.2.0-py3-none-any.whl'), 'FAKE-WHEEL-NEWER-BYTE-CONTENT')
    const rebuilt = await ensureKernel(config, env, fakeExec as never, wheelDir)
    expect(rebuilt.ready).toBe(true)
    expect(records.length).toBeGreaterThan(afterFirst)
  })

  it('returns DEBRIEF_NO_WHEEL when the slim wheel is missing', async () => {
    const { env } = fakeEnvironment()
    const wheelDir = fakeWheelsDir(['sqlalchemy-2.1.8-py3-none-any.whl'])
    const config = rawConfig({ kernelMode: 'managed', dataDir: env.DEBRIEF_DATA_DIR })
    const result = await ensureKernel(config, env, recordingExec([]) as never, wheelDir)
    expect(result.ready).toBe(false)
    expect(result.errorCode).toBe('DEBRIEF_NO_WHEEL')
  })

  it('returns DEBRIEF_NO_PYTHON without uv or python', async () => {
    const emptyBin = tempDir('nopy')
    const env = { PATH: emptyBin, DEBRIEF_DATA_DIR: join(tmp, 'nopy-data') }
    const wheelDir = fakeWheelsDir(['portfolio_agent_kernel-0.2.0-py3-none-any.whl'])
    const config = rawConfig({ kernelMode: 'managed', dataDir: env.DEBRIEF_DATA_DIR })
    const result = await ensureKernel(config, env, undefined as never, wheelDir)
    expect(result.ready).toBe(false)
    expect(result.errorCode).toBe('DEBRIEF_NO_PYTHON')
  })

  it('external mode is a zero-cost passthrough', async () => {
    const config = rawConfig({ kernelMode: 'external', cliPath: '/opt/debrief/bin/debrief' })
    const result = await ensureKernel(config, {}, recordingExec([]) as never)
    expect(result).toEqual({ ready: true, mode: 'external', cliPath: '/opt/debrief/bin/debrief', prefixArgs: [] })
  })
})

describe('bootstrap lock', () => {
  it('acquires when free, times out when held, steals stale locks', async () => {
    const dir = tempDir('lock')
    const lock = await acquireBootstrapLock(dir)
    expect(lock.acquired).toBe(true)

    let tick = 0
    const fastNow = (): number => {
      tick += 61_000
      return Date.now() + tick
    }
    const held = await acquireBootstrapLock(dir, fastNow)
    expect(held.acquired).toBe(false) // deadline exceeded → structured initializing
    lock.release()

    const again = await acquireBootstrapLock(dir)
    expect(again.acquired).toBe(true)
    again.release()

    // Stale lock gets stolen.
    const stale = await acquireBootstrapLock(dir)
    expect(stale.acquired).toBe(true)
    const old = Date.now() - 11 * 60 * 1000
    utimesSync(join(dir, '.bootstrap-lock'), new Date(old), new Date(old))
    stale.release()
    mkdirSync(join(dir, '.bootstrap-lock'))
    utimesSync(join(dir, '.bootstrap-lock'), new Date(old), new Date(old))
    const stolen = await acquireBootstrapLock(dir)
    expect(stolen.acquired).toBe(true)
    stolen.release()
  })
})

describe('runCli kernel prefix (managed path)', () => {
  it('runs the bootstrapped launcher with the CLI prefix', async () => {
    const { env } = fakeEnvironment()
    const records: string[] = []
    const fakeExec = async (command: string, args: readonly string[]): Promise<FakeResult> => {
      records.push(`${command} ${args.join(' ')}`)
      if (command === 'uv' && args[0] === 'venv') {
        const venv = String(args[3])
        mkdirSync(join(venv, 'bin'), { recursive: true })
        writeFileSync(
          join(venv, 'bin', 'debrief'),
          '#!/bin/sh\necho "{\\"ok\\":true,\\"schemaVersion\\":1,\\"data\\":{\\"ran\\":true}}"\n',
        )
        chmodSync(join(venv, 'bin', 'debrief'), 0o755)
      }
      return { ok: true, code: 0, stdout: '', stderr: '' }
    }
    const wheelDir = fakeWheelsDir(['portfolio_agent_kernel-0.2.0-py3-none-any.whl'])
    const config = normalizeConfig({ kernelMode: 'managed', dataDir: env.DEBRIEF_DATA_DIR, timeoutMs: 10000 }, {})
    // runCli resolves the wheels dir from the env override, so its internal
    // ensureKernel sees the same fake wheel fingerprint as the marker above.
    process.env.DEBRIEF_WHEELS_DIR = wheelDir
    process.env.DEBRIEF_DATA_DIR = env.DEBRIEF_DATA_DIR
    await ensureKernel(config, env, fakeExec as never, wheelDir)
    const envelope = await runCli(
      { ...config, cliPath: undefined, kernelMode: 'managed', dataDir: env.DEBRIEF_DATA_DIR },
      ['holdings'],
    )
    expect(envelope).toEqual({ ok: true, schemaVersion: 1, data: { ran: true } })
  })

  it('keeps the existing external passthrough behavior', async () => {
    const config = normalizeConfig({ cliPath: process.execPath, timeoutMs: 10000 }, {})
    const envelope = await runCli(config, [MOCK, 'holdings'])
    expect(envelope.ok).toBe(true)
    if (envelope.ok) expect((envelope.data as Record<string, unknown>).totalMarketValue).toBe(1234567)
  })
})

describe('bundled wheels audit', () => {
  it('bundled dir ships exactly one slim kernel wheel plus the offline dependency closure', () => {
    // The real bundled dir must contain exactly one kernel wheel and the 8
    // dependency wheels the lead verified as the exact offline closure.
    const dir = wheelsDir()
    const entries = existsSync(dir) ? readdirSync(dir) : []
    const kernelWheels = entries.filter((name) => name.startsWith('portfolio_agent_kernel-') && name.endsWith('.whl'))
    expect(kernelWheels.length).toBe(1)
    for (const name of [
      'sqlalchemy-2.1.8-py3-none-any.whl',
      'requests-2.34.2-py3-none-any.whl',
      'python_dotenv-1.2.4-py3-none-any.whl',
      'certifi-2026.10.23-py3-none-any.whl',
      'charset_normalizer-3.5.2-py3-none-any.whl',
      'idna-3.20-py3-none-any.whl',
      'urllib3-2.8.0-py3-none-any.whl',
      'typing_extensions-4.16.0-py3-none-any.whl',
    ]) {
      expect(entries, `missing offline wheel ${name}`).toContain(name)
    }
  })
})
