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
    audioHeard: vi.fn(),
    audioChapters: vi.fn(),
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
  heard: vi.mocked(api.audioHeard),
  chapters: vi.mocked(api.audioChapters),
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

async function mountPlayer(chapters: { title: string; start_ms: number }[] = []) {
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
  m.heard.mockResolvedValue({ items: ['02.mp3'], total: 1 })
  m.chapters.mockResolvedValue({ items: chapters, supported: true })
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

  it('已听标记来自后端（只有列在 items 里的轨显示）', async () => {
    const w = await mountPlayer()
    expect(m.heard).toHaveBeenCalledWith('b1')
    const marks = w.findAll('span').filter((s) => s.text() === '已听')
    expect(marks).toHaveLength(1)
    expect(w.text()).toContain('已听 1')
  })

  it('倍速：档位扩到 0.5–3，细调按钮按 0.05 步进并夹住边界', async () => {
    const w = await mountPlayer()
    const sel = w.find('select[aria-label="播放倍速"]')
    const values = sel.findAll('option').map((o) => o.element.value)
    expect(values).toContain('0.5')
    expect(values).toContain('3')

    await sel.setValue('3')
    const up = w.findAll('button').find((b) => b.attributes('title') === '升 0.05 倍速')!
    expect(up.attributes('disabled')).toBeDefined()      // 已在 3x，升不动

    await sel.setValue('1')
    await flushPromises()
    await w.findAll('button').find((b) => b.attributes('title') === '升 0.05 倍速')!.trigger('click')
    await flushPromises()
    // 细调后不在预设档位里，下拉里要能显示它（不能是空白）
    expect((w.find('select[aria-label="播放倍速"]').element as HTMLSelectElement).value).toBe('1.05')
    expect(w.text()).toContain('1.05x（细调）')
  })

  it('睡眠：本轨结束模式在播完时暂停并复位；+15 分钟可延长倒计时', async () => {
    const w = await mountPlayer()
    const sel = w.find('select[aria-label="睡眠定时"]')
    expect(sel.findAll('option').map((o) => o.text())).toContain('本轨结束')

    await sel.setValue('15')
    expect(w.text()).toContain('15:00')
    await w.findAll('button').find((b) => b.text().includes('+15 分钟'))!.trigger('click')
    expect(w.text()).toContain('30:00')

    await sel.setValue('track-end')
    expect(w.text()).toContain('本轨结束')
    // 本轨结束模式没有倒计时可延 ⇒ 不再显示 +15
    expect(w.findAll('button').some((b) => b.text().includes('+15 分钟'))).toBe(false)
    await w.find('audio').trigger('ended')
    await flushPromises()
    expect((w.find('select[aria-label="睡眠定时"]').element as HTMLSelectElement).value).toBe('off')
  })

  it('按书倍速：记为本书后落本机，清除则回全局默认', async () => {
    const w = await mountPlayer()
    const sel = w.find('select[aria-label="播放倍速"]')
    await sel.setValue('1.5')
    await flushPromises()
    await w.findAll('button').find((b) => b.text() === '仅本书')!.trigger('click')
    await flushPromises()

    const stored = JSON.parse(localStorage.getItem('audio-book-speeds') || '{}')
    expect(stored.b1).toBe(1.5)
    expect(w.findAll('button').some((b) => b.text() === '本书 ×')).toBe(true)

    await w.findAll('button').find((b) => b.text() === '本书 ×')!.trigger('click')
    await flushPromises()
    expect(JSON.parse(localStorage.getItem('audio-book-speeds') || '{}')).toEqual({})
    expect((w.find('select[aria-label="播放倍速"]').element as HTMLSelectElement).value).toBe('1')
  })

  it('已有本书覆盖时，打开就是那本书的倍速', async () => {
    localStorage.setItem('audio-book-speeds', JSON.stringify({ b1: 1.25 }))
    const w = await mountPlayer()
    expect((w.find('select[aria-label="播放倍速"]').element as HTMLSelectElement).value).toBe('1.25')
  })

  it('M4B 章节：有 chpl 时显示章节列表与上一章/下一章', async () => {
    const w = await mountPlayer([
      { title: '第一章', start_ms: 0 },
      { title: '第二章', start_ms: 65000 },
    ])
    expect(w.text()).toContain('共 2 章')
    expect(w.text()).toContain('第一章')
    expect(w.text()).toContain('02:00'.replace('02:00', '1:05'))   // 65000ms = 1:05
    expect(w.findAll('button').some((b) => b.text() === '上一章')).toBe(true)
    expect(w.findAll('button').some((b) => b.text() === '下一章')).toBe(true)
  })

  it('删除书签走软删除接口', async () => {
    const w = await mountPlayer()
    const del = w.findAll('button').filter((b) => b.text() === '删除')[0]
    await del.trigger('click')
    await flushPromises()
    expect(m.del).toHaveBeenCalledWith('b1', 1)
  })
})
