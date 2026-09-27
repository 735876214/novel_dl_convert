import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'

import { api, type AllAnnotation, type AnnotationOverview, type KoreaderImportResult } from '@/lib/api'
import { useLibraryStore } from '@/stores/library'
import { useUiStore } from '@/stores/ui'
import AnnotationsView from '@/views/AnnotationsView.vue'

/**
 * `@/lib/api` 整体替换（与 `BookDetailView.spec.ts` 同一套理由：桩要一次给齐，
 * 少一个会在 `onMounted` 里抛，而那个异常被 `catch` 吞成「加载失败」——
 * 用例随后以「找不到元素」的形式报错，离真正的原因很远）。
 *
 * 这里多一条：**`importKoreaderAnnotations` 是全页唯一会写库的调用**。
 * 用例不仅要它的返回值，还要它的**调用参数**（`apply` 的真假）——
 * dry-run 与落库的区别全在那个布尔上，返回的 `applied` 字段只是服务端回声。
 */
vi.mock('@/lib/api', () => ({
  api: {
    allAnnotations: vi.fn(),
    annotationOverview: vi.fn(),
    importKoreaderAnnotations: vi.fn(),
    deleteAnnotation: vi.fn(),
    restoreAnnotation: vi.fn(),
    purgeAnnotation: vi.fn(),
    exportAnnotations: vi.fn(),
  },
  apiErrorMessage: (_e: unknown, fallback: string) => fallback,
}))

const m = {
  allAnnotations: vi.mocked(api.allAnnotations),
  annotationOverview: vi.mocked(api.annotationOverview),
  importKoreaderAnnotations: vi.mocked(api.importKoreaderAnnotations),
}

let router: Router

function makeAnno(over: Partial<AllAnnotation> = {}): AllAnnotation {
  return {
    id: 1,
    book_id: 'lib$aaa',
    book_title: '三体',
    book_author: '刘慈欣',
    chapter: 4,
    quote: '不要回答',
    color: 'yellow',
    note: '',
    style: 'highlight',
    created_at: 1700000000,
    origin: 'web',
    deleted_at: 0,
    ...over,
  }
}

/** KC 的返回体：dry-run 时 `totals` 全是 0（一条没落库），条数要从每个文件的 `items` 累。 */
function makeImport(over: Partial<KoreaderImportResult> = {}): KoreaderImportResult {
  const files = over.files ?? [
    { path: '/lib/三体.epub.sdr/三体.epub.annotations.lua', book: '三体.epub', book_id: 'lib$aaa', error: '', items: 3, skipped: 1, device_id: 'dev-1', stats: {} },
  ]
  return {
    applied: false,
    scanned: files.length,
    with_file: files.filter((f) => !f.error).length,
    unmatched: [],
    files,
    totals: { added: 0, updated: 0, unchanged: 0, trashed: 0, no_anchor: 0, no_quote: 0, skipped: files.reduce((n, f) => n + f.skipped, 0), files: files.length },
    ...over,
  }
}

async function mountView(): Promise<VueWrapper> {
  const w = mount(AnnotationsView, { global: { plugins: [router] } })
  await flushPromises()
  return w
}

/** 页面上的可点按钮文案（去掉图标等子节点带来的空白） */
function buttonTexts(w: VueWrapper): string[] {
  return w.findAll('button').map((b) => b.text().replace(/\s+/g, ' ').trim())
}

beforeEach(async () => {
  setActivePinia(createPinia())
  m.allAnnotations.mockResolvedValue({ items: [makeAnno()], total: 1 })
  m.annotationOverview.mockResolvedValue({
    active: 1, trashed: 0, weeks: 1, longest_quiet_weeks: 0,
  } satisfies AnnotationOverview)
  m.importKoreaderAnnotations.mockResolvedValue(makeImport())

  router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/annotations', name: 'annotations', component: AnnotationsView },
      { path: '/read/:id', name: 'read', component: { template: '<div />' } },
    ],
  })
  await router.push('/annotations')
  await router.isReady()
})

