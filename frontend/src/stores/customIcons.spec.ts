import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/lib/api'
import { useCustomIconsStore } from '@/stores/customIcons'

vi.mock('@/lib/api', () => ({
  api: {
    customIcons: vi.fn(),
    createCustomIcon: vi.fn(),
    deleteCustomIcon: vi.fn(),
  },
}))

const m = {
  list: vi.mocked(api.customIcons),
  create: vi.mocked(api.createCustomIcon),
  remove: vi.mocked(api.deleteCustomIcon),
}

describe('customIcons store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    m.list.mockResolvedValue({ items: [], total: 0 })
  })

  it('pathOf 只拼 path 标记；加载一次后缓存', async () => {
    m.list.mockResolvedValue({
      items: [{ key: 'custom-a', name: 'A', paths: ['M0 0h1', 'M2 2'], created_at: 0 }],
      total: 1,
    })
    const s = useCustomIconsStore()
    await s.load()
    expect(m.list).toHaveBeenCalledTimes(1)
    expect(s.pathOf('custom-a')).toBe('<path d="M0 0h1"/><path d="M2 2"/>')
    expect(s.pathOf('nope')).toBe('')
    await s.load()
    expect(m.list).toHaveBeenCalledTimes(1)
  })

  it('创建追加 / 删除移除', async () => {
    m.create.mockResolvedValue({ key: 'custom-b', name: 'B', paths: ['M1 1'], created_at: 0 })
    const s = useCustomIconsStore()
    await s.create('B', '<svg/>')
    expect(s.keys).toEqual(['custom-b'])
    m.remove.mockResolvedValue({ ok: true, removed: 'custom-b' })
    await s.remove('custom-b')
    expect(s.keys).toEqual([])
  })
})
