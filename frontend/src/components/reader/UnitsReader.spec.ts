import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import { defineComponent, h } from 'vue'

import { api, type UnitItem, type UnitRef } from '@/lib/api'
import UnitsReader from '@/components/reader/UnitsReader.vue'

/**
 * 第 73 期：序号单元合集阅读器（**进度独占写入**的那一半）。
 *
 * 三个子阅读器（PDF / 漫画 / 音频）在这里整只换成桩：本文件要钉的不是它们怎么渲染，
 * 而是它们与本组件之间的**协议** —— 谁写进度、什么时候写、过期上报怎么处理。
 * 「换话时旧话的收尾上报把进度写回旧话」这类缺陷没有报错、界面上也看不出来，
 * 只有用例守得住。
 */
vi.mock('@/lib/api', () => ({
  api: { getProgress: vi.fn(), setProgress: vi.fn() },
}))

const m = {
  getProgress: vi.mocked(api.getProgress),
  setProgress: vi.mocked(api.setProgress),
}

/**
 * 子阅读器桩。用 `h()` 而不是 `template:` —— 运行期模板编译要完整版 Vue，
 * 本仓库的 vitest 走的是 bundler 版（既有 spec 里那些 `{ template: '<div />' }`
 * 的路由占位从来不渲染，所以从没暴露过）。渲染函数没有这个前提。
 */
function mkStub(name: 'pdf' | 'comic' | 'audio') {
  return defineComponent({
    name,
    props: {
      bookId: String,
      title: String,
      series: String,
      unit: Object,
      autoplay: Boolean,
      tracks: Array,
      source: String,
      comicLib: Boolean,
      fileRel: String,
    },
    emits: ['unitPos', 'unitEnd', 'pdfMode'],
    setup: () => () => h('div', { class: `stub-${name}` }),
  })
}

const PdfStub = mkStub('pdf')
const ComicStub = mkStub('comic')
const AudioStub = mkStub('audio')

const STUBS = [
  ['.stub-pdf', PdfStub],
  ['.stub-comic', ComicStub],
  ['.stub-audio', AudioStub],
] as const

const NEXT = 'button[title="下一话"]'
const PREV = 'button[title="上一话"]'

function makeUnits(kinds: Array<'pdf' | 'comic' | 'audio'>): UnitItem[] {
  const ext = { pdf: 'pdf', comic: 'cbz', audio: 'mp3' } as const
  return kinds.map((kind, i) => ({
    index: i,
    name: `第1卷/第${i + 1}话.${ext[kind]}`,
    num: i + 1,
    kind,
    size: 10,
  }))
}

/** 挂载并等恢复那一次取数落地（`ready` 之前子阅读器不渲染，也就找不到桩） */
async function mountUnits(
  units = makeUnits(['pdf', 'comic', 'pdf', 'pdf']),
  bookId = 'u1',
): Promise<{ wrapper: VueWrapper; router: Router }> {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/', component: { render: () => h('div') } }],
  })
  // ⚠️ 这里**不能** `await router.isReady()`：router 的首次导航是在 `app.use(router)`
  // （即下面的 `mount`）才发起的，而 `isReady()` 在首次导航之前**不会 resolve** ——
  // 先 await 它就永远是死等，表现是每个用例都超时（实测过一次）。
  const wrapper = mount(UnitsReader, {
    props: { bookId, title: '转生魔女宣告毁灭', series: '', units },
    global: {
      plugins: [router],
      stubs: { PdfReader: PdfStub, ComicReader: ComicStub, AudioPlayer: AudioStub },
    },
  })
  await flushPromises()
  return { wrapper, router }
}

/** 当前挂着的那个子阅读器桩（同一时刻只有一个） */
function child(wrapper: VueWrapper): VueWrapper {
  for (const [cls, def] of STUBS) {
    if (wrapper.find(cls).exists()) return wrapper.findComponent(def)
  }
  throw new Error('没有子阅读器被渲染')
}

/**
 * 桩上的 props（三个桩形状相同，本文件只读这两个）。
 *
 * 走 `.props()` 整取再断言，而不是 `.props('unit')`：`child()` 的返回类型是三个桩的
 * 联合，按名字取的话 TS 把可选键收成 `never`，用例反而编译不过。
 */
function stubProps(wrapper: VueWrapper): { unit?: UnitRef; autoplay?: boolean } {
  return child(wrapper).props() as { unit?: UnitRef; autoplay?: boolean }
}

/** 点「下一话」并等两笔写入走完 */
async function goNext(wrapper: VueWrapper): Promise<void> {
  await wrapper.find(NEXT).trigger('click')
  await flushPromises()
}

/** 上一次 `setProgress` 的实参 */
function lastWrite(): unknown[] {
  const calls = m.setProgress.mock.calls
  return calls[calls.length - 1] as unknown as unknown[]
}

beforeEach(() => {
  setActivePinia(createPinia())
  m.getProgress.mockResolvedValue({ locator: 0, percent: 0, cfi: '', updated_at: 0, file_rel: null })
  m.setProgress.mockResolvedValue({ ok: true, updated_at: 1 })
})