describe('AnnotationsView 的章节显示', () => {
  it('序号未知的批注显示设备给的标题，且**不可点**（跳过去只会落到章首）', async () => {
    m.allAnnotations.mockResolvedValue({
      items: [
        makeAnno({ id: 1, chapter: 4, quote: '本应用划的', origin: 'web' }),
        makeAnno({ id: 2, chapter: -1, chapter_title: '第十二章 夜航', quote: '设备来的', origin: 'koreader' }),
      ],
      total: 2,
    })
    const w = await mountView()

    expect(w.text()).toContain('第十二章 夜航')
    expect(w.text()).not.toContain('第 1 章')
    // 已知序号那条照旧（后端 0 基 → 界面 1 基）
    expect(w.text()).toContain('第 5 章')

    // 序号未知的渲染成 <p>（不可点），已知的渲染成 <button> —— 按标签判，不按文案猜
    expect(w.findAll('p').some((p) => p.text().includes('第十二章 夜航'))).toBe(true)
    expect(w.findAll('button').some((b) => b.text().includes('第十二章 夜航'))).toBe(false)
    expect(w.findAll('button').some((b) => b.text().includes('第 5 章'))).toBe(true)
  })

  it('点已知序号那条会带上 ?chapter=', async () => {
    m.allAnnotations.mockResolvedValue({ items: [makeAnno({ chapter: 4 })], total: 1 })
    const w = await mountView()

    const link = w.findAll('button').find((b) => b.text().includes('第 5 章'))
    expect(link).toBeTruthy()
    await link!.trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.fullPath).toBe('/read/lib$aaa?chapter=4')
  })
})

describe('AnnotationsView 的 KOReader 导入是两步走', () => {
  it('「从 KOReader 导入」只跑 dry-run（apply=false），并报出会导多少条', async () => {
    const w = await mountView()

    const btn = w.findAll('button').find((b) => b.text().includes('从 KOReader 导入'))
    expect(btn).toBeTruthy()
    await btn!.trigger('click')
    await flushPromises()

    // **关键断言**：第一次调用必须是 false —— 点了按钮就写库是这个流程要避免的事
    expect(m.importKoreaderAnnotations).toHaveBeenCalledTimes(1)
    expect(m.importKoreaderAnnotations).toHaveBeenCalledWith(false)

    // 确认条出现，条数来自 files[].items（dry-run 的 totals 全是 0，不能读它）
    expect(w.text()).toContain('3')
    expect(w.text()).toContain('确认导入')
    // 还没确认，不能再写
    expect(m.importKoreaderAnnotations).toHaveBeenCalledTimes(1)
  })

  it('点「确认导入」才落库（apply=true），随后重新拉列表', async () => {
    const w = await mountView()
    await w.findAll('button').find((b) => b.text().includes('从 KOReader 导入'))!.trigger('click')
    await flushPromises()

    m.importKoreaderAnnotations.mockResolvedValue(
      makeImport({ applied: true, totals: { added: 3, updated: 0, unchanged: 0, trashed: 0, no_anchor: 0, no_quote: 0, skipped: 1, files: 1 } }),
    )
    const before = m.allAnnotations.mock.calls.length

    await w.findAll('button').find((b) => b.text() === '确认导入')!.trigger('click')
    await flushPromises()

    expect(m.importKoreaderAnnotations).toHaveBeenLastCalledWith(true)
    // 导完要刷新列表 —— 否则刚导进来的批注要等用户手动刷新才出现
    expect(m.allAnnotations.mock.calls.length).toBeGreaterThan(before)
    // 确认条收起
    expect(w.text()).not.toContain('确认导入')
    // 提示条走 store（`App.vue` 渲染它，本页的 wrapper 里看不到那个 DOM）——
    // 所以断言状态本身，不去 `w.text()` 里找
    expect(useUiStore().toastMessage).toContain('已导入 3 条')
  })

  it('「取消」只收起确认条，不落库', async () => {
    const w = await mountView()
    await w.findAll('button').find((b) => b.text().includes('从 KOReader 导入'))!.trigger('click')
    await flushPromises()

    await w.findAll('button').find((b) => b.text() === '取消')!.trigger('click')
    await flushPromises()

    expect(w.text()).not.toContain('确认导入')
    expect(m.importKoreaderAnnotations).toHaveBeenCalledTimes(1) // 只有那次 dry-run
  })

  it('一个文件都没找到 ⇒ 说没找到，且不给「确认导入」', async () => {
    m.importKoreaderAnnotations.mockResolvedValue(makeImport({ scanned: 0, with_file: 0, files: [] }))
    const w = await mountView()
    await w.findAll('button').find((b) => b.text().includes('从 KOReader 导入'))!.trigger('click')
    await flushPromises()

    expect(w.text()).toContain('没找到 KOReader 的导出文件')
    expect(buttonTexts(w)).not.toContain('确认导入')
  })

  it('文件读不懂时如实报出来，不混进「可导入」的条数里', async () => {
    m.importKoreaderAnnotations.mockResolvedValue(makeImport({
      files: [
        { path: '/lib/三体.epub.sdr/x.lua', book: '三体.epub', book_id: 'lib$aaa', error: 'expecting value at 12', items: 0, skipped: 0, device_id: '', stats: {} },
      ],
    }))
    const w = await mountView()
    await w.findAll('button').find((b) => b.text().includes('从 KOReader 导入'))!.trigger('click')
    await flushPromises()

    expect(w.text()).toContain('没能解析')
    expect(buttonTexts(w)).not.toContain('确认导入')
  })
})

