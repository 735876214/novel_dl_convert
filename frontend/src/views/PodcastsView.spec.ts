import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api, type PodcastEpisode } from '@/lib/api'
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
    podcastsOpml: vi.fn(),
    importPodcastsOpml: vi.fn(),
    refreshAllPodcasts: vi.fn(),
    downloadPodcastEpisode: vi.fn(),
    downloadAllPodcastEpisodes: vi.fn(),
    cleanPodcastEpisode: vi.fn(),
    podcastEpisodeAudioUrl: vi.fn((eid: string) => `/local/${eid}`),
    savePodcastProgress: vi.fn(),
    markPodcastEpisodePlayed: vi.fn(),
    podcastBookmarks: vi.fn(),
    addPodcastBookmark: vi.fn(),
    deletePodcastBookmark: vi.fn(),
    getPodcastAuto: vi.fn(),
    setPodcastAuto: vi.fn(),
  },
}))

const m = {
  list: vi.mocked(api.podcasts),
  sub: vi.mocked(api.subscribePodcast),
  refresh: vi.mocked(api.refreshPodcast),
  eps: vi.mocked(api.podcastEpisodes),
  del: vi.mocked(api.deletePodcast),
  opml: vi.mocked(api.podcastsOpml),
  importOpml: vi.mocked(api.importPodcastsOpml),
  refreshAll: vi.mocked(api.refreshAllPodcasts),
  dl: vi.mocked(api.downloadPodcastEpisode),
  dlAll: vi.mocked(api.downloadAllPodcastEpisodes),
  clean: vi.mocked(api.cleanPodcastEpisode),
  prog: vi.mocked(api.savePodcastProgress),
  played: vi.mocked(api.markPodcastEpisodePlayed),
  bms: vi.mocked(api.podcastBookmarks),
  addBm: vi.mocked(api.addPodcastBookmark),
  delBm: vi.mocked(api.deletePodcastBookmark),
  autoSet: vi.mocked(api.setPodcastAuto),
}

const POD = {
  id: 'p1', feed_url: 'https://x/feed.xml', title: '测试播客', author: '某某',
  description: '', artwork_url: '', categories: ['科技'], explicit: false,
  last_fetched_at: 0, last_attempt_at: 0, last_ok_at: 0, fail_count: 0, last_error: '',
  auto_download: false, auto_keep: 0, auto_clean: false,
  created_at: 0,
}

const EP: PodcastEpisode = {
  id: 'e1', podcast_id: 'p1', guid: 'g1', title: '第 1 集', description: '简介',
  published_at: 1700000000, duration_sec: 3723, audio_url: 'https://cdn/1.mp3',
  audio_type: 'audio/mpeg', episode_no: 1, season_no: 0, explicit: false,
  download_state: '', download_error: '', downloaded_at: 0, local_bytes: 0, has_local: false,
  position_sec: 0, played_at: 0,
}

async function mountView(episodes: PodcastEpisode[] = [EP]) {
  const pinia = createPinia()
  setActivePinia(pinia)
  m.list.mockResolvedValue({ items: [POD], total: 1 })
  m.prog.mockResolvedValue({})
  m.eps.mockResolvedValue({ items: episodes, total: episodes.length })
  const w = mount(PodcastsView, { global: { plugins: [pinia] } })
  await flushPromises()
  return w
}

