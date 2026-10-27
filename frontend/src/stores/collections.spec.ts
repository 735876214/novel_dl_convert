import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api, type CollectionItem } from '@/lib/api'
import { useCollectionsStore } from '@/stores/collections'

vi.mock('@/lib/api', () => ({
  api: {
    collections: vi.fn(),
    reorderCollections: vi.fn(),
    createCollection: vi.fn(),
    deleteCollection: vi.fn(),
    renameCollection: vi.fn(),
  },
}))

function item(id: number, name: string, order: number): CollectionItem {
  return {
    id,
    name,
    count: 0,
    created_at: id,
    updated_at: id,
    sort_order: order,
    first_book_id: null,
    first_book_has_cover: false,
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.mocked(api.collections).mockResolvedValue({ items: [item(1, '甲', 0), item(2, '乙', 1)] })
  vi.mocked(api.reorderCollections).mockResolvedValue({ items: [item(2, '乙', 0), item(1, '甲', 1)] })
})

describe('collections.reorder（第 154 期）', () => {
  it('先把本地顺序换位，再以服务端返回为准', async () => {
    const store = useCollectionsStore()
    await store.load(true)

    await store.reorder([2, 1])

    expect(vi.mocked(api.reorderCollections)).toHaveBeenCalledWith([2, 1])
    expect(store.items.map((c) => c.id)).toEqual([2, 1])
  })

  it('提交失败：回滚到服务端顺序并抛出（页面据此 toast）', async () => {
    const store = useCollectionsStore()
    await store.load(true)
    vi.mocked(api.reorderCollections).mockRejectedValue(new Error('boom'))

    await expect(store.reorder([2, 1])).rejects.toThrow('boom')
    // 回滚读的是服务端，不是本地那份乐观顺序
    expect(vi.mocked(api.collections)).toHaveBeenCalledTimes(2)
    expect(store.items.map((c) => c.id)).toEqual([1, 2])
  })
})