describe('AnnotationsView 的空态', () => {
  it('摆本机阅读器与 KOReader 两张卡，**不摆 Kobo**（那条路没实现）', async () => {
    m.allAnnotations.mockResolvedValue({ items: [], total: 0 })
    m.annotationOverview.mockResolvedValue({ active: 0, trashed: 0, weeks: 0, longest_quiet_weeks: 0 })
    const w = await mountView()

    expect(w.text()).toContain('本应用阅读器')
    expect(w.text()).toContain('KOReader')
    // 卡片标题**逐个列出来**，不是 `toContain` —— 加一张 Kobo 卡不会让 toContain 变红，
    // 而「摆了 Kobo 卡」正是这条要防的（那个来源没有接入路径，摆了就是假承诺）
    expect(w.findAll('h3').map((h) => h.text())).toEqual(['本应用阅读器', 'KOReader'])
  })

  it('空态那张卡上的导入按钮也是 dry-run，不直接写库', async () => {
    m.allAnnotations.mockResolvedValue({ items: [], total: 0 })
    m.annotationOverview.mockResolvedValue({ active: 0, trashed: 0, weeks: 0, longest_quiet_weeks: 0 })
    const w = await mountView()

    // 空态卡片里也有一个「从 KOReader 导入」——恰恰是一条批注都没有时最需要它
    const btn = w.findAll('button').find((b) => b.text().includes('从 KOReader 导入'))
    expect(btn).toBeTruthy()
    await btn!.trigger('click')
    await flushPromises()

    expect(m.importKoreaderAnnotations).toHaveBeenCalledWith(false)
  })
})

describe('AnnotationsView 的分组口径', () => {
  it('按来源分组时用中文名，未知来源原样显示', async () => {
    m.allAnnotations.mockResolvedValue({
      items: [
        makeAnno({ id: 1, origin: 'koreader', chapter: -1, chapter_title: '第十二章' }),
        makeAnno({ id: 2, origin: 'calibre', quote: '别的来源' }),
      ],
      total: 2,
    })
    const w = await mountView()

    await w.findAll('button').find((b) => b.text() === '按来源')!.trigger('click')
    await flushPromises()

    const heads = w.findAll('h3').map((h) => h.text().replace(/\s+/g, ' ').trim())
    expect(heads.some((t) => t.startsWith('KOReader'))).toBe(true)
    // 未知来源不盖成「其他」
    expect(heads.some((t) => t.startsWith('calibre'))).toBe(true)
    expect(w.text()).not.toContain('其他')
    // 用到了 store 才不会有「未使用导入」的疑问（这一句同时钉住 store 可注入）
    expect(useLibraryStore().currentLibraryId).toBe('')
  })
})
