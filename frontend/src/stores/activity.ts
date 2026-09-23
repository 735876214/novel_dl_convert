import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

import { api, type ReadingActivity } from '@/lib/api'
import { useLibraryStore } from '@/stores/library'

/**
 * 阅读活动 store：/api/reading-activity 的缓存，跟随当前书库与**年份范围**。
 *
 * 第 31 期新增。第 46 期把「年份范围 / 条数上限」从视图挪进来：此前切书库时
 * store 调 `load(true)` **不带 year**，于是拉回全量数据、而视图的范围选择器仍停在
 * 「今年」⇒ 选择器与数据两处真值源不一致（`force` 参数也形同虚设）。
 */
export const useActivityStore = defineStore('activity', () => {
  const data = ref<ReadingActivity | null>(null)
  const loading = ref(false)
  const error = ref(false)
  /** 当前数据对应的查询条件（年份 / 条数上限），与 `data` 同源，切换时一并重载。 */
  const year = ref<number | undefined>(undefined)
  const limit = ref(120)
  const library = useLibraryStore()

  async function load(force = false, nextYear = year.value, nextLimit = limit.value): Promise<void> {
    const lid = library.currentLibraryId || ''
    // 命中同一 (库, 年份, 上限) 且已有数据 ⇒ 直接用缓存；`force` 才真正强制重载。
    if (!force && data.value && year.value === nextYear && limit.value === nextLimit) return
    loading.value = true
    error.value = false
    try {
      data.value = await api.readingActivity(lid, nextYear, nextLimit)
      year.value = nextYear
      limit.value = nextLimit
    } catch {
      data.value = null
      error.value = true
    } finally {
      loading.value = false
    }
  }

  watch(
    () => library.currentLibraryId,
    () => {
      // 跟随书库重载，**带上当前年份与上限**，避免范围与数据错配。
      if (data.value || error.value) void load(true)
    },
  )

  return { data, loading, error, year, limit, load }
})
