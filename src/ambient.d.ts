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
}

declare module 'node:url' {
  export function fileURLToPath(url: URL | string): string
}
