import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/lib/api'
import NotificationsView from '@/views/NotificationsView.vue'

vi.mock('@/lib/api', () => ({
  api: {
    notifications: vi.fn(),
    markNotificationsRead: vi.fn(),
    dismissNotifications: vi.fn(),
  },
}))

const m = {
  list: vi.mocked(api.notifications),
  read: vi.mocked(api.markNotificationsRead),
  dismiss: vi.mocked(api.dismissNotifications),
}

const N1 = { id: 'n1', read: false, action: '测试', status: '成功', file: 'a.txt', ts: '10:00' }

function page(items = [N1], over: Record<string, unknown> = {}) {
  return {
    items, count: items.length, total: 3, offset: 0, next_offset: 1,
    has_more: true, unread: items.filter((x) => !x.read).length, unread_total: 3,
    ...over,
  }
}

describe('NotificationsView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
    m.list.mockResolvedValue(page())
    m.dismiss.mockResolvedValue({ ok: true, dismissed: 1 })
    m.read.mockResolvedValue({ ok: true, marked: 1 })
  })

  it('渲染条目；隐藏单条 / 隐藏全部都接后端', async () => {
    const w = mount(NotificationsView, { global: { stubs: { RouterLink: true } } })
    await flushPromises()
    expect(w.text()).toContain('a.txt')

    await w.find('button[aria-label="隐藏这条通知"]').trigger('click')
    await flushPromises()
    expect(m.dismiss).toHaveBeenCalledWith({ ids: ['n1'] })

    await w.findAll('button').find((b) => b.text() === '隐藏全部')!.trigger('click')
    await flushPromises()
    expect(m.dismiss).toHaveBeenCalledWith({ all: true })
  })

  it('分页：加载更多带上 offset 并追加', async () => {
    m.list.mockResolvedValueOnce(page())
    m.list.mockResolvedValueOnce(page(
      [{ ...N1, id: 'n2', file: 'b.txt' }],
      { offset: 1, next_offset: null, has_more: false },
    ))
    const w = mount(NotificationsView, { global: { stubs: { RouterLink: true } } })
    await flushPromises()
    expect(m.list).toHaveBeenCalledWith(50, 0)

    await w.findAll('button').find((b) => b.text() === '加载更多')!.trigger('click')
    await flushPromises()
    expect(m.list).toHaveBeenCalledWith(50, 1)
    expect(w.text()).toContain('a.txt')
    expect(w.text()).toContain('b.txt')
  })
})
