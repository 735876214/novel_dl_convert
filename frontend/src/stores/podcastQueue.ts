import { defineStore } from 'pinia'
import { ref } from 'vue'

/**
 * 播客播放队列（第 180 期）—— 页面级队列，存本机。
 *
 * 存的是**快照**（单集 id + 标题 + 所属订阅），不是完整单集对象：队列可以在刷新后
 * 仍然存在，播放时再回订阅里按 id 取「当前」那一集（下载状态 / 进度都可能已变）。
 * 跨订阅也允许 —— 播放时先切到那一档订阅再找单集。
 *
 * 为什么不放服务端：队列是「这台设备接下来听什么」，与书架偏好同档（`shelfPrefs` /
 * `tablePrefs`），换设备不该互相改。播放历史/进度才是服务端的事。
 */

export interface QueueItem {
  episodeId: string
  podcastId: string
  title: string
  podcastTitle: string
}

const KEY = 'podcast-queue'
/** 队列上限：这是「接下来听」，不是收藏夹。 */
export const QUEUE_MAX = 100

function read(): QueueItem[] {
  try {
    const raw = localStorage.getItem(KEY)
    const arr = raw ? JSON.parse(raw) : null
    if (!Array.isArray(arr)) return []
    return arr
      .filter((x) => x && typeof x.episodeId === 'string' && typeof x.podcastId === 'string')
      .slice(0, QUEUE_MAX)
      .map((x) => ({
        episodeId: String(x.episodeId),
        podcastId: String(x.podcastId),
        title: String(x.title || ''),
        podcastTitle: String(x.podcastTitle || ''),
      }))
  } catch {
    return []
  }
}

export const usePodcastQueueStore = defineStore('podcastQueue', () => {
  const items = ref<QueueItem[]>(read())

  function save(): void {
    try {
      localStorage.setItem(KEY, JSON.stringify(items.value))
    } catch {
      /* 隐私模式：本次会话仍生效 */
    }
  }

  function has(episodeId: string): boolean {
    return items.value.some((x) => x.episodeId === episodeId)
  }

  /** 入队（已在队列 / 已满则拒绝，返回是否真的加入）。 */
  function enqueue(item: QueueItem): boolean {
    if (has(item.episodeId) || items.value.length >= QUEUE_MAX) return false
    items.value = [...items.value, item]
    save()
    return true
  }

  function remove(episodeId: string): void {
    items.value = items.value.filter((x) => x.episodeId !== episodeId)
    save()
  }

  /** 取出并移除队首（播完自动连播用）。空队列返回 `null`。 */
  function shift(): QueueItem | null {
    const first = items.value[0] ?? null
    if (!first) return null
    items.value = items.value.slice(1)
    save()
    return first
  }

  function clear(): void {
    items.value = []
    save()
  }

  return { items, has, enqueue, remove, shift, clear }
})
