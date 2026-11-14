/**
 * Self-contained kernel distribution (managed mode).
 *
 * The npm package bundles offline wheels under `kernel/wheels/`. On first use
 * the Host bootstraps an isolated venv into the data directory
 * (default `~/.dsh/debrief-runtime/`, Config `dataDir` overrides):
 *
 *   1. `uv venv --python 3.11 <dataDir>/venv` when `uv` is on PATH,
 *      else `python3.11|python3.12|python3.13 -m venv` — no Python ≥3.11 and
 *      no uv is a structured DEBRIEF_NO_PYTHON error.
 *   2. `pip install --no-index --find-links <kernel/wheels>
 *      portfolio_agent_kernel` — fully offline, no network access.
 *   3. A marker file records the installed wheel fingerprint; a version
 *      mismatch rebuilds the venv.
 *
 * Modes: `external` uses the configured cliPath as-is (server deployment);
 * `managed` always bootstraps; `auto` prefers an explicitly configured
 * cliPath, otherwise bootstraps. Bootstrap output is captured separately and
 * never pollutes the CLI envelope. A directory lock serializes concurrent
 * bootstraps; callers wait, and a timed-out wait is DEBRIEF_KERNEL_INITIALIZING.
 */
import { existsSync, mkdirSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { basename, join } from 'node:path'
import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import type { DebriefConfig } from './config.js'

export const KERNEL_PACKAGE = 'portfolio_agent_kernel'
export const KERNEL_WHEEL_PREFIX = 'portfolio_agent_kernel-'
const MARKER_SCHEMA = 1
const LOCK_STALE_MS = 10 * 60 * 1000
const LOCK_WAIT_MS = 60 * 1000

export type KernelMode = 'auto' | 'external' | 'managed'

export interface KernelRuntime {
  mode: 'external' | 'managed'
  cliPath: string
  prefixArgs: readonly string[]
  ready: boolean
  dataDir?: string
  wheel?: string
  errorCode?: string
  error?: string
}

export interface KernelConfigLike {
  kernelMode?: KernelMode
  cliPath?: string
  dataDir?: string
  withCollectors?: boolean
}

export function wheelsDir(env: Record<string, string | undefined> = process.env): string {
  return env.DEBRIEF_WHEELS_DIR ?? fileURLToPath(new URL('../../kernel/wheels/', import.meta.url))
}

/** Resolve the effective mode: external when cliPath is configured, else managed. */
export function resolveKernelMode(config: KernelConfigLike): { mode: 'external' | 'managed'; cliPath: string } {
  if (config.kernelMode === 'external') {
    return { mode: 'external', cliPath: config.cliPath ?? 'debrief' }
  }
  if (config.kernelMode === 'managed') {
    return { mode: 'managed', cliPath: '' }
  }
  if (config.cliPath !== undefined && config.cliPath !== '') {
    return { mode: 'external', cliPath: config.cliPath }
  }
  return { mode: 'managed', cliPath: '' }
}

/** Newest bundled kernel wheel, or undefined when the slim wheel is absent. */
export function findKernelWheel(dir: string): string | undefined {
  let entries: string[]
  try {
    entries = readdirSync(dir)
  } catch {
    return undefined
  }
  const wheels = entries.filter((name) => name.startsWith(KERNEL_WHEEL_PREFIX) && name.endsWith('.whl')).sort()
  return wheels[wheels.length - 1]
}

export function runtimeDataDir(config: KernelConfigLike, env: Record<string, string | undefined>): string {
  const dir = config.dataDir ?? env.DEBRIEF_DATA_DIR ?? join(homedir(), '.dsh', 'debrief-runtime')
  return dir.startsWith('~/') ? join(homedir(), dir.slice(2)) : dir
}

/** The sqlite URL managed mode injects when the user has no DATABASE_URL. */
export function managedDbUrl(dataDir: string): string {
  return `sqlite:///${join(dataDir, 'portfolio.db')}`
}

/**
 * Subprocess environment for one kernel call: managed mode injects
 * `DATABASE_URL=sqlite:///<dataDir>/portfolio.db` unless the user already
 * configured one; external mode passes the environment through untouched.
 * Non-empty `telegram` credentials are additionally overlaid as
 * `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` (existing env values are never
 * wiped when the config omits or empties a value).
 *
 * `pycachePrefix` is overlaid as `PYTHONPYCACHEPREFIX` (existing values win).
 * Without it a read-only venv — the common server deployment, where the venv
 * is root-owned and the Host runs as another user — cannot persist `.pyc`
 * files, and every cold `debrief` call recompiles pandas/akshare from source
 * (~2-3 s per page view).
 */
export function resolveKernelEnv(
  kernel: Pick<EnsureResult, 'mode' | 'dbUrl'>,
  env: Record<string, string | undefined>,
  telegram?: { botToken?: string; chatId?: string },
  pycachePrefix?: string,
): Record<string, string | undefined> {
  let resolved = { ...env }
  if (
    kernel.mode === 'managed' &&
    kernel.dbUrl !== undefined &&
    (env.DATABASE_URL === undefined || env.DATABASE_URL === '')
  ) {
    resolved = { ...resolved, DATABASE_URL: kernel.dbUrl }
  }
  if (pycachePrefix !== undefined && pycachePrefix !== '' && !resolved.PYTHONPYCACHEPREFIX) {
    resolved = { ...resolved, PYTHONPYCACHEPREFIX: pycachePrefix }
  }
  if (telegram?.botToken !== undefined && telegram.botToken !== '') {
    resolved = { ...resolved, TELEGRAM_BOT_TOKEN: telegram.botToken }
  }
  if (telegram?.chatId !== undefined && telegram.chatId !== '') {
    resolved = { ...resolved, TELEGRAM_CHAT_ID: telegram.chatId }
  }
  return resolved
}

/**
 * Writable bytecode-cache directory for kernel subprocesses: Config
 * `pycachePrefix`, else `<dataDir>/pycache`, else `<homedir>/.dsh/
 * debrief-runtime/pycache`. An empty configured string disables it.
 */
export function pycachePrefixFor(
  config: KernelConfigLike & { pycachePrefix?: string },
  env: Record<string, string | undefined>,
): string | undefined {
  if (config.pycachePrefix === '') return undefined
  return config.pycachePrefix ?? join(runtimeDataDir(config, env), 'pycache')
}

const venvBin = (dataDir: string): string => join(dataDir, 'venv', process.platform === 'win32' ? 'Scripts' : 'bin')
const markerPath = (dataDir: string): string => join(dataDir, 'kernel.json')

interface Marker {
  schemaVersion: number
  wheel: string
  cliPath: string
  prefixArgs: string[]
  installedAt: string
}

function readMarker(dataDir: string): Marker | undefined {
  try {
    const parsed = JSON.parse(readFileSync(markerPath(dataDir), 'utf8')) as Marker
    if (parsed.schemaVersion === MARKER_SCHEMA && typeof parsed.cliPath === 'string') return parsed
    return undefined
  } catch {
    return undefined
  }
}

/** Fingerprint of the bundled wheel: name + size (stable offline signal). */
export function wheelFingerprint(wheelPath: string): string {
  try {
    const stat = statSync(wheelPath)
    return `${basename(wheelPath)}@${stat.size}`
  } catch {
    return basename(wheelPath)
  }
}

interface ExecResult {
  code: number | null
  stdout: string
  stderr: string
  error?: string
}

/** Capture stdout/stderr separately — bootstrap chatter must never reach the CLI envelope. */
export function execQuiet(
  command: string,
  args: readonly string[],
  options: { timeoutMs?: number; env?: Record<string, string | undefined> } = {},
): Promise<ExecResult> {
  return new Promise((resolve) => {
    let child: ReturnType<typeof spawn>
    try {
      child = spawn(command, [...args], {
        env: { ...process.env, ...options.env },
        stdio: ['ignore', 'pipe', 'pipe'],
      })
    } catch (error) {
      resolve({ code: null, stdout: '', stderr: '', error: error instanceof Error ? error.message : String(error) })
      return
    }
    const stdout: Buffer[] = []
    const stderr: Buffer[] = []
    let timedOut = false
    const timer = setTimeout(() => {
      timedOut = true
      child.kill('SIGKILL')
    }, options.timeoutMs ?? 120000)
    child.stdout.on('data', (chunk: Buffer) => stdout.push(chunk))
    child.stderr.on('data', (chunk: Buffer) => stderr.push(chunk))
    child.on('error', (error: NodeJS.ErrnoException) => {
      clearTimeout(timer)
      resolve({ code: null, stdout: '', stderr: '', error: error.message })
    })
    child.on('close', (code) => {
      clearTimeout(timer)
      resolve({
        code,
        stdout: Buffer.concat(stdout).toString('utf8'),
        stderr: Buffer.concat(stderr).toString('utf8'),
        ...(timedOut ? { error: `command timed out: ${command} ${args.join(' ')}` } : {}),
      })
    })
  })
}

/**
 * Precompile a managed venv's library tree.
 *
 * pandas + numpy + akshare are ≈4 000 modules; without `.pyc` on disk every
 * cold `debrief` subprocess recompiles them from source (≈2-3 s, ~100 MB
 * RSS). Non-fatal by design: the runtime `PYTHONPYCACHEPREFIX` overlay still
 * keeps the compiler out of the hot path.
 */
async function compileVenv(
  dataDir: string,
  venvPython: string,
  env: Record<string, string | undefined>,
  exec: typeof execQuiet,
): Promise<void> {
  for (const lib of [join(dataDir, 'venv', 'lib'), join(dataDir, 'venv', 'Lib')]) {
    if (!existsSync(lib)) continue
    try {
      await exec(venvPython, ['-m', 'compileall', '-q', '-j', '0', lib], { env, timeoutMs: 300000 })
    } catch {
      /* best effort — a failed compile only costs cold-start time */
    }
  }
}

export type BootstrapTool =
  | { ok: true; tool: 'uv'; toolPath: string }
  | { ok: true; tool: 'python'; toolPath: string; version: string }
  | { ok: false; reason: string }

/** Prefer uv; fall back to python3.13/3.12/3.11 with a version check. */
export async function detectBootstrapTool(
  env: Record<string, string | undefined>,
  exec = execQuiet,
): Promise<BootstrapTool> {
  const uv = await exec('uv', ['--version'], { env, timeoutMs: 10000 })
  if (uv.code === 0 && uv.error === undefined) return { ok: true, tool: 'uv', toolPath: 'uv' }
  for (const name of ['python3.13', 'python3.12', 'python3.11'] as const) {
    const probe = await exec(name, ['-c', 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'], {
      env,
      timeoutMs: 10000,
    })
    if (probe.code === 0 && probe.error === undefined) {
      const version = probe.stdout.trim()
      const parts = version.split('.').map(Number)
      const major = parts[0] ?? 0
      const minor = parts[1] ?? 0
      if (major === 3 && minor >= 11) return { ok: true, tool: 'python', toolPath: name, version }
    }
  }
  return { ok: false, reason: 'no python' }
}

interface LockGuard {
  acquired: boolean
  release: () => void
}

const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))

