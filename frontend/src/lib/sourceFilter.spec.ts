import { describe, expect, it } from 'vitest'

import {
  filterSources,
  groupOptions,
  hasVerified,
  sourceStats,
  type SourceLike,
} from '@/lib/sourceFilter'

const L = (over: Partial<SourceLike> = {}): SourceLike => ({
  name: 'a',
  enabled: true,
  imported: false,
  supported: 'yes',
  ...over,
})

const LIST: SourceLike[] = [
  L({ name: 'a', display_name: '甲', group: '都市', enabled: true, imported: true,
      supported: 'no', verified_at: 300, verify_ok: false }),
  L({ name: 'b', display_name: '乙', group: '玄幻', enabled: false, imported: false,
      supported: 'partial', verified_at: 100, verify_ok: true }),
  L({ name: 'c', group: '玄幻', enabled: true, imported: false }),
]

describe('统计条', () => {
  it('各档计数与列表相符', () => {
    const s = sourceStats(LIST)
    expect(s.total).toBe(3)
    expect(s.enabled).toBe(2)
    expect(s.disabled).toBe(1)
    expect(s.imported).toBe(1)
    expect(s.manual).toBe(2)
    expect(s.unsupported).toBe(1)
    expect(s.partial).toBe(1)
    expect(s.usable).toBe(1)
    expect(s.neverVerified).toBe(1)
    expect(s.verifyFailed).toBe(1)
  })

  it('缺省口径与后端一致：没有台账行的源算启用/未导入/可用', () => {
    const s = sourceStats([{ name: 'x' }])
    expect([s.enabled, s.manual, s.usable]).toEqual([1, 1, 1])
  })

  it('统计数字就是筛出来的条数（界面不许自相矛盾）', () => {
    const s = sourceStats(LIST)
    expect(filterSources(LIST, { supported: 'no' }).length).toBe(s.unsupported)
    expect(filterSources(LIST, { supported: 'partial' }).length).toBe(s.partial)
    expect(filterSources(LIST, { origin: 'imported' }).length).toBe(s.imported)
    expect(filterSources(LIST, { state: 'disabled' }).length).toBe(s.disabled)
    expect(filterSources(LIST, { verified: 'never' }).length).toBe(s.neverVerified)
    expect(filterSources(LIST, { verified: 'failed' }).length).toBe(s.verifyFailed)
  })
})

describe('筛选', () => {
  it('搜索命中名称/显示名/分组', () => {
    expect(filterSources(LIST, { q: '甲' }).map((s) => s.name)).toEqual(['a'])
    expect(filterSources(LIST, { q: '玄幻' }).map((s) => s.name)).toEqual(['b', 'c'])
    expect(filterSources(LIST, { q: 'A' }).map((s) => s.name)).toEqual(['a'])
  })

  it('未验证与验证失败是两种状态', () => {
    expect(filterSources(LIST, { verified: 'never' }).map((s) => s.name)).toEqual(['c'])
    expect(filterSources(LIST, { verified: 'failed' }).map((s) => s.name)).toEqual(['a'])
    expect(filterSources(LIST, { verified: 'ok' }).map((s) => s.name)).toEqual(['b'])
  })

  it('组合筛选取交集', () => {
    const got = filterSources(LIST, { group: '玄幻', state: 'enabled' })
    expect(got.map((s) => s.name)).toEqual(['c'])
  })

  it('空查询原样返回，不改入参', () => {
    const before = [...LIST]
    expect(filterSources(LIST, {}).length).toBe(3)
    expect(LIST).toEqual(before)
  })
})

describe('排序', () => {
  it('默认按名称升序', () => {
    expect(filterSources(LIST, { sort: 'name' }).map((s) => s.name)).toEqual(['a', 'b', 'c'])
    expect(filterSources(LIST, { sort: 'name', desc: true }).map((s) => s.name))
      .toEqual(['c', 'b', 'a'])
  })

  it('按分组排序时组内仍按名称', () => {
    const got = filterSources(LIST, { sort: 'group' }).map((s) => s.name)
    expect(got).toEqual(['a', 'b', 'c'])
  })

  it('按最近验证排序，且「没验证过」永远排最后', () => {
    const got = filterSources(LIST, { sort: 'verified' }).map((s) => s.name)
    expect(got[got.length - 1]).toBe('c')
    const desc = filterSources(LIST, { sort: 'verified', desc: true }).map((s) => s.name)
    expect(desc[desc.length - 1]).toBe('c')
  })

  it('导入的排前面（它更容易需要管理）', () => {
    expect(filterSources(LIST, { sort: 'imported' })[0].name).toBe('a')
  })
})

describe('杂项', () => {
  it('分组选项去重且有序', () => {
    expect(groupOptions(LIST)).toEqual(['都市', '玄幻'])
  })

  it('hasVerified 把 undefined 与 null 都当没验证过', () => {
    expect(hasVerified({ name: 'x' })).toBe(false)
    expect(hasVerified({ name: 'x', verified_at: null })).toBe(false)
    expect(hasVerified({ name: 'x', verified_at: 0 })).toBe(true)
  })
})
