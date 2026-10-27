import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import {
  MAX_SAVED_VIEWS,
  TABLE_COLUMNS,
  TABLE_PREFS_DEFAULT,
  normalizeTablePrefs,
  useTablePrefsStore,
} from './tablePrefs'

/**
 * 第 158 期：表格列偏好。
 *
 * 这组判据坏了不会崩 —— 只是「勾了没生效 / 导入把别人的视图覆盖掉 / 全部列被取消」。
 * 钉住：规范顺序、至少留一列、同名视图不覆盖、导入逐条校验。
 */
describe('tablePrefs', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('列集合按规范顺序存，未知键被忽略', () => {
    const p = normalizeTablePrefs({ columns: ['rating', 'author', 'nope'] })
    expect(p.columns).toEqual(['author', 'rating'])
  })

  it('空列集合退回默认可见集（表格不能只剩书名）', () => {
    expect(normalizeTablePrefs({ columns: [] }).columns).toEqual(TABLE_PREFS_DEFAULT.columns)
  })

  it('取消最后一列不生效', () => {
    const s = useTablePrefsStore()
    s.patch({ columns: ['author'] })
    s.toggleColumn('author')
    expect(s.prefs.columns).toEqual(['author'])
  })

  it('命名视图：保存 / 应用 / 删除，同名保存是更新', () => {
    const s = useTablePrefsStore()
    s.patch({ columns: ['author', 'rating'], density: 'compact' })
    const v = s.saveView('漫画')!
    expect(v.name).toBe('漫画')
    s.patch({ columns: ['series'], density: 'comfortable' })
    s.applyView(v.id)
    expect(s.prefs.columns).toEqual(['author', 'rating'])
    expect(s.prefs.density).toBe('compact')

    const again = s.saveView('漫画')!
    expect(again.id).toBe(v.id)
    expect(s.views).toHaveLength(1)

    s.deleteView(v.id)
    expect(s.views).toHaveLength(0)
  })

  it('导入：逐条校验，同名不覆盖，坏 JSON 给原因', () => {
    const s = useTablePrefsStore()
    s.saveView('已有')
    expect(s.importViews('{oops').error).toContain('JSON')
    const r = s.importViews(JSON.stringify({
      version: 1,
      views: [
        { name: '已有', prefs: { columns: ['author'] } },
        { name: '新的', prefs: { columns: ['format'] } },
        { name: '', prefs: { columns: ['author'] } },
      ],
    }))
    expect(r.added).toBe(1)
    expect(r.skipped).toBe(2)
    expect(s.views.map((v) => v.name)).toEqual(['已有', '新的'])
  })

  it('命名视图数量有上限（导入不会无限膨胀）', () => {
    const s = useTablePrefsStore()
    const views = Array.from({ length: MAX_SAVED_VIEWS + 5 }, (_, i) => ({
      name: `v${i}`,
      prefs: { columns: ['author'] },
    }))
    const r = s.importViews(JSON.stringify({ views }))
    expect(r.added).toBe(MAX_SAVED_VIEWS)
    expect(s.views).toHaveLength(MAX_SAVED_VIEWS)
  })

  it('导出的 JSON 能被自己导入（往返一致）', () => {
    const s = useTablePrefsStore()
    s.patch({ columns: ['author', 'pages'], density: 'compact', freezeTitle: true })
    s.saveView('A')
    const text = s.exportViews()
    const s2 = useTablePrefsStore()
    // 同 pinia 实例：先删掉再导入
    s2.deleteView(s2.views[0].id)
    expect(s2.importViews(text).added).toBe(1)
    s2.applyView(s2.views[0].id)
    expect(s2.prefs.columns).toEqual(['author', 'pages'])
    expect(s2.prefs.freezeTitle).toBe(true)
  })

  it('面板只提供六列（书名 / 操作不可隐藏）', () => {
    expect(TABLE_COLUMNS.map((c) => c.key)).toEqual([
      'author', 'series', 'format', 'pages', 'progress', 'rating',
    ])
  })
})