/** Directory lock: serializes bootstraps; a wait beyond LOCK_WAIT_MS times out. */
export async function acquireBootstrapLock(dataDir: string, now = Date.now): Promise<LockGuard> {
  const lockDir = join(dataDir, '.bootstrap-lock')
  try {
    mkdirSync(dataDir, { recursive: true })
  } catch {
    /* parent already exists or is unwritable; the lock attempt reports it */
  }
  const release = (): void => {
    try {
      rmSync(lockDir, { recursive: true, force: true })
    } catch {
      /* already gone */
    }
  }
  const deadline = now() + LOCK_WAIT_MS
  for (;;) {
    try {
      mkdirSync(lockDir)
      return { acquired: true, release }
    } catch {
      // fall through to the wait branch
    }
    // Stale lock (older than LOCK_STALE_MS) gets stolen.
    try {
      const stat = statSync(lockDir)
      if (now() - stat.mtimeMs > LOCK_STALE_MS) {
        release()
        continue
      }
    } catch {
      continue
    }
    if (now() >= deadline) return { acquired: false, release }
    await sleep(200)
  }
}

const NO_PYTHON_MESSAGE =
  '未找到 uv 或 Python ≥3.11（python3.11/python3.12/python3.13）。请安装其一后重试：macOS/Linux 推荐 `uv`（curl -LsSf https://astral.sh/uv/install.sh | sh），或 `brew install python@3.11`。'

