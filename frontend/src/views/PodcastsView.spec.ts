import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/lib/api'
import PodcastsView from '@/views/PodcastsView.vue'

/**
 * 第 173 期：播客订阅页的接线。
 *
 * 坏起来都是「点了没反应」：订阅按钮没接 api、列表没渲染、点某档没取单集。
 * RSS 解析/入库在后端用例里钉，这里只看前后端契约。
 */
vi.mock('@/lib/api', () => ({
  api: {
    podcasts: vi.fn(),
    subscribePodcast: vi.fn(),
    refreshPodcast: vi.fn(),
    podcastEpisodes: vi.fn(),
    deletePodcast: vi.fn(),
  },
}))

const m = {
  list: vi.mocked(api.podcasts),
  sub: vi.mocked(api.subscribePodcast),
  refresh: vi.mocked(api.refreshPodcast),
  eps: vi.mocked(api.podcastEpisodes),
  del: vi.mocked(api.deletePodcast),
}

const POD = {
  id: 'p1', feed_url: 'https://x/feed.xml', title: '测试播客', author: '某某',
  description: '', artwork_url: '', categories: ['科技'], explicit: false,
  last_fetched_at: 0, created_at: 0,
}

const EP = {
  id: 'e1', podcast_id: 'p1', guid: 'g1', title: '第 1 集', description: '简介',
  published_at: 1700000000, duration_sec: 3723, audio_url: 'https://cdn/1.mp3',
  audio_type: 'audio/mpeg', episode_no: 1, season_no: 0, explicit: false,
}

async function mountView() {
  const pinia = createPinia()
  setActivePinia(pinia)
  m.list.mockResolvedValue({ items: [POD], total: 1 })
  m.eps.mockResolvedValue({ items: [EP], total: 1 })
  const w = mount(PodcastsView, { global: { plugins: [pinia] } })
  await flushPromises()
  return w
}

describe('PodcastsView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('订阅列表来自后端；点单集取回单集并渲染音频地址', async () => {
    const w = await mountView()
    expect(w.text()).toContain('测试播客')

    await w.findAll('button').find((b) => b.text() === '单集')!.trigger('click')
    await flushPromises()
    expect(m.eps).toHaveBeenCalledWith('p1')
    expect(w.text()).toContain('第 1 集')
    expect(w.find('audio').attributes('src')).toBe('https://cdn/1.mp3')
  })

  it('订阅：把 URL 发给后端，成功后刷新列表', async () => {
    const w = await mountView()
    m.sub.mockResolvedValue({ podcast: POD, added: 1, updated: 0, total: 1, created: true })
    await w.find('input[aria-label="RSS 地址"]').setValue('https://x/feed.xml')
    await w.findAll('button').find((b) => b.text() === '订阅')!.trigger('click')
    await flushPromises()

    expect(m.sub).toHaveBeenCalledWith('https://x/feed.xml')
    expect(m.list.mock.calls.length).toBeGreaterThanOrEqual(2)   // 挂载一次 + 订阅后刷新
    expect(m.eps).toHaveBeenCalledWith('p1')                     // 订阅后自动展开单集
  })

  it('刷新 / 移除都接后端', async () => {
    const w = await mountView()
    m.refresh.mockResolvedValue({ podcast: POD, added: 2, updated: 1, total: 3 })
    m.del.mockResolvedValue({ ok: true, removed: 'p1' })
    await w.findAll('button').find((b) => b.text() === '刷新')!.trigger('click')
    await flushPromises()
    expect(m.refresh).toHaveBeenCalledWith('p1')

    await w.findAll('button').find((b) => b.text() === '移除')!.trigger('click')
    await flushPromises()
    expect(m.del).toHaveBeenCalledWith('p1')
  })
})
