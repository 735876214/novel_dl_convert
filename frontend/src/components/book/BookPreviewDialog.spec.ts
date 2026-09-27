import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

import BookPreviewDialog from '@/components/book/BookPreviewDialog.vue'
import { api, type BookCard, type BookDetail } from '@/lib/api'

/**
 * 快速预览浮层（第 64 期 2/3）。
 *
 * 两条契约写错都**不会报错**，只会悄悄给用户错信息：
 *
 * 1. **详情拉失败时只坏那一行** —— 浮层的主要内容（标题 / 作者 / 格式 / 状态）
 *    全在书卡上，详情请求只补「N 章」。若失败时把整块换成错误页，等于把一份
 *    真数据说成「没有」；若失败时照常写「0 章」，那是把「没拿到」说成「没有」。
 * 2. **「下载 / 阅读」不给出去了错的格式** —— AUDIO 整本是一个目录，没有可下的
 *    单个文件（与 ⋮ 菜单同一套判据，`lib/bookOpen.ts`）。
 */
vi.mock('@/lib/api', () => ({
  api: {
    bookDetail: vi.fn(),
    downloadUrl: vi.fn((name: string, libraryId?: string) =>
      `/download/${name}${libraryId ? `?library_id=${libraryId}` : ''}`,
    ),
  },
  apiErrorMessage: (_e: unknown, fallback: string) => fallback,
}))

const m = { bookDetail: vi.mocked(api.bookDetail) }

function makeBook(over: Partial<BookCard> = {}): BookCard {
  return {
    id: 'lib$aaa',
    name: '三体.epub',
    title: '三体',
    author: '刘慈欣',
    series: '三体',
    series_index: '1',
    has_cover: false,
    format: 'EPUB',
    size: 1024,
    mtime: 1700000000,
    c1: 'oklch(0.9 0 0)',
    c2: 'oklch(0.8 0 0)',
    tags: [],
    narrators: [],
    year: '2008',
    publisher: '重庆出版社',
    isbn: '',
    language: 'zh',
    description: '地球往事三部曲之一。',
    issues: [],
    library_id: 'lib',
    ...over,
  }
}

const BOOK = makeBook()

function makeDetail(over: Partial<BookDetail> = {}): BookDetail {
  return {
    ...BOOK,
    chapters: [
      { title: '第一部', chapters: [{ title: '科学边界' }, { title: '台球' }] },
      { title: '第二部', chapters: [{ title: '宇宙闪烁' }] },
    ],
    files: [{ name: '三体.epub', format: 'EPUB', size: 1024, mtime: 1 }],
    ...over,
  } as BookDetail
}

let router: Router
const mounted: VueWrapper[] = []

async function mountDialog(book: BookCard | null = BOOK): Promise<VueWrapper> {
  const w = mount(BookPreviewDialog, {
    props: { open: true, book },
    global: { plugins: [router] },
  })
  mounted.push(w)
  await flushPromises()
  return w
}

function text(w: VueWrapper): string {
  return w.text().replace(/\s+/g, ' ')
}

beforeEach(async () => {
  setActivePinia(createPinia())
  // 详情是**按 id 记忆化**的（`library.details`）⇒ 换用例必须换 pinia（上面刚换），
  // 否则上一个用例的详情会被当成这个用例的缓存命中，失败态那两条永远绿
  m.bookDetail.mockResolvedValue(makeDetail())

  router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      { path: '/read/:id', component: { template: '<div />' } },
      { path: '/listen/:id', component: { template: '<div />' } },
    ],
  })
  await router.push('/')
  await router.isReady()
})

afterEach(() => {
  for (const w of mounted.splice(0)) w.unmount()
  document.body.innerHTML = ''
})

describe('BookPreviewDialog', () => {
  it('内容取自书卡：标题 / 作者 / 系列 / 格式 / 简介都在', async () => {
    const w = await mountDialog()
    const t = text(w)

    expect(t).toContain('三体')
    expect(t).toContain('刘慈欣')
    expect(t).toContain('EPUB')
    expect(t).toContain('地球往事三部曲之一。')
    // 章节数是详情补的：三个子章 → 「3 章」
    expect(t).toContain('3 章')
  })

  it('详情拉到了就补章节数；拉不到只说这一项，卡片上的真数据一个字不吞', async () => {
    m.bookDetail.mockResolvedValue(makeDetail())
    const ok = await mountDialog()
    expect(text(ok)).toContain('3 章')

    // 换一本（id 不同）才会重新请求 —— 同一个 id 会命中详情缓存
    const other = makeBook({ id: 'lib$bbb', title: '球状闪电' })
    m.bookDetail.mockRejectedValue(new Error('后端连不上'))
    const bad = await mountDialog(other)

    const t = text(bad)
    expect(t).toContain('详细目录没拿到')
    expect(t).toContain('后端连不上')
    // ⚠️ 这两条才是重点：没把真数据换成错误页，也没把「没拿到」写成「0 章」
    expect(t).toContain('球状闪电')
    expect(t).toContain('EPUB')
    expect(t).not.toContain('0 章')
    // 还能重试（不是一次失败就锁死）
    expect(bad.findAll('button').some((b) => b.text().includes('重试'))).toBe(true)
  })

  it('EPUB：开始阅读跳到阅读器并关掉浮层', async () => {
    const w = await mountDialog()
    const btn = w.findAll('button').find((b) => b.text().trim() === '阅读')
    expect(btn).toBeTruthy()
    await btn!.trigger('click')
    await flushPromises()

    expect(w.emitted('close')).toBeTruthy()
    expect(router.currentRoute.value.fullPath).toBe('/read/lib$aaa')
  })

  it('AUDIO：给「收听」不给「下载」（有声书整本是一个目录）', async () => {
    const w = await mountDialog(makeBook({ format: 'AUDIO', name: '三体' }))
    const labels = w.findAll('button').map((b) => b.text().trim())

    expect(labels).toContain('收听')
    expect(labels).not.toContain('阅读')
    expect(labels).not.toContain('下载')
  })

  it('MOBI：既不能读也不能听，但「下载」与「详细信息」都在', async () => {
    const w = await mountDialog(makeBook({ format: 'MOBI', has_cover: false }))
    const labels = w.findAll('button').map((b) => b.text().trim())

    expect(labels).not.toContain('阅读')
    expect(labels).not.toContain('收听')
    expect(labels).toContain('下载')
    expect(labels).toContain('详细信息')
  })

  it('「详细信息」把书一起 emit 出去（父组件不必猜浮层里是谁）', async () => {
    const w = await mountDialog()
    const btn = w.findAll('button').find((b) => b.text().trim() === '详细信息')
    await btn!.trigger('click')

    expect(w.emitted('open-detail')?.[0]).toEqual([BOOK])
  })

  it('Escape 与点遮罩都关掉它', async () => {
    const w = await mountDialog()
    expect(w.find('[role="dialog"]').exists()).toBe(true)

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await flushPromises()
    expect(w.emitted('close')).toBeTruthy()

    // 遮罩：点在对话框**本身**上（非内容区）才算「点外面」
    await w.find('[role="dialog"]').trigger('click')
    expect(w.emitted('close')?.length).toBe(2)
  })
})