describe('UnitsReader · 分派与恢复', () => {
  it('按当前话的种类选阅读器（pdf / comic / audio 三种各挂对）', async () => {
    const { wrapper } = await mountUnits(makeUnits(['comic', 'pdf', 'audio']))
    expect(wrapper.find('.stub-comic').exists()).toBe(true)

    await goNext(wrapper)
    expect(wrapper.find('.stub-pdf').exists()).toBe(true)

    await goNext(wrapper)
    expect(wrapper.find('.stub-audio').exists()).toBe(true)
  })

  it('恢复：书级 percent 反解成「第几话 + 话内比例」交给子阅读器', async () => {
    // 4 话的书读到 62.5% ⇒ 第 3 话（下标 2）的一半
    m.getProgress.mockResolvedValue({ locator: 5, percent: 62.5, cfi: '', updated_at: 9, file_rel: null })
    const { wrapper } = await mountUnits()

    const unit = stubProps(wrapper).unit
    expect(unit?.index).toBe(2)
    expect(unit?.total).toBe(4)
    expect(unit?.within).toBeCloseTo(0.5, 10)
    expect(wrapper.text()).toContain('3 / 4')
  })
})

describe('UnitsReader · 进度独占写入', () => {
  it('子阅读器上报 ⇒ 本组件按同一份算式写库，且**不取整**', async () => {
    const { wrapper } = await mountUnits()
    await goNext(wrapper)
    await goNext(wrapper)                       // 现在在第 3 话（下标 2）

    child(wrapper).vm.$emit('unitPos', { index: 2, within: 0.9, locator: 5 })
    await flushPromises()

    // (2 + 0.9) / 4 × 100 = 72.5 —— 写成整数就会把话内位置抹掉（见 unitsProgress.spec）
    expect(lastWrite()).toEqual(['u1', 5, 72.5])
  })

  it('**过期上报一律丢弃**：旧话卸载时的那一次不能把位置写回旧话', async () => {
    const { wrapper } = await mountUnits()
    await goNext(wrapper)
    await goNext(wrapper)                       // 现在在第 3 话（下标 2）

    child(wrapper).vm.$emit('unitPos', { index: 2, within: 0.5, locator: 3 })
    await flushPromises()
    const before = m.setProgress.mock.calls.length

    // 换话那一刻，**旧话**那个组件会在卸载钩子里再报一次（载荷里的 index 是旧的）。
    // 上层手里的 index 已经是新话，不核对就会把「第 3 话读到一半」写成「第 2 话读到九成」。
    child(wrapper).vm.$emit('unitPos', { index: 1, within: 0.9, locator: 8 })
    await flushPromises()
    expect(m.setProgress.mock.calls.length).toBe(before)
  })

  it('读完一话 ⇒ 换话，并把「旧话末尾」与「新话开头」**按顺序**各写一笔', async () => {
    const { wrapper } = await mountUnits()
    child(wrapper).vm.$emit('unitPos', { index: 0, within: 1, locator: 9 })
    child(wrapper).vm.$emit('unitEnd')
    await flushPromises()

    const calls = m.setProgress.mock.calls
    expect(calls[calls.length - 2]).toEqual(['u1', 9, 25])   // 旧话末尾
    expect(calls[calls.length - 1]).toEqual(['u1', 0, 25])   // 新话开头（同一个位置）
    expect(wrapper.text()).toContain('2 / 4')
  })

  it('自动续过来时音频拿到 autoplay；用户自己点「下一话」不自动播', async () => {
    const { wrapper } = await mountUnits(makeUnits(['audio', 'audio', 'audio']))
    expect(stubProps(wrapper).autoplay).toBe(false)

    child(wrapper).vm.$emit('unitEnd')
    await flushPromises()
    expect(stubProps(wrapper).autoplay).toBe(true)           // 接着放

    await goNext(wrapper)                                    // 「我要看这一话」
    expect(stubProps(wrapper).autoplay).toBe(false)
  })

  it('离开阅读器时补写当前位置（子阅读器的最后一次上报可能已隔了几秒）', async () => {
    const { wrapper } = await mountUnits()
    await goNext(wrapper)
    await goNext(wrapper)
    child(wrapper).vm.$emit('unitPos', { index: 2, within: 0.5, locator: 4 })
    await flushPromises()
    const before = m.setProgress.mock.calls.length

    wrapper.unmount()
    await flushPromises()
    expect(m.setProgress.mock.calls.length).toBe(before + 1)
    expect(lastWrite()).toEqual(['u1', 4, 62.5])
  })

  it('最后一话不再往后换（按钮置灰），读到末尾也不越界', async () => {
    const { wrapper } = await mountUnits(makeUnits(['pdf']))
    expect(wrapper.find(NEXT).attributes('disabled')).toBeDefined()
    expect(wrapper.find(PREV).attributes('disabled')).toBeDefined()

    child(wrapper).vm.$emit('unitEnd')
    await flushPromises()
    expect(wrapper.text()).toContain('1 / 1')
  })

  it('翻回上一话同样只写不读：进度由本组件按新话重算', async () => {
    const { wrapper } = await mountUnits()
    await goNext(wrapper)
    child(wrapper).vm.$emit('unitPos', { index: 1, within: 0.5, locator: 2 })
    await flushPromises()

    await wrapper.find(PREV).trigger('click')
    await flushPromises()
    expect(lastWrite()).toEqual(['u1', 0, 0])                // 回到第 1 话开头
    expect(wrapper.text()).toContain('1 / 4')
  })
})
