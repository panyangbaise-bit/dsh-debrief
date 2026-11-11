import { describe, expect, it } from 'vitest'
import { loadSkills, parseSkillMarkdown } from '../src/host/skills'

describe('skill loading', () => {
  const skills = loadSkills()

  it('loads the five scheduled skills with kebab-case names', () => {
    expect(skills.map((skill) => skill.name)).toEqual([
      'debrief-after-market',
      'debrief-compact',
      'debrief-monthly',
      'debrief-news',
      'debrief-weekly',
    ])
  })

  it('marks every skill model-invocable but not user-invocable', () => {
    for (const skill of skills) {
      expect(skill.invocation).toEqual({ modelInvocable: true, userInvocable: false })
      expect(skill.source).toBe('runtime')
    }
  })

  it('carries a bilingual body with IRON constraints', () => {
    for (const skill of skills) {
      expect(skill.content.length).toBeGreaterThan(400)
      expect(skill.content).toContain('IRON')
      expect(skill.content).toMatch(/[\u4e00-\u9fff]/) // Chinese content
      expect(skill.content).toMatch(/[A-Za-z]{3,}/) // English content
    }
  })

  it('documents the write-tool workflow in after-market and compact skills', () => {
    const afterMarket = skills.find((skill) => skill.name === 'debrief-after-market')!
    expect(afterMarket.content).toContain('debrief_report_create')
    expect(afterMarket.content).toContain('debrief_analyze')
    const compact = skills.find((skill) => skill.name === 'debrief-compact')!
    expect(compact.content).toContain('debrief_memory_compact_write')
    expect(compact.content).toContain('debrief_memory_add')
  })
})

describe('skill markdown parsing', () => {
  const body = '# 标题\n\n正文内容。'

  it('parses the header and body', () => {
    const skill = parseSkillMarkdown('name: my-skill\ndescription: 描述\nwhenToUse: 触发条件\n\n' + body, 'my-skill.md')
    expect(skill.name).toBe('my-skill')
    expect(skill.description).toBe('描述')
    expect(skill.whenToUse).toBe('触发条件')
    expect(skill.content).toBe(body)
  })

  it('rejects a non-kebab-case name', () => {
    expect(() => parseSkillMarkdown('name: MySkill\n\n' + body, 'x.md')).toThrow(/kebab-case/)
  })

  it('rejects an empty body', () => {
    expect(() => parseSkillMarkdown('name: my-skill\n\n', 'x.md')).toThrow(/empty body/)
  })
})
