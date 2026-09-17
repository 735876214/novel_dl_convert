import { defineStore } from 'pinia'
import { ref } from 'vue'

import { api, type CollectionItem } from '@/lib/api'

/**
 * 收藏夹 store：用户自建的收藏夹（持久化在后端 SQLite）。
 *
 * 侧栏「收藏夹」组、收藏页、书籍详情页的「加入收藏」共用这份列表，
 * 任一处的增删都走这里并刷新，保证多处显示一致。
 */
export const useCollectionsStore = defineStore('collections', () => {
  const items = ref<CollectionItem[]>([])
  const loaded = ref(false)

  async function load(force = false): Promise<void> {
    if (loaded.value && !force) return
    try {
      items.value = (await api.collections()).items
      loaded.value = true
    } catch {
      /* 未登录或后端不可用时保持空列表 */
    }
  }

  async function create(name: string): Promise<number> {
    const r = await api.createCollection(name)
    await load(true)
    return r.id
  }

  async function remove(id: number): Promise<void> {
    await api.deleteCollection(id)
    await load(true)
  }

  return { items, loaded, load, create, remove }
})
