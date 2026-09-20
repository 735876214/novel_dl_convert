import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

import { api, type StatsOverview } from '@/lib/api'
import { useLibraryStore } from '@/stores/library'

/**
 * 统计 store：/api/stats 的一次性缓存，供仪表盘部件共用（统计页**不**走这里，
 * 它有独立的窗口/范围选择）。
 *
 * 第 30 期：跟随当前书库（`currentLibraryId`）。「全部书库」是默认态，行为与加库
 * 维度之前逐字节一致；切库后自动失效重载，8 个仪表盘部件无需各自挂 watch。
 */
export const useStatsStore = defineStore('stats', () => {
  const data = ref<StatsOverview | null>(null)
  const loaded = ref(false)
  const library = useLibraryStore()

  async function load(force = false): Promise<void> {
    const lid = library.currentLibraryId || ''
    // 同一库且已加载则跳过；切库或强制时重拉（避免把「全部书库」的统计误当成某库）
    if (loaded.value && !force && data.value?.library_id === lid) return
    try {
      data.value = await api.stats(28, lid)
      loaded.value = true
    } catch {
      /* 未登录或后端不可用时保持为空 */
    }
  }

  // 切库后自动重载：只在我们曾经加载过时才重新请求，避免无人消费时也打接口
  watch(
    () => library.currentLibraryId,
    () => {
      if (data.value) void load(true)
    },
  )

  return { data, loaded, load }
})
