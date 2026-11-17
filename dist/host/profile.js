/**
 * Investment memory profile: the Client-callable route (GET/POST) plus the
 * shared write-payload validation used by both the route and the
 * `debrief_profile_write` tool (UserActions pattern — one operation, two
 * callers, see edits.ts).
 *
 * Kernel contract (plan/kernel.md + plan/README.md arbitration):
 * - `debrief profile get --json` never answers DEBRIEF_NOT_FOUND; an empty
 *   store yields version=0 with six empty sections.
 * - `debrief profile write --by <user|agent> --json` reads the payload from
 *   stdin. Per plan/README.md §3 the kernel derives per-section `updatedBy`
 *   from the caller (the `--by` flag), so the payload carries NO updatedBy —
 *   the route writes as `user` (inline edits) and the tool as `agent`.
 * - DEBRIEF_CONFLICT (expectedVersion mismatch) maps to HTTP 409;
 *   DEBRIEF_ARGS / DEBRIEF_VALIDATION / DEBRIEF_USAGE map to 400; everything
 *   else is a 502 passthrough of the canonical envelope.
 *
 * Latency design (dashboard.ts pattern, minus background quote refresh):
 * single-flight + short payload cache (default 5 s) + stale-while-error.
 */
import { runCli } from './cli.js';
import { arr, b, i, obj, opt, s, validate } from './schema.js';
export const PROFILE_PATH = '/api/debrief/profile';
/** Section key whitelist — fixed order, three-way anchor with kernel.md §2.1 and the client locale keys. */
export const PROFILE_SECTION_KEYS = [
    'portfolio',
    'habits',
    'discipline',
    'risk',
    'advice',
    'decisions',
];
const DEFAULT_PROFILE_CACHE_MS = 5000;
function jsonResponseText(body, status) {
    return new Response(body, {
        status,
        headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' },
    });
}
function jsonResponse(body, status) {
    return jsonResponseText(JSON.stringify(body), status);
}
const badRequest = (message) => jsonResponse({ ok: false, schemaVersion: 1, error: { code: 'DEBRIEF_ARGS', message } }, 400);
// ---- shared write-payload shapes (route + tool) ------------------------------
/** A written section: key + full new content. `updatedBy` is caller-derived kernel-side, never carried. */
const sectionWriteShape = obj({ key: s(), content: s() }, ['key', 'content']);
/** Profile evidence refs are `{docId:int}` only — no quote (unlike compact-write). */
const profileEvidenceRefShape = obj({ docId: i() }, ['docId']);
export const profileWriteShape = obj({
    sections: opt(arr(sectionWriteShape)),
    evidenceRefs: opt(arr(profileEvidenceRefShape)),
    expectedVersion: opt(i()),
    protectUserSections: opt(b()),
}, []);
/** Cross-field rules the shape cannot express (at-least-one, key whitelist). */
export function checkProfileWriteArgs(args) {
    const hasSections = Array.isArray(args.sections) && args.sections.length > 0;
    const hasRefs = Array.isArray(args.evidenceRefs) && args.evidenceRefs.length > 0;
    if (!hasSections && !hasRefs)
        return 'at least one of sections or evidenceRefs is required';
    for (const item of args.sections ?? []) {
        if (!PROFILE_SECTION_KEYS.includes(String(item.key))) {
            return `sections key must be one of ${PROFILE_SECTION_KEYS.join('/')}`;
        }
    }
    return undefined;
}
/**
 * Build the kernel stdin JSON with explicit field remapping: the plugin's
 * validator silently drops unknown fields (schema.ts), so the builder is the
 * real anti-smuggling line — sections shrink to {key, content}, evidence refs
 * shrink to {docId}, and only the four declared top-level fields can pass.
 */
export function profileWritePayload(args) {
    return JSON.stringify({
        ...(Array.isArray(args.sections) && args.sections.length > 0
            ? {
                sections: args.sections.map((item) => ({
                    key: item.key,
                    content: item.content,
                })),
            }
            : {}),
        ...(Array.isArray(args.evidenceRefs)
            ? {
                evidenceRefs: args.evidenceRefs.map((ref) => ({ docId: ref.docId })),
            }
            : {}),
        ...(typeof args.expectedVersion === 'number' ? { expectedVersion: args.expectedVersion } : {}),
        ...(args.protectUserSections === true ? { protectUserSections: true } : {}),
    });
}
export function validateProfileWritePayload(args) {
    const result = validate(profileWriteShape, args);
    if (!result.ok) {
        return { ok: false, error: { code: 'DEBRIEF_ARGS', message: `invalid payload: ${result.path} ${result.reason}` } };
    }
    const conditional = checkProfileWriteArgs(args);
    if (conditional !== undefined)
        return { ok: false, error: { code: 'DEBRIEF_ARGS', message: conditional } };
    return { ok: true, stdin: profileWritePayload(args) };
}
// ---- route -------------------------------------------------------------------
function mapProfileErrorStatus(code) {
    if (code === 'DEBRIEF_CONFLICT')
        return 409;
    if (code === 'DEBRIEF_ARGS' || code === 'DEBRIEF_VALIDATION' || code === 'DEBRIEF_USAGE')
        return 400;
    return 502;
}
export function registerProfileRoute(ctx, config, deps = {}) {
    const run = deps.runCli ?? ((args, options) => runCli(config, args, options));
    const now = deps.now ?? Date.now;
    const cacheMs = config.profileCacheMs ?? DEFAULT_PROFILE_CACHE_MS;
    const cacheKey = 'profile';
    const cache = new Map();
    const inflight = new Map();
    const build = async () => {
        const envelope = await run(['profile', 'get']);
        return {
            at: now(),
            body: JSON.stringify(envelope),
            status: envelope.ok ? 200 : mapProfileErrorStatus(envelope.error.code),
        };
    };
    const payloadFor = async () => {
        const cached = cache.get(cacheKey);
        if (cached !== undefined && cacheMs > 0 && now() - cached.at < cacheMs)
            return cached;
        let pending = inflight.get(cacheKey);
        if (pending === undefined) {
            pending = build().finally(() => inflight.delete(cacheKey));
            inflight.set(cacheKey, pending);
        }
        const fresh = await pending;
        if (fresh.status === 200) {
            cache.set(cacheKey, fresh);
            return fresh;
        }
        // Kernel failure: keep the last good payload rather than an error card.
        return cached ?? fresh;
    };
    const route = {
        path: PROFILE_PATH,
        methods: ['GET', 'POST'],
        requestBody: 'buffered',
        async fetch(request) {
            if (request.method === 'GET') {
                const payload = await payloadFor();
                return jsonResponseText(payload.body, payload.status);
            }
            let body;
            try {
                body = (await request.json());
            }
            catch {
                return badRequest('body must be JSON');
            }
            const checked = validateProfileWritePayload(body);
            if (!checked.ok)
                return badRequest(checked.error.message);
            const envelope = await run(['profile', 'write', '--by', 'user'], { stdin: checked.stdin });
            cache.delete(cacheKey); // POST response carries the fresh full profile; drop the stale GET payload
            return jsonResponse(envelope, envelope.ok ? 200 : mapProfileErrorStatus(envelope.error.code));
        },
    };
    let unregister;
    try {
        unregister = ctx.connection.fetch.register(route);
    }
    catch (error) {
        console.warn('[dsh-debrief] profile route registration failed:', error instanceof Error ? error.message : error);
        return () => { };
    }
    return () => void unregister();
}
