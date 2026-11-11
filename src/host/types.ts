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

export interface DebriefContext {
  get(name: string): unknown | undefined
  effect(setup: () => void | (() => void), label?: string): void
  tools: {
    register(definition: ToolDefinition): () => void
  }
}