export interface EnsureResult {
  ready: boolean
  mode: 'external' | 'managed'
  cliPath: string
  prefixArgs: readonly string[]
  dataDir?: string
  dbUrl?: string
  wheel?: string
  errorCode?: string
  error?: string
}

const inFlight = new Map<string, Promise<EnsureResult>>()

/**
 * Resolve the kernel launcher for one call. External mode is a no-op; managed
 * mode reuses a marker-verified venv (zero overhead) or bootstraps once.
 */
export async function ensureKernel(
  config: KernelConfigLike,
  env: Record<string, string | undefined> = process.env,
  exec = execQuiet,
  wheelDir?: string,
): Promise<EnsureResult> {
  const resolved = resolveKernelMode(config)
  if (resolved.mode === 'external') {
    return { ready: true, mode: 'external', cliPath: resolved.cliPath, prefixArgs: [] }
  }
  const dataDir = runtimeDataDir(config, env)
  const pending = inFlight.get(dataDir)
  if (pending) return pending

  const promise = bootstrapManaged(config, dataDir, env, exec, wheelDir ?? wheelsDir(env))
  inFlight.set(dataDir, promise)
  promise.finally(() => {
    if (inFlight.get(dataDir) === promise) inFlight.delete(dataDir)
  })
  return promise
}

