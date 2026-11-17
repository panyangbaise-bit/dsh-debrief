/**
 * Minimal Node.js ambient declarations.
 *
 * The package's devDependencies are intentionally limited to
 * typescript/vitest/eslint/prettier, so `@types/node` is not installed.
 * This file declares only the Node surface the Host half actually uses.
 */

declare namespace NodeJS {
  interface ProcessEnv {
    DEBRIEF_CLI_PATH?: string
    [key: string]: string | undefined
  }

  interface ErrnoException extends Error {
    code?: string
  }
}

declare const process: {
  env: NodeJS.ProcessEnv
  argv: string[]
  platform: string
  stdin: {
    setEncoding(encoding: string): void
    on(event: string, listener: (...args: never[]) => void): unknown
  }
  exit(code?: number): never
  stdout: { write(chunk: string): void }
  stderr: { write(chunk: string): void }
}

interface Buffer {
  length: number
  toString(encoding?: string): string
  slice(start?: number, end?: number): Buffer
}

interface BufferConstructor {
  concat(list: readonly Buffer[], totalLength?: number): Buffer
  isBuffer(value: unknown): value is Buffer
}

declare const Buffer: BufferConstructor

declare module 'node:child_process' {
  export interface ChildProcess {
    stdout: { on(event: string, listener: (chunk: Buffer) => void): void }
    stderr: { on(event: string, listener: (chunk: Buffer) => void): void }
    stdin: { write(chunk: string): void; end(): void }
    on(event: string, listener: (arg: any) => void): void
    kill(signal?: string): boolean
  }

  export function spawn(command: string, args: readonly string[], options?: unknown): ChildProcess
}

declare module 'node:fs' {
  export function readFileSync(path: string, encoding: 'utf8'): string
  export function readdirSync(path: string): string[]
  export function existsSync(path: string): boolean
  export function mkdirSync(path: string, options?: unknown): void
  export function rmSync(path: string, options?: unknown): void
  export function writeFileSync(path: string, data: string): void
  export function statSync(path: string): { size: number; mtimeMs: number }
}

declare module 'node:path' {
  export function join(...segments: string[]): string
  export function basename(path: string): string
  export function dirname(path: string): string
}

declare module 'node:os' {
  export function homedir(): string
  export function tmpdir(): string
}

declare module 'node:url' {
  export function fileURLToPath(url: URL | string): string
}

/**
 * Plugin-owned SessionReferenceSource label for profile-page delivery into the
 * currently open session. The package ships zero runtime dsh dependencies, so
 * the merge target module is declared ambiently here; at runtime the label is
 * a plain string key in the sessions-service retain counter map.
 */
declare module '@deepseek-ai/dsh-api-session-controller/client' {
  interface SessionReferenceSourceMap {
    /** Investment memory profile page: ask/update/regenerate delivery. */
    debriefProfilePage: unknown
  }
}
