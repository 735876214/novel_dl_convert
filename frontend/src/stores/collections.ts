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
  /**
   * 加载失败信息。⚠️ 这是**主数据**（侧栏「收藏夹」组与收藏页都吃它），
   * 失败必须能被页面区分出来 —— 否则「拉不到」会被读成「还没有收藏夹」。
   */
  const error = ref('')

  async function load(force = false): Promise<void> {
    if (loaded.value && !force) return
    error.value = ''
    try {
      items.value = (await api.collections()).items
      loaded.value = true
    } catch (e) {
      /* 未登录或后端不可用：保持空列表，但记下错误供页面显示错误态 */
      error.value = e instanceof Error ? e.message : '加载失败'
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

  async function rename(id: number, name: string): Promise<void> {
    await api.renameCollection(id, name)
    await load(true)
  }

  return { items, loaded, error, load, create, remove, rename }
})
