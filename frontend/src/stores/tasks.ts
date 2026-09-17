import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import type { TaskStatus } from '@/data/tasks'
import { api, type TaskItem } from '@/lib/api'

/**
 * 任务 store：数据全部来自服务端真实任务表（`GET /api/tasks`）。
 *
 * ⚠️ 与旧实现的两点关键区别：
 *   1. **没有演示种子数据**。旧版从 `data/tasks.ts` 灌入 6 条写死的假任务（诡秘之主、三体…），
 *      并把它们和真实任务混在一起展示。
 *   2. **没有假进度**。旧版用 900ms ticker 每跳 +1.5% 推进进度条 —— 下载器根本不报细分进度，
 *      那个百分比是凭空造的。现在进度只反映真实里程碑（0 入队 / 50 开始 / 100 结束）。
 *
 * 轮询策略：仅当存在未结束任务时才按固定间隔刷新；没有活跃任务时自动停止，
 * 避免空转请求。
 */
const POLL_MS = 2500

export const useTasksStore = defineStore('tasks', () => {
  const tasks = ref<TaskItem[]>([])
  const loading = ref(false)
  const error = ref('')
  let timer: ReturnType<typeof setInterval> | null = null

  function byStatus(status: TaskStatus): TaskItem[] {
    return tasks.value.filter((t) => t.status === status)
  }

  const running = computed(() => byStatus('running'))
  const queued = computed(() => byStatus('queued'))
  const failed = computed(() => byStatus('failed'))
  const done = computed(() => byStatus('done'))

  /** 「运行中 + 排队中」——侧栏任务中心计数胶囊用 */
  const runningCount = computed(() => running.value.length + queued.value.length)

  const lastError = computed(() => failed.value[0]?.error ?? '')

  function countByStatus(status: TaskStatus): number {
    return byStatus(status).length
  }

  async function load(): Promise<void> {
    loading.value = true
    try {
      const r = await api.tasks()
      tasks.value = r.items ?? []
      error.value = ''
    } catch (e) {
      error.value = e instanceof Error ? e.message : '任务列表加载失败'
    } finally {
      loading.value = false
    }
  }

  function stopPolling(): void {
    if (timer === null) return
    clearInterval(timer)
    timer = null
  }

  /** 按「有无未结束任务」启停轮询 */
  function syncPolling(): void {
    if (runningCount.value > 0) {
      if (timer === null) timer = setInterval(() => void refresh(), POLL_MS)
    } else {
      stopPolling()
    }
  }

  async function refresh(): Promise<void> {
    await load()
    syncPolling()
  }

  /** 发起下载/转换后调用：立刻刷新一次并按需开始轮询 */
  async function track(): Promise<void> {
    await refresh()
  }

  return {
    tasks,
    loading,
    error,
    running,
    queued,
    failed,
    done,
    runningCount,
    lastError,
    countByStatus,
    load,
    refresh,
    track,
    syncPolling,
    stopPolling,
  }
})
