/**
 * Register the five scheduled debrief skills through ctx.skills.register.
 *
 * Skill bodies are authored as bilingual markdown files in `skills/*.md` next
 * to the package root and are read once at activation. Names are kebab-case;
 * the workflow (tool order, IRON constraints, output format) follows the
 * design document §2.5.
 */
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
const SKILLS_DIR = new URL('../../skills/', import.meta.url);
export function loadSkills() {
    const skills = [];
    let files;
    try {
        files = readdirSync(fileURLToPath(SKILLS_DIR))
            .filter((name) => name.endsWith('.md'))
            .sort();
    }
    catch (error) {
        console.warn('[dsh-debrief] cannot read skills directory:', error instanceof Error ? error.message : error);
        return skills;
    }
    for (const file of files) {
        try {
            const content = readFileSync(fileURLToPath(new URL(`../../skills/${file}`, import.meta.url)), 'utf8');
            skills.push(parseSkillMarkdown(content, file));
        }
        catch (error) {
            console.warn(`[dsh-debrief] skipping skill ${file}:`, error instanceof Error ? error.message : error);
        }
    }
    return skills;
}
const KEBAB = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
/** Front-matter-ish header: `name:`, `description:`, `whenToUse:` lines, then the body. */
export function parseSkillMarkdown(content, fileName) {
    const lines = content.split('\n');
    const header = {};
    let bodyStart = 0;
    for (let index = 0; index < lines.length; index += 1) {
        const match = /^(name|description|whenToUse):\s*(.+)$/.exec(lines[index] ?? '');
        if (match) {
            header[match[1] ?? ''] = (match[2] ?? '').trim();
            bodyStart = index + 1;
            continue;
        }
        if ((lines[index] ?? '').trim() === '')
            continue;
        break;
    }
    const name = header.name ?? fileName.replace(/\.md$/, '');
    if (!KEBAB.test(name)) {
        throw new Error(`skill name ${JSON.stringify(name)} is not kebab-case`);
    }
    const body = lines.slice(bodyStart).join('\n').trim();
    if (body === '')
        throw new Error(`skill ${name} has an empty body`);
    return {
        name,
        description: header.description ?? name,
        whenToUse: header.whenToUse,
        content: body,
        invocation: { modelInvocable: true, userInvocable: false },
        source: 'runtime',
    };
}
export function registerSkills(ctx, skills) {
    const disposers = [];
    for (const skill of skills) {
        try {
            disposers.push(ctx.skills.register(skill));
        }
        catch (error) {
            console.warn(`[dsh-debrief] skill ${skill.name} registration failed:`, error instanceof Error ? error.message : error);
        }
    }
    return () => disposers.forEach((dispose) => dispose());
}
