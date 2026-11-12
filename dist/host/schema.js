/**
 * Dependency-free schema validation (the plugin's "zod stand-in").
 *
 * The package ships with zero runtime dependencies and its devDependencies are
 * limited to typescript/vitest/eslint/prettier, so no zod. This module covers
 * the validation the plugin needs — write-tool payloads on the Host and tool
 * result render models on the Client (the Client keeps its own copy because
 * the browser entry is a single self-contained file).
 */
export const s = () => ({ type: 'string' });
export const n = () => ({ type: 'number' });
export const i = () => ({ type: 'integer' });
export const b = () => ({ type: 'boolean' });
export const arr = (items) => ({ type: 'array', items });
export const obj = (properties, required = []) => ({
    type: 'object',
    properties,
    required,
});
export const opt = (shape) => ({ ...shape, optional: true });
export function validate(shape, value, path = '$') {
    if ((value === undefined || value === null) && shape.optional) {
        return { ok: true, value: undefined };
    }
    if (value === undefined || value === null) {
        return { ok: false, path, reason: 'required value is missing' };
    }
    switch (shape.type) {
        case 'string':
            return typeof value === 'string'
                ? { ok: true, value }
                : { ok: false, path, reason: `expected string, got ${typeof value}` };
        case 'number':
            return typeof value === 'number' && Number.isFinite(value)
                ? { ok: true, value }
                : { ok: false, path, reason: `expected finite number, got ${typeof value}` };
        case 'integer':
            return typeof value === 'number' && Number.isInteger(value)
                ? { ok: true, value }
                : { ok: false, path, reason: `expected integer, got ${typeof value}` };
        case 'boolean':
            return typeof value === 'boolean'
                ? { ok: true, value }
                : { ok: false, path, reason: `expected boolean, got ${typeof value}` };
        case 'array': {
            if (!Array.isArray(value))
                return { ok: false, path, reason: `expected array, got ${typeof value}` };
            const items = [];
            for (let index = 0; index < value.length; index += 1) {
                const item = value[index];
                const result = validate(shape.items, item, `${path}[${index}]`);
                if (!result.ok)
                    return result;
                items.push(result.value);
            }
            return { ok: true, value: items };
        }
        case 'object': {
            if (typeof value !== 'object' || Array.isArray(value)) {
                return { ok: false, path, reason: `expected object, got ${Array.isArray(value) ? 'array' : typeof value}` };
            }
            const record = value;
            for (const key of shape.required ?? []) {
                const result = validate(shape.properties[key] ?? s(), record[key], `${path}.${key}`);
                if (!result.ok)
                    return result;
            }
            const out = {};
            for (const [key, member] of Object.entries(shape.properties)) {
                const result = validate(member, record[key], `${path}.${key}`);
                if (!result.ok)
                    return result;
                if (result.value !== undefined)
                    out[key] = result.value;
            }
            return { ok: true, value: out };
        }
    }
}
