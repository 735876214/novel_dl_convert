import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { TASKS as SEED_TASKS, type Task, type TaskStatus } from '@/data/tasks'

/**
 * 任务 store。
 *
 * 进度推进沿用 v2 的**确定性步进**（原 startTicker，900ms 一跳），
 * 不使用随机数 —— 这样每次渲染图形一致，也不会像参考页那样每帧乱跳。
 */
const TICK_MS = 900
/** 每个 tick 每个运行中任务推进的百分比 */
const STEP = 1.5

export const useTasksStore = defineStore('tasks', () => {
  const tasks = ref<Task[]>(SEED_TASKS.map((t) => ({ ...t })))
  let timer: ReturnType<typeof setInterval> | null = null

  const running = computed(() => tasks.value.filter((t) => t.status === 'running'))
  const queued = computed(() => tasks.value.filter((t) => t.status === 'queued'))
  const failed = computed(() => tasks.value.filter((t) => t.status === 'failed'))
  const done = computed(() => tasks.value.filter((t) => t.status === 'done'))

  /** 「运行中 + 排队中」——侧栏任务中心计数胶囊用 */
  const runningCount = computed(
    () => tasks.value.filter((t) => t.status === 'running' || t.status === 'queued').length,
  )

  const totalPages = computed(() => 0)

  const lastError = computed(() => failed.value[0]?.error ?? '')

  function countByStatus(status: TaskStatus): number {
    return tasks.value.filter((t) => t.status === status).length
  }

  /** 推进进度；到达 100% 自动转为已完成，并把队首任务提为运行中 */
  function tick(): void {
    let finished = false

    tasks.value.forEach((t) => {
      if (t.status !== 'running') return
      t.progress = Math.min(100, Math.round((t.progress + STEP) * 10) / 10)
      if (t.progress >= 100) {
        t.status = 'done'
        delete t.speed
        delete t.eta
        finished = true
      }
    })

    if (finished) {
      const next = tasks.value.find((t) => t.status === 'queued')
      if (next) next.status = 'running'
    }
  }

  /** 登记一条外部任务（真实下载任务由「探索发现」页创建后塞进来） */
  function addTask(task: Task): void {
    tasks.value.unshift(task)
  }

  /** 按 id 更新一条任务的部分字段（真实任务的进度轮询用） */
  function patchTask(id: string, patch: Partial<Task>): void {
    const target = tasks.value.find((t) => t.id === id)
    if (!target) return
    Object.assign(target, patch)
  }

  function startTicker(): void {
    if (timer !== null) return
    timer = setInterval(tick, TICK_MS)
  }

  function stopTicker(): void {
    if (timer === null) return
    clearInterval(timer)
    timer = null
  }

  return {
    tasks,
    running,
    queued,
    failed,
    done,
    runningCount,
    totalPages,
    lastError,
    countByStatus,
    addTask,
    patchTask,
    tick,
    startTicker,
    stopTicker,
  }
})
