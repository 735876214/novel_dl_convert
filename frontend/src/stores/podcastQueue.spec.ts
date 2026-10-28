import { describe, expect, it, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { QUEUE_MAX, usePodcastQueueStore, type QueueItem } from './podcastQueue'

/**
 * 第 180 期：播客播放队列（本机持久化）。
 *
 * 坏了不会报错：重复入队出现两条、播完不按顺序取、刷新页面队列丢了 ——
 * 用户只会觉得「这队列不听话」。
 */
function item(id: string, pid = 'p1'): QueueItem {
  return { episodeId: id, podcastId: pid, title: `第 ${id} 集`, podcastTitle: '播客' }
}

describe('podcastQueue', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
  })

  it('入队去重、按加入顺序取出、取出后从队列移除', () => {
    const q = usePodcastQueueStore()
    expect(q.enqueue(item('e1'))).toBe(true)
    expect(q.enqueue(item('e2'))).toBe(true)
    expect(q.enqueue(item('e1'))).toBe(false)
    expect(q.items.map((x) => x.episodeId)).toEqual(['e1', 'e2'])

    expect(q.shift()?.episodeId).toBe('e1')
    expect(q.items.map((x) => x.episodeId)).toEqual(['e2'])
    expect(q.shift()?.episodeId).toBe('e2')
    expect(q.shift()).toBeNull()
  })

  it('移除与清空；has 判重', () => {
    const q = usePodcastQueueStore()
    q.enqueue(item('e1'))
    q.enqueue(item('e2'))
    expect(q.has('e1')).toBe(true)
    q.remove('e1')
    expect(q.has('e1')).toBe(false)
    q.clear()
    expect(q.items).toEqual([])
  })

  it('落 localStorage，换 store 实例仍在；有上限', () => {
    const q = usePodcastQueueStore()
    q.enqueue(item('e1'))
    q.enqueue(item('e2'))
    // 新 pinia ⇒ 新 store 实例，从 localStorage 恢复
    setActivePinia(createPinia())
    const q2 = usePodcastQueueStore()
    expect(q2.items.map((x) => x.episodeId)).toEqual(['e1', 'e2'])

    q2.clear()
    for (let i = 0; i < QUEUE_MAX + 5; i += 1) q2.enqueue(item(`x${i}`))
    expect(q2.items).toHaveLength(QUEUE_MAX)
    expect(q2.enqueue(item('overflow'))).toBe(false)
  })
})