async function bootstrapManaged(
  config: KernelConfigLike,
  dataDir: string,
  env: Record<string, string | undefined>,
  exec: typeof execQuiet,
  wheelDir: string,
): Promise<EnsureResult> {
  const wheel = findKernelWheel(wheelDir)
  const marker = readMarker(dataDir)
  const wheelPath = wheel === undefined ? undefined : join(wheelDir, wheel)
  const fingerprint = wheelPath === undefined ? undefined : wheelFingerprint(wheelPath)
  const venvDebrief = join(venvBin(dataDir), process.platform === 'win32' ? 'debrief.exe' : 'debrief')
  const venvPython = join(venvBin(dataDir), process.platform === 'win32' ? 'python.exe' : 'python')

  // Fast path: marker matches the bundled wheel and the launcher exists.
  if (wheel !== undefined && fingerprint !== undefined && marker !== undefined && marker.wheel === fingerprint) {
    if (existsSync(marker.cliPath)) {
      return {
        ready: true,
        mode: 'managed',
        cliPath: marker.cliPath,
        prefixArgs: marker.prefixArgs,
        dataDir,
        dbUrl: managedDbUrl(dataDir),
        wheel,
      }
    }
  }

  const lock = await acquireBootstrapLock(dataDir)
  if (!lock.acquired) {
    return {
      ready: false,
      mode: 'managed',
      cliPath: venvDebrief,
      prefixArgs: [],
      dataDir,
      wheel,
      errorCode: 'DEBRIEF_KERNEL_INITIALIZING',
      error: '内核正在自举（另一进程初始化中），请稍后重试；或运行 /debrief-setup 查看状态。',
    }
  }
  try {
    if (wheel === undefined || wheelPath === undefined || fingerprint === undefined) {
      return {
        ready: false,
        mode: 'managed',
        cliPath: venvDebrief,
        prefixArgs: [],
        dataDir,
        errorCode: 'DEBRIEF_NO_WHEEL',
        error: `未找到内核轮子（kernel/wheels/ 缺少 ${KERNEL_WHEEL_PREFIX}*.whl）。请更新插件，或将 Config.kernelMode 设为 external 并配置 cliPath。`,
      }
    }

    // Rebuild on wheel mismatch.
    if (marker !== undefined && marker.wheel !== fingerprint) {
      try {
        rmSync(join(dataDir, 'venv'), { recursive: true, force: true })
      } catch {
        /* best effort */
      }
    }

    const tool = await detectBootstrapTool(env, exec)
    if (!tool.ok) {
      return {
        ready: false,
        mode: 'managed',
        cliPath: venvDebrief,
        prefixArgs: [],
        dataDir,
        wheel,
        errorCode: 'DEBRIEF_NO_PYTHON',
        error: NO_PYTHON_MESSAGE,
      }
    }

    let installError: string | undefined
    if (tool.tool === 'uv') {
      const venv = await exec('uv', ['venv', '--python', '3.11', join(dataDir, 'venv')], { env, timeoutMs: 180000 })
      if (venv.code !== 0) installError = venv.error ?? venv.stderr
      if (installError === undefined) {
        // --no-cache: uv/pip caches key by filename+version, so a
        // same-version wheel override would otherwise hit a stale cache.
        const install = await exec(
          'uv',
          [
            'pip',
            'install',
            '--no-cache',
            // Python >=3.12: write .pyc at install time. Without it a read-only
            // venv makes every cold `debrief` call recompile the collectors.
            '--compile',
            '--python',
            venvPython,
            '--no-index',
            '--find-links',
            wheelDir,
            KERNEL_PACKAGE,
          ],
          { env, timeoutMs: 180000 },
        )
        if (install.code !== 0) installError = install.error ?? install.stderr
      }
    } else {
      const venv = await exec(tool.toolPath, ['-m', 'venv', join(dataDir, 'venv')], { env, timeoutMs: 180000 })
      if (venv.code !== 0) installError = venv.error ?? venv.stderr
      if (installError === undefined) {
        const install = await exec(
          venvPython,
          ['-m', 'pip', 'install', '--no-cache-dir', '--no-index', '--find-links', wheelDir, KERNEL_PACKAGE],
          {
            env,
            timeoutMs: 180000,
          },
        )
        if (install.code !== 0) installError = install.error ?? install.stderr
      }
    }

    if (installError !== undefined) {
      return {
        ready: false,
        mode: 'managed',
        cliPath: venvDebrief,
        prefixArgs: [],
        dataDir,
        wheel,
        errorCode: 'DEBRIEF_BOOTSTRAP',
        error: `内核自举失败：${installError.slice(0, 400)}。可运行 /debrief-setup 查看状态，或删除 ${dataDir} 后重试。`,
      }
    }

    // Content self-check: the installed package must expose both the CLI
    // modules and the adapters module — guards against stale cached wheels.
    const selfCheck = await exec(venvPython, ['-c', 'import adapters, debrief'], { env, timeoutMs: 60000 })
    if (selfCheck.code !== 0) {
      return {
        ready: false,
        mode: 'managed',
        cliPath: venvDebrief,
        prefixArgs: [],
        dataDir,
        wheel,
        errorCode: 'DEBRIEF_BOOTSTRAP_INCOMPLETE',
        error: `内核自举不完整：安装内容缺少 adapters/debrief 模块（可能命中了旧缓存）。请删除 ${dataDir} 后重试，或运行 /debrief-setup 查看状态。${selfCheck.stderr.slice(0, 200)}`,
      }
    }

    // Optional collectors extra (networked, explicitly opt-in, non-fatal).
    if (config.withCollectors === true) {
      console.warn('[dsh-debrief] withCollectors: 正在从 PyPI 联网安装 collectors extra（可采集依赖）…')
      const collectors =
        tool.tool === 'uv'
          ? await exec(
              'uv',
              ['pip', 'install', '--python', venvPython, '--find-links', wheelDir, `${KERNEL_PACKAGE}[collectors]`],
              { env, timeoutMs: 300000 },
            )
          : await exec(
              venvPython,
              ['-m', 'pip', 'install', '--find-links', wheelDir, `${KERNEL_PACKAGE}[collectors]`],
              { env, timeoutMs: 300000 },
            )
      if (collectors.code !== 0) {
        console.warn('[dsh-debrief] collectors 安装失败（不影响核心读写命令）：', collectors.error ?? collectors.stderr)
      }
    }

    // Bytecode is written last so the collectors extra is covered too.
    await compileVenv(dataDir, venvPython, env, exec)

    const cliPath = existsSync(venvDebrief) ? venvDebrief : venvPython
    const prefixArgs = existsSync(venvDebrief) ? [] : ['-m', 'debrief.cli']
    try {
      mkdirSync(dataDir, { recursive: true })
      writeFileSync(
        markerPath(dataDir),
        JSON.stringify({
          schemaVersion: MARKER_SCHEMA,
          wheel: fingerprint,
          cliPath,
          prefixArgs,
          installedAt: new Date().toISOString(),
        }),
      )
    } catch {
      /* marker is an optimization; a missing marker only re-runs bootstrap */
    }
    return { ready: true, mode: 'managed', cliPath, prefixArgs, dataDir, dbUrl: managedDbUrl(dataDir), wheel }
  } finally {
    lock.release()
  }
}

/** Human-readable kernel status for /debrief-setup output. */
export async function describeKernel(
  config: KernelConfigLike,
  env: Record<string, string | undefined> = process.env,
): Promise<EnsureResult> {
  return ensureKernel(config, env)
}
