/**
 * v2 edit routes (Client-callable Host entry points).
 *
 * Both are registered through `ctx.connection.fetch` — the authenticated
 * exact-route seam (signed browser cookie, Host/Origin fence, owner-only
 * Peer) — exactly like the dashboard route. The UI is the second caller of
 * the single Host operation `runEdit`; the agent tools are the first.
 */
import { runCli } from './cli.js';
import { runEdit, validateEditPayload } from './edits.js';
export const INSTRUMENTS_PATH = '/api/debrief/instruments';
export const MUTATE_PATH = '/api/debrief/mutate';
const MARKETS = new Set(['us', 'cn', 'hk', 'crypto']);
function jsonResponse(body, status) {
    return new Response(JSON.stringify(body), {
        status,
        headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' },
    });
}
const badRequest = (message) => jsonResponse({ ok: false, schemaVersion: 1, error: { code: 'DEBRIEF_ARGS', message } }, 400);
export function registerEditRoutes(ctx, config) {
    const instruments = {
        path: INSTRUMENTS_PATH,
        methods: ['GET', 'HEAD'],
        requestBody: 'buffered',
        async fetch(request) {
            const url = new URL(request.url);
            const market = (url.searchParams.get('market') ?? '').toLowerCase();
            const query = (url.searchParams.get('query') ?? '').trim();
            if (!MARKETS.has(market))
                return badRequest('market must be one of us, cn, hk, crypto');
            if (query === '')
                return badRequest('query must not be empty');
            const envelope = await runCli(config, ['instruments', 'search', '--market', market, '--query', query]);
            return jsonResponse(envelope, envelope.ok ? 200 : 502);
        },
    };
    const mutate = {
        path: MUTATE_PATH,
        methods: ['POST'],
        requestBody: 'buffered',
        async fetch(request) {
            let body;
            try {
                body = (await request.json());
            }
            catch {
                return badRequest('body must be JSON');
            }
            const entity = body.entity === 'holding' || body.entity === 'watchlist' ? body.entity : undefined;
            const action = body.action === 'add' || body.action === 'update' || body.action === 'remove' ? body.action : undefined;
            if (entity === undefined || action === undefined) {
                return badRequest('entity (holding|watchlist) and action (add|update|remove) are required');
            }
            const payload = (body.payload && typeof body.payload === 'object' ? body.payload : {});
            const checked = validateEditPayload(entity, action, payload);
            if (!checked.ok)
                return badRequest(checked.error.message);
            const envelope = await runEdit(config, entity, action, payload);
            return jsonResponse(envelope, envelope.ok ? 200 : envelope.error.code === 'DEBRIEF_CONFLICT' ? 409 : 502);
        },
    };
    const disposers = [];
    for (const route of [instruments, mutate]) {
        try {
            disposers.push(ctx.connection.fetch.register(route));
        }
        catch (error) {
            console.warn(`[dsh-debrief] route ${route.path} registration failed:`, error instanceof Error ? error.message : error);
        }
    }
    return () => {
        for (const dispose of disposers)
            void dispose();
    };
}
