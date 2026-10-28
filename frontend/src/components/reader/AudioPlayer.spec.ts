import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/lib/api'
import AudioPlayer from '@/components/reader/AudioPlayer.vue'

/**
 * 第 167 期：有声书书签。
 *
 * 坏起来都不会崩：锚格式不对 ⇒ 列表里混进文本书签；点「加在当前时间」没接 api ⇒
 * 什么都没发生；删除没调后端 ⇒ 刷新后又回来。规则在服务端（复用 bookmarks 表），
 * 这里钉前端接线与锚格式。
 */
vi.mock('@/lib/api', () => ({
  api: {
    listBookmarks: vi.fn(),
    addBookmark: vi.fn(),
    deleteBookmark: vi.fn(),
    getProgress: vi.fn(),
    setProgress: vi.fn(),
    recordSession: vi.fn(),
    audioTrackUrl: vi.fn((id: string, i: number) => `/audio/${id}/${i}`),
    unitFileUrl: vi.fn(),
  },
}))

const m = {
  list: vi.mocked(api.listBookmarks),
  add: vi.mocked(api.addBookmark),
  del: vi.mocked(api.deleteBookmark),
  progress: vi.mocked(api.getProgress),
  setProgress: vi.mocked(api.setProgress),
  session: vi.mocked(api.recordSession),
}

const TRACKS = [
  { index: 0, name: '01.mp3', size: 10, mtime: 0 },
  { index: 1, name: '02.mp3', size: 10, mtime: 0 },
] as never

function bookmark(id: number, anchor: string, label: string) {
  return {
    id, book_id: 'b1', anchor, chapter: 1, percent: 55, label,
    created_at: 0, updated_at: 0,
  }
}

async function mountPlayer() {
  const pinia = createPinia()
  setActivePinia(pinia)
  m.list.mockResolvedValue({
    items: [
      bookmark(1, 'audio:1:65', '第二节开始'),
      bookmark(2, '3:1200', '文本书签'),        // 不是音频锚，必须被过滤掉
    ],
    total: 2,
  })
  m.progress.mockResolvedValue({ percent: 0, locator: 0, updated_at: 0 } as never)
  m.add.mockResolvedValue({ ok: true, id: 9, created: true, revived: false } as never)
  m.del.mockResolvedValue({ ok: true, trashed: true })
  m.setProgress.mockResolvedValue({ updated_at: 0 } as never)
  m.session.mockResolvedValue({} as never)
  const w = mount(AudioPlayer, {
    props: { bookId: 'b1', tracks: TRACKS },
    global: { plugins: [pinia] },
  })
  await flushPromises()
  return w
}

describe('AudioPlayer 书签', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.clearAllMocks()
  })

  it('只显示音频锚的书签，时间按轨号 + 秒数显示', async () => {
    const w = await mountPlayer()
    expect(w.text()).toContain('第 2 轨 · 1:05')
    expect(w.text()).toContain('第二节开始')
    expect(w.text()).not.toContain('文本书签')
  })

  it('加书签：anchor 写成 audio:<轨>:<秒>，并刷新列表', async () => {
    const w = await mountPlayer()
    await w.find('audio').trigger('loadedmetadata')
    await w.find('input[aria-label="书签备注"]').setValue('这里好听')
    await w.findAll('button').find((b) => b.text().includes('加在当前时间'))!.trigger('click')
    await flushPromises()

    expect(m.add).toHaveBeenCalledWith('b1', {
      anchor: 'audio:0:0',
      chapter: 0,
      percent: 0,
      label: '这里好听',
    })
    expect(m.list).toHaveBeenCalledTimes(2)      // 挂载一次 + 加完刷新一次
  })

  it('删除书签走软删除接口', async () => {
    const w = await mountPlayer()
    const del = w.findAll('button').filter((b) => b.text() === '删除')[0]
    await del.trigger('click')
    await flushPromises()
    expect(m.del).toHaveBeenCalledWith('b1', 1)
  })
})