describe('PodcastsView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
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

  it('OPML：导入走文件内容，导出触发下载，全部刷新调后端', async () => {
    const w = await mountView()
    m.importOpml.mockResolvedValue({ total: 2, added: 1, refreshed: 1, failed: [] })
    m.opml.mockResolvedValue({ opml: '<?xml version="1.0"?><opml/>' })
    m.refreshAll.mockResolvedValue({ ok: 1, failed: 0, items: [] })
    // 导出 / 全部刷新接后端即可（下载动作由浏览器 API 完成，不在本 spec 断言）
    await w.findAll('button').find((b) => b.text() === '导出 OPML')!.trigger('click')
    await flushPromises()
    expect(m.opml).toHaveBeenCalled()
    await w.findAll('button').find((b) => b.text() === '全部刷新')!.trigger('click')
    await flushPromises()
    expect(m.refreshAll).toHaveBeenCalled()

    // 导入：用 File + change 事件模拟文件选择
    const file = new File([new Blob(['<opml/>'])], 'x.opml', { type: 'text/xml' })
    const input = w.find('input[type="file"]')
    Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
    await input.trigger('change')
    await flushPromises()
    expect(m.importOpml).toHaveBeenCalled()
  })

  it('下载：点“下载”调后端；已下载的单集播放本地地址', async () => {
    const w = await mountView()
    m.dl.mockResolvedValue({ ok: true, state: 'downloading' })
    await w.findAll('button').find((b) => b.text() === '单集')!.trigger('click')
    await flushPromises()
    await w.findAll('button').find((b) => b.text() === '下载')!.trigger('click')
    await flushPromises()
    expect(m.dl).toHaveBeenCalledWith('e1')

    // 已下载：audio 的 src 走本地出口（带 token 的 URL 由 api 生成）
    m.eps.mockResolvedValue({
      items: [{ ...EP, download_state: 'downloaded', has_local: true }],
      total: 1,
    })
    // 第一次点了「单集」后按钮变「收起」—— 再点一次重新拉取单集
    await w.findAll('button').find((b) => b.text() === '收起')!.trigger('click')
    await flushPromises()
    expect(w.find('audio').attributes('src')).toBe('/local/e1')
    expect(w.text()).toContain('已下载')
  })

  it('播放状态筛选与手动标已播', async () => {
    m.eps.mockResolvedValue({
      items: [
        { ...EP, id: 'e1', title: '未播', position_sec: 0, played_at: 0 },
        { ...EP, id: 'e2', title: '进行中', position_sec: 30, played_at: 0 },
        { ...EP, id: 'e3', title: '已播', position_sec: 100, played_at: 1700000000 },
      ],
      total: 3,
    })
    const w = await mountView()
    await w.findAll('button').find((b) => b.text() === '单集')!.trigger('click')
    await flushPromises()
    expect(w.text()).toContain('进行中')
    expect(w.text()).toContain('已播')

    // 点「未播」筛选：只剩那一集
    await w.findAll('button').find((b) => b.text().startsWith('未播'))!.trigger('click')
    await flushPromises()
    expect(w.text()).toContain('未播')
    expect(w.text()).not.toContain('已播 1')

    // 手动标已播接后端
    m.played.mockResolvedValue({})
    await w.findAll('button').find((b) => b.text() === '标已播')!.trigger('click')
    await flushPromises()
    expect(m.played).toHaveBeenCalledWith('e1', true)
  })

  it('单集书签：打开列表、加在当前时间、删除', async () => {
    const w = await mountView()
    m.bms.mockResolvedValue({ items: [{ id: 'bm1', episode_id: 'e1', position_sec: 30,
      title: '0:30', note: '', created_at: 0 }], total: 1 })
    m.addBm.mockResolvedValue({ id: 'bm2', episode_id: 'e1', position_sec: 0,
      title: '0:00', note: '', created_at: 0 })
    m.delBm.mockResolvedValue({ ok: true, removed: 'bm1' })

    await w.findAll('button').find((b) => b.text() === '单集')!.trigger('click')
    await flushPromises()
    await w.findAll('button').find((b) => b.text() === '书签')!.trigger('click')
    await flushPromises()
    expect(m.bms).toHaveBeenCalledWith('e1')
    expect(w.text()).toContain('0:30')

    await w.findAll('button').find((b) => b.text() === '加在当前时间')!.trigger('click')
    await flushPromises()
    expect(m.addBm).toHaveBeenCalledWith('e1', { position_sec: 0, title: '0:00' })

    await w.findAll('button').find((b) => b.text() === '删除')!.trigger('click')
    await flushPromises()
    expect(m.delBm).toHaveBeenCalledWith('bm1')
  })

  it('播完自动连播：默认开，关掉后不自动放下一集', async () => {
    localStorage.removeItem('podcast-autonext')
    const w = await mountView([
      { ...EP, id: 'e1', title: '第一集' },
      { ...EP, id: 'e2', title: '第二集' },
    ])
    await w.findAll('button').find((b) => b.text() === '单集')!.trigger('click')
    await flushPromises()

    const audios = w.findAll('audio')
    expect(audios).toHaveLength(2)
    const secondPlay = vi.fn(() => Promise.resolve())
    ;(audios[1].element as HTMLAudioElement).play = secondPlay as never
    await audios[0].trigger('ended')
    await flushPromises()
    expect(secondPlay).toHaveBeenCalledTimes(1)

    // 关掉开关后不再自动播（按标签定位：面板里还有「听完清理」复选框）
    const autoNextBox = w.findAll('input[type="checkbox"]').find((c) => {
      const label = c.element.closest('label')?.textContent || ''
      return label.includes('播完自动连播')
    })
    expect(autoNextBox).toBeTruthy()
    await autoNextBox!.setValue(false)
    await flushPromises()
    const before = secondPlay.mock.calls.length
    await audios[0].trigger('ended')
    await flushPromises()
    expect(secondPlay.mock.calls.length).toBe(before)
  })

  it('播放队列：加入 / 面板显示 / 播完优先取队首', async () => {
    const w = await mountView([
      { ...EP, id: 'e1', title: '第一集' },
      { ...EP, id: 'e2', title: '第二集' },
    ])
    await w.findAll('button').find((b) => b.text() === '单集')!.trigger('click')
    await flushPromises()

    // 把第二集加入队列
    const addBtns = w.findAll('button').filter((b) => b.text() === '加入队列')
    await addBtns[1].trigger('click')
    await flushPromises()
    expect(w.text()).toContain('播放队列（1）')
    expect(w.text()).toContain('移出队列')

    // 第一集播完 ⇒ 取队首（第二集）播放，且队列清空
    const audios = w.findAll('audio')
    const secondPlay = vi.fn(() => Promise.resolve())
    ;(audios[1].element as HTMLAudioElement).play = secondPlay as never
    await audios[0].trigger('ended')
    await flushPromises()
    expect(secondPlay).toHaveBeenCalled()
    expect(w.text()).not.toContain('播放队列（1）')
  })

  it('自动策略：保存最新 N 集与听完清理', async () => {
    const w = await mountView()
    await w.findAll('button').find((b) => b.text() === '单集')!.trigger('click')
    await flushPromises()

    m.autoSet.mockResolvedValue({ auto_download: true, auto_keep: 3, auto_clean: true })
    await w.find('input[aria-label="自动下载最新集数"]').setValue('3')
    const clean = w.findAll('input[type="checkbox"]').find((c) => {
      const label = c.element.closest('label')?.textContent || ''
      return label.includes('听完清理')
    })
    expect(clean).toBeTruthy()
    await clean!.setValue(true)
    await w.findAll('button').find((b) => b.text() === '保存自动策略')!.trigger('click')
    await flushPromises()

    expect(m.autoSet).toHaveBeenCalledWith('p1', { auto_keep: 3, auto_clean: true })
  })
})
