import { describe, expect, it } from 'vitest'

import type { BookVolume } from '@/lib/api'
import { groupLabel, tocGroups } from './chapterGroups'

/** 造一个段（`volume` 默认空串 = 无名段） */
function V(v: Partial<BookVolume> & { chapters: BookVolume['chapters'] }): BookVolume {
  return { volume: '', ...v }
}

describe('groupLabel：段名的唯一真值源', () => {
  it('有名卷用卷名；无名段按 kind 叫「卷前 / 卷尾 / 正文」', () => {
    expect(groupLabel({ volume: '第一卷' })).toBe('第一卷')
    expect(groupLabel({ volume: '', kind: 'front' })).toBe('卷前')
    expect(groupLabel({ volume: '', kind: 'back' })).toBe('卷尾')
    expect(groupLabel({ volume: '' })).toBe('正文')
  })
})

describe('tocGroups：摊平 + 逐项带位置', () => {
  it('位置跨段连续计数，且只有有名卷出段头', () => {
    const g = tocGroups([
      V({ kind: 'front', chapters: [{ title: '楔子', index: 0 }] }),
      V({
        volume: '第一卷',
        chapters: [
          { title: '第一章', index: 1, num: 1 },
          { title: '第二章', index: 2, num: 2 },
        ],
      }),
      V({ kind: 'back', chapters: [{ title: '番外', index: 3 }] }),
    ])
    expect(g.map((x) => x.label)).toEqual(['卷前', '第一卷', '卷尾'])
    expect(g.map((x) => x.headered)).toEqual([false, true, false])
    expect(g.flatMap((x) => x.items.map((i) => i.pos))).toEqual([0, 1, 2, 3])
  })

  it('index 缺失的条目跳过；空的无名段不产出（第 61 期口径，别顺手改）', () => {
    const g = tocGroups([
      V({
        volume: '第一卷',
        chapters: [{ title: '第一章', index: 0, num: 1 }, { title: '无序号页' }],
      }),
      V({ chapters: [] }),
    ])
    expect(g).toHaveLength(1)
    expect(g[0].items.map((i) => i.title)).toEqual(['第一章'])
  })

  it('段 key 唯一且稳定：背靠背的两个无名段不会互相串折叠', () => {
    const g = tocGroups([
      V({ chapters: [{ title: '甲', index: 0, num: 1 }] }),
      V({ volume: '第一卷', chapters: [{ title: '乙', index: 1, num: 1 }] }),
      V({ chapters: [{ title: '丙', index: 2, num: 1 }] }),
    ])
    expect(g.map((x) => x.label)).toEqual(['正文', '第一卷', '正文'])
    expect(new Set(g.map((x) => x.key)).size).toBe(3)
  })

  it('无编号条目不带序号（num 缺省原样透传，界面据此不渲染序号）', () => {
    const g = tocGroups([V({ kind: 'front', chapters: [{ title: '楔子', index: 0 }] })])
    expect(g[0].items[0].num).toBeUndefined()
  })

  it('chapters 还没回来（undefined）时给空数组，不抛', () => {
    expect(tocGroups(undefined)).toEqual([])
  })
})
