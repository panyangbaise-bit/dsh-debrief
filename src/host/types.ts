/**
 * Minimal structural contracts for the Harness services this plugin consumes.
 *
 * These types mirror the installed DSH 0.2.2-rc.1 contracts (verified via
 * cordis_inspect_query against the running Host). The plugin is intentionally
 * runtime-dependency-free, so the contracts are re-declared here instead of
 * imported from `@deepseek-ai/dsh-*` packages.
 */

export interface ContentBlock {
  type: string
  text?: string
}

/** Compiled raw-schema property node (what `defineTool` produces). */
export interface JsonNode {
  type?: 'object' | 'array' | 'string' | 'number' | 'integer' | 'boolean' | 'null'
  description?: string
  properties?: Record<string, JsonNode>
  required?: string[]
  items?: JsonNode
  enum?: (string | number | boolean | null)[]
  default?: unknown
}

export interface ToolRunContext {
  signal: AbortSignal
  agent?: { id: string }
}

export interface ToolDefinition {
  name: string
  description: string
  parameters: Record<string, unknown>
  output: {
    schema: JsonNode
    render(args: unknown, value: unknown): ContentBlock[]
  }
  execute(args: unknown, exec: ToolRunContext): Promise<unknown>
}

export interface SkillRegistrationInput {
  name: string
  description: string
  whenToUse?: string
  content: string
  invocation?: { modelInvocable: boolean; userInvocable: boolean }
  source?: string
}

export interface CommandInvocation {
  agent: { id: string }
  rawInput: string
  signal: AbortSignal
}

export type CommandResult = { kind: 'success'; text?: string } | { kind: 'error'; text: string }

export interface CommandDefinition {
  name: string
  description: string
  handler: (invocation: CommandInvocation) => CommandResult | Promise<CommandResult>
}

export interface SchedulePreset {
  title: string
  prompt: string
  rrule: string
  target: 'new_once'
  order?: number
}

export interface ScheduleCreateRequest {
  title: string
  prompt: string
  timing: { kind: 'rrule'; rrule: string }
  target: { kind: 'new_once' }
}

export interface ScheduleCatalogEntry {
  id: string
  title: string
  prompt: string
  scheduledAt?: string
  status?: string
}

export interface ScheduleListResult {
  items: ScheduleCatalogEntry[]
}

export interface ConnectionFetchRoute {
  path: string
  methods: readonly ('GET' | 'HEAD' | 'POST')[]
  requestBody: 'buffered' | 'streaming'
  fetch: (request: Request) => Promise<Response>
}

export interface ScheduleService {
  list(request: { limit?: number; offset?: number }): Promise<ScheduleListResult>
  create(request: ScheduleCreateRequest): Promise<ScheduleCatalogEntry>
}

/** tools/pre-execute waterfall decision vocabulary (inspected contract). */
export type PreToolDecision =
  | { kind: 'allow' }
  | { kind: 'deny'; reason: string }
  | { kind: 'cancel' }
  | { kind: 'ask'; reason?: string; displayReason?: { en: string; [locale: string]: string } }

export interface ToolExecutionLike {
  name: string
  arguments?: unknown
  agent?: { id: string }
}

/**
 * Services consumed through the plugin's `inject` declaration
 * (['tools', 'commands', 'schedule', 'connection', 'skills']). The inspect
 * contracts document the hard-dependency form `inject: [key]` → `ctx[key]`;
 * the optional `ctx.get(key)` form proved unreachable for commands/schedule/
 * connection on the server profile, which silently disabled the setup command
 * and the dashboard route.
 */
export interface DebriefContext {
  effect(setup: () => void | (() => void), label?: string): void
  on(name: string, listener: (...args: never[]) => unknown, prepend?: boolean): () => void
  tools: {
    register(definition: ToolDefinition): () => void
  }
  skills: {
    register(skill: SkillRegistrationInput): () => void
  }
  commands: {
    register(definition: CommandDefinition): () => void
  }
  schedule: ScheduleService
  connection: {
    fetch: {
      register(route: ConnectionFetchRoute): () => Promise<void>
    }
  }
}
