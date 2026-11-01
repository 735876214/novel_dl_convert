import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { useDashboardStore } from '@/stores/dashboard'

/**
 * 第 206 期：仪表盘偏好进入偏好同步载荷。
 * 坏起来是「换设备后布局没跟过来」或「远端脏数据把本地书架行打散」。
 */
describe('dashboard store · 同步块', () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
  })

  it('applyRemote 走同一套合并；exportSync 给出可序列化快照', () => {
    const dash = useDashboardStore()
    dash.applyRemote({
      widgets: [{ id: 'library-overview', enabled: false }],
      shelves: [{ id: 'shelf-recent', type: 'recent', title: '远端最近', enabled: true,
        rows: 2, library_ids: ['lib-a'] }],
      shelf_layout: 'two-columns',
    })
    expect(dash.shelfLayout).toBe('two-columns')
    expect(dash.widgets.find((w) => w.id === 'library-overview')?.enabled).toBe(false)
    const recent = dash.shelves.find((s) => s.id === 'shelf-recent')
    expect(recent?.rows).toBe(2)
    expect(recent?.library_ids).toEqual(['lib-a'])

    const snap = dash.exportSync()
    expect(snap.shelf_layout).toBe('two-columns')
    expect(snap.widgets.length).toBeGreaterThan(1)      // 合并了注册表默认项
    expect(snap.shelves.some((s) => s.id === 'shelf-recent')).toBe(true)
    // 快照是拷贝，不是响应式代理
    snap.widgets[0].enabled = !snap.widgets[0].enabled
    expect(dash.widgets[0].enabled).not.toBe(snap.widgets[0].enabled)
  })

  it('脏块被夹回合法形态（未知类型行丢弃 / 非法布局回落单列）', () => {
    const dash = useDashboardStore()
    dash.applyRemote({
      widgets: [],
      shelves: [{ id: 'bad', type: 'nope' as never, title: '坏行', enabled: true }],
      shelf_layout: 'three-columns' as never,
    })
    expect(dash.shelfLayout).toBe('wide')
    expect(dash.shelves.some((s) => s.id === 'bad')).toBe(false)
  })
})
