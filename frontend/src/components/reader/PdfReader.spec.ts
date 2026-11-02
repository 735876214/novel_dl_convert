import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * PDF 阅读器的两个交互（第 231 期）：**拖拽平移**与**站外链确认**。
 *
 * 这两条都属「坏了在界面上看不出来」的那一类：
 * - 平移不生效 ⇒ 放大后只能靠滚动条挪（而横向模式还要先切模式）；
 * - 外链直接开 ⇒ PDF 里的一个链接能把用户带到任意站点（自托管阅读器不该替它做这个决定）；
 *   外链**点不动** ⇒ 那就是「看起来能点」的假链接 —— 一样是缺陷。
 */

/** pdf.js 的最小替身：只提供这两个交互用得到的接口。 */
const pdfPage = {
  getViewport: () => ({ width: 200, height: 100, transform: [1, 0, 0, -1, 0, 100] }),
  getTextContent: async () => ({ items: [] }),
  getAnnotations: async () => ([
    { subtype: 'Link', url: 'https://example.com/x', rect: [10, 40, 60, 50] },
    { subtype: 'Link', url: 'javascript:alert(1)', rect: [10, 10, 60, 20] },
    { subtype: 'Square', rect: [0, 0, 5, 5] },   // 不是链接 ⇒ 不该画热区
  ]),
  render: () => ({ promise: Promise.resolve() }),
}

vi.mock('pdfjs-dist', () => ({
  getDocument: () => ({ promise: Promise.resolve({
    numPages: 1,
    getPage: async () => pdfPage,
    destroy: () => {},
  }) }),
  GlobalWorkerOptions: {},
}))
vi.mock('pdfjs-dist/build/pdf.worker.min.mjs?url', () => ({ default: '/worker.mjs' }))

vi.mock('@/lib/api', () => ({
  api: {
    bookDetail: vi.fn(),
    pdfSearch: vi.fn(),
    listAnnotations: vi.fn().mockResolvedValue({ items: [] }),
    addAnnotation: vi.fn(),
    deleteAnnotation: vi.fn(),
    readingThresholds: vi.fn(),
    coverUrl: vi.fn((id: string) => `/api/books/${id}/cover`),
    downloadUrl: vi.fn((n: string) => `/download/${n}`),
    pdfOutline: vi.fn().mockResolvedValue({ items: [] }),
  },
}))

import PdfReader from '@/components/reader/PdfReader.vue'

describe('PdfReader：拖拽平移 + 站外链确认（第 231 期）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    // happy-dom 里没有 PointerEvent ⇒ 补一个最小的（事件处理器只读 button/clientX/clientY）
    if (typeof (globalThis as any).PointerEvent === 'undefined') {
      class _PE extends MouseEvent {
        pointerId: number
        constructor(type: string, init: any = {}) {
          super(type, init)
          this.pointerId = init.pointerId ?? 1
        }
      }
      ;(globalThis as any).PointerEvent = _PE
    }
  })

  async function mountReader(): Promise<any> {
    const w = mount(PdfReader, {
      props: { bookId: 'b1', title: '测试 PDF' },
    })
    await flushPromises()
    await flushPromises()
    return w
  }

  it('链接热区真的能点，且点了先弹确认框（不直接打开）', async () => {
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    const w = await mountReader()

    const links = w.findAll('[data-pdf-link]')
    expect(links.length, '链接热区没渲染 ⇒ 那就是「看起来能点」的假链接').toBe(2)

    await links[0].trigger('click')
    await flushPromises()

    // 确认框出现，且**还没**真的打开
    expect(w.text()).toContain('要打开这个外部链接')
    expect(w.text()).toContain('https://example.com/x')
    expect(open).not.toHaveBeenCalled()

    // 点「打开」才真的去
    const okBtn = w.findAll('button').find((b: any) => b.text() === '打开')
    await okBtn.trigger('click')
    await flushPromises()
    expect(open).toHaveBeenCalledWith('https://example.com/x', '_blank', 'noopener,noreferrer')
  })

  it('「取消」不出站', async () => {
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    const w = await mountReader()

    await w.findAll('[data-pdf-link]')[0].trigger('click')
    await flushPromises()
    const cancel = w.findAll('button').find((b: any) => b.text() === '取消')
    await cancel.trigger('click')
    await flushPromises()

    expect(open).not.toHaveBeenCalled()
    expect(w.text()).not.toContain('要打开这个外部链接')
  })

  it('非 http(s) 的外链（javascript:）**不放行**', async () => {
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    const w = await mountReader()

    // 第二条热区是 javascript: —— 点了也要弹确认，但「打开」时不得真的导航
    await w.findAll('[data-pdf-link]')[1].trigger('click')
    await flushPromises()
    const okBtn = w.findAll('button').find((b: any) => b.text() === '打开')
    await okBtn.trigger('click')
    await flushPromises()

    expect(open).not.toHaveBeenCalled()
  })

  it('非链接注释（Square）不画热区', async () => {
    const w = await mountReader()
    // 只有两条 Link ⇒ 两个热区（Square 被跳过）
    expect(w.findAll('[data-pdf-link]').length).toBe(2)
  })

  it('拖拽平移：内容装不下才接管拖拽（装得下时留给「选中文字」）', async () => {
    const w = await mountReader()
    // 滚动容器 = 带 `overflow-auto` 的那层（`boxRef` 指向它）
    const box = w.find('.overflow-auto').element as HTMLElement
    // happy-dom 里所有尺寸都是 0 ⇒ 造一个「装得下」的场景先验一遍
    Object.defineProperty(box, 'scrollHeight', { value: 100, configurable: true })
    Object.defineProperty(box, 'clientHeight', { value: 100, configurable: true })
    Object.defineProperty(box, 'scrollWidth', { value: 100, configurable: true })
    Object.defineProperty(box, 'clientWidth', { value: 100, configurable: true })

    await box.dispatchEvent(new PointerEvent('pointerdown', {
      bubbles: true, button: 0, clientX: 10, clientY: 10,
    }))
    await flushPromises()
    // 装得下 ⇒ 不该接管拖拽（否则用户选不了字）
    expect(box.style.cursor).not.toBe('grabbing')
  })

  it('拖拽平移：装不下时按住拖动 ⇒ 滚动位置跟着走', async () => {
    const w = await mountReader()
    const box = w.find('.overflow-auto').element as HTMLElement
    Object.defineProperty(box, 'scrollHeight', { value: 900, configurable: true })
    Object.defineProperty(box, 'clientHeight', { value: 100, configurable: true })
    Object.defineProperty(box, 'scrollWidth', { value: 900, configurable: true })
    Object.defineProperty(box, 'clientWidth', { value: 100, configurable: true })
    // happy-dom 的 scrollTop/scrollLeft 是只读的 accessor ⇒ 换成自己记值的替身
    const scroll = { top: 0, left: 0 }
    Object.defineProperty(box, 'scrollTop', { get: () => scroll.top, set: (v) => { scroll.top = v }, configurable: true })
    Object.defineProperty(box, 'scrollLeft', { get: () => scroll.left, set: (v) => { scroll.left = v }, configurable: true })

    await box.dispatchEvent(new PointerEvent('pointerdown', {
      bubbles: true, button: 0, clientX: 100, clientY: 100,
    }))
    await box.dispatchEvent(new PointerEvent('pointermove', {
      bubbles: true, clientX: 60, clientY: 70,
    }))
    await flushPromises()
    // 手指往上/往左挪 ⇒ 内容跟着往回看（scroll 变大）
    expect(scroll.top).toBe(30)
    expect(scroll.left).toBe(40)
  })
})
