#!/usr/bin/env node
/**
 * Postbuild step for the Client half.
 *
 * The Web Host serves `dist/client.js` and wraps the file's content inside a
 * `factory(require)` function body (the same shape official client bundles
 * ship), so the artifact must contain NO top-level `export`/`import`
 * statements — they are a SyntaxError inside a function body. The TypeScript
 * source keeps its `export`s (the vitest suite imports them), and this script
 * strips them from the compiled artifact.
 *
 * The script also compiles the stripped content inside the exact wrapper
 * shape the loader uses and fails the build if anything is left over.
 */
import { readFileSync, writeFileSync } from 'node:fs'
import { fileURLToPath, pathToFileURL } from 'node:url'

const CLIENT_FILE = fileURLToPath(new URL('../dist/client.js', import.meta.url))

/** Remove top-level `export <declaration>` prefixes; nested lines stay untouched. */
export function stripExports(source) {
  return source
    .replace(/\r\n/g, '\n')
    .split('\n')
    .map((line) => line.replace(/^export\s+(?=const\b|let\b|var\b|function\b|class\b|async\b|\{)/, ''))
    .join('\n')
}

/** True when the source still carries top-level module syntax. */
export function hasTopLevelModuleSyntax(source) {
  return /^(export|import)\s/m.test(source)
}

/** The exact wrapper shape the host loader executes plugin client code in. */
export function loaderWrapper(content) {
  return `(require) => {\nvar module={exports:{}};\nvar exports=module.exports;\n${content}\n}`
}

const isMain = process.argv[1] !== undefined && import.meta.url === pathToFileURL(process.argv[1]).href

if (isMain) {
  const source = readFileSync(CLIENT_FILE, 'utf8')
  const stripped = stripExports(source)
  if (hasTopLevelModuleSyntax(stripped)) {
    console.error('[strip-client-exports] FAIL: dist/client.js still has top-level export/import statements')
    process.exit(1)
  }
  try {
    // Compile-only check; the Function constructor parses but never runs the body.
    new Function(loaderWrapper(stripped))
  } catch (error) {
    console.error('[strip-client-exports] FAIL: wrapper compile check:', error instanceof Error ? error.message : error)
    process.exit(1)
  }
  if (stripped !== source) {
    writeFileSync(CLIENT_FILE, stripped)
  }
  console.log('[strip-client-exports] dist/client.js: top-level exports stripped; loader-wrapper compile OK')
}
