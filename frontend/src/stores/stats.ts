import { defineStore } from 'pinia'
import { ref } from 'vue'

import { api, type StatsOverview } from '@/lib/api'

/** 统计 store：/api/stats 的一次性缓存，供统计页与仪表盘部件共用。 */
export const useStatsStore = defineStore('stats', () => {
  const data = ref<StatsOverview | null>(null)
  const loaded = ref(false)

  async function load(force = false): Promise<void> {
    if (loaded.value && !force) return
    try {
      data.value = await api.stats()
      loaded.value = true
    } catch {
      /* 未登录或后端不可用时保持为空 */
    }
  }

  return { data, loaded, load }
})
