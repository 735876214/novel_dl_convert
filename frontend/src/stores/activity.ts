import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

import { api, type ReadingActivity } from '@/lib/api'
import { useLibraryStore } from '@/stores/library'

/**
 * 阅读活动 store：/api/reading-activity 的一次性缓存，跟随当前书库。
 * 第 31 期新增。范围（今年/去年/全部）由视图本地控制，切范围时强制重载。
 */
export const useActivityStore = defineStore('activity', () => {
  const data = ref<ReadingActivity | null>(null)
  const loading = ref(false)
  const library = useLibraryStore()

  async function load(force = false, year?: number): Promise<void> {
    loading.value = true
    const lid = library.currentLibraryId || ''
    try {
      data.value = await api.readingActivity(lid, year)
    } catch {
      data.value = null
    } finally {
      loading.value = false
    }
  }

  watch(
    () => library.currentLibraryId,
    () => {
      if (data.value) void load(true)
    },
  )

  return { data, loading, load }
})
