/**
 * dsh-debrief — Host half.
 *
 * All model work belongs to the DSH agent. This plugin bridges the model-free
 * debrief kernel over a local JSON CLI: each tool runs `debrief <command> --json`
 * and returns the canonical envelope. The Client half renders the conversation
 * cards and the Dashboard page.
 *
 * The package is runtime-dependency-free by design (local directory installs
 * are linked, so module resolution does not reach the profile's node_modules):
 * tool definitions are written in the registry's compiled raw-schema form.
 */
export { apply } from './host/index.js';
export { inject } from './host/index.js';
