import { flushPromises, mount, type DOMWrapper, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import {
  api,
  type SearchHit,
  type SearchSourceState,
  type SourceStatus,
  type TaskItem,
} from '@/lib/api'
import { useLibraryStore } from '@/stores/library'
import ExploreView from '@/views/ExploreView.vue'

/**
 * `@/lib/api` 整体替换，桩要**一次给齐**：少一个就会在 `onMounted`（读闸门状态）
 * 或点「下载」时抛，用例随后会以「找不到按钮 / 文本对不上」的形式报错，离原因很远。
 *
 * `apiErrorMessage` 不 mock 成真实实现（那要构造 `{"detail":"…"}` 的错误对象），
 * 这里就回 fallback —— 本文件要断言的是**视图行为**，不是剥壳函数（它有全站共用的实现）。
 */
vi.mock('@/lib/api', () => ({
  api: {
    search: vi.fn(),
    sourcesStatus: vi.fn(),
    preview: vi.fn(),
    download: vi.fn(),
    tasks: vi.fn(),
  },
  apiErrorMessage: (_e: unknown, fallback: string) => fallback,
}))

const m = {
  search: vi.mocked(api.search),
  sourcesStatus: vi.mocked(api.sourcesStatus),
  preview: vi.mocked(api.preview),
  download: vi.mocked(api.download),
  tasks: vi.mocked(api.tasks),
}

/** 逐源状态（第 71 期 `/api/search` 的 `sources[]`） */
function srcState(name: string, patch: Partial<SearchSourceState> = {}): SearchSourceState {
  return {
    name,
    display_name: `${name} 展示名`,
    ok: true,
    count: 1,
    error: '',
    skipped: false,
    reason: '',
    has_more: false,
    ...patch,
  }
}

/**
 * 造一条命中。字段与后端 `_mark()` 的产出一致 —— 包括 `source_name`：
 * 它是**展示名**（`display_name`），徽章优先显示它，缺了才回落源名。
 */
function hit(source: string, title: string, author = '刘慈欣', url = ''): SearchHit {
  return {
    source,
    title,
    author,
    url: url || `https://e.com/${source}/${title}`,
    source_name: `${source} 展示名`,
  }
}

function page(results: SearchHit[], sources: SearchSourceState[], hasMore = false, p = 1) {
  return { count: results.length, results, sources, has_more: hasMore, page: p }
}

/** 任务表的一行（本文件只关心 `status` / `error`，其余字段照 `TaskItem` 填齐） */
function taskItem(patch: Partial<TaskItem> = {}): TaskItem {
  return {
    id: 't1',
    type: 'download',
    title: '三体',
    detail: 'gutenberg · epub',
    status: 'queued',
    progress: 0,
    error: '',
    result: '',
    name: '',
    notice: '',
    actor: 'admin',
    created_at: 0,
    updated_at: 0,
    ...patch,
  }
}

/** `/api/sources/status` 的一行（视图只读 `download_enabled` 与 `blocked_reason`） */
function status(patch: Partial<SourceStatus> = {}): SourceStatus {
  return {
    name: 'gutenberg',
    display_name: 'Project Gutenberg',
    domains: ['gutenberg.org'],
    public: true,
    user: false,
    download_enabled: true,
    cookie: { has: false, mtime: null, size: 0 },
    usable: true,
    blocked_reason: '',
    ...patch,
  }
}

/** 按文案取按钮：找不到时把现有按钮全列出来，省得回去猜 DOM */
function button(w: VueWrapper, label: string, index = 0): DOMWrapper<Element> {
  const found = w.findAll('button').filter((b) => b.text().includes(label))
  const el = found[index]
  if (!el) {
    throw new Error(`找不到按钮「${label}」；现有：${w.findAll('button').map((b) => b.text()).join(' / ')}`)
  }
  return el
}

/** 结果行里的「下载」按钮数：一书一行时每行一个，展开后每个来源一个 */
const downloadButtons = (w: VueWrapper): number =>
  w.findAll('button').filter((b) => b.text() === '下载').length

async function mountExplore(): Promise<VueWrapper> {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/explore', component: ExploreView },
      { path: '/settings/ext/network', component: { template: '<div>网络与下载</div>' } },
    ],
  })
  await router.push('/explore')
  await router.isReady()
  const wrapper = mount(ExploreView, { global: { plugins: [router] } })
  await flushPromises()
  return wrapper
}

async function searchFor(w: VueWrapper, word = '三体'): Promise<void> {
  await w.find('input[aria-label="搜索书名"]').setValue(word)
  await button(w, '检索').trigger('click')
  await flushPromises()
}

beforeEach(() => {
  // 新建的 store：`librariesLoaded` 为假 ⇒ `hasNoLibraries` 为假（判据是「拉取成功**且**
  // 一个库都没有」），下载路径畅通。0 库那条用例自己把两种状态都设出来。
  setActivePinia(createPinia())
  vi.clearAllMocks()
  m.sourcesStatus.mockResolvedValue({ items: [status()] })
  m.tasks.mockResolvedValue({ items: [], count: 0 })
  m.download.mockResolvedValue({ task_id: 't1' })
  m.preview.mockResolvedValue({ toc: ['第一章'], sample: '正文片段' })
})

describe('ExploreView · 来源字段（第 71 期修掉的老 bug）', () => {
  /**
   * 第 71 期之前后端只写 `_source`，而这里读 `hit.source` ⇒ 结果是 `undefined`：
   * 来源徽章空白、`GET /api/preview?source=undefined` 被后端拒成
   * 502「未知书源: undefined」。这条把「预览真的带上了书源名」钉住。
   */
  it('预览用 hit.source 请求（不是 undefined）', async () => {
    m.search.mockResolvedValue(page([hit('gutenberg', '三体', '刘慈欣', 'https://e.com/1')], [srcState('gutenberg')]))
    const w = await mountExplore()
    await searchFor(w)

    await button(w, '预览').trigger('click')
    await flushPromises()

    expect(m.preview).toHaveBeenCalledWith('gutenberg', 'https://e.com/1')
    expect(w.text()).toContain('共 1 章')
    expect(w.text()).toContain('正文片段')
  })

  it('来源徽章显示源名（不是空白）', async () => {
    m.search.mockResolvedValue(page([hit('gutenberg', '三体')], [srcState('gutenberg')]))
    const w = await mountExplore()
    await searchFor(w)

    expect(w.text()).toContain('gutenberg 展示名')
  })
})

describe('ExploreView · 同名合并（一书一行）', () => {
  it('同名同作者跨源合并成一行，展开后每个来源各自可下载', async () => {
    m.search.mockResolvedValue(page(
      [hit('gutenberg', '《三体》', '刘慈欣', 'u1'), hit('other', '三体', '刘慈欣', 'u2')],
      [srcState('gutenberg'), srcState('other')],
    ))
    const w = await mountExplore()
    await searchFor(w)

    expect(downloadButtons(w)).toBe(1)
    expect(w.text()).toContain('2 条来源')
    expect(w.text()).toContain('共 2 条命中 · 1 本')

    await button(w, '2 条来源').trigger('click')
    await flushPromises()

    expect(downloadButtons(w)).toBe(2)
  })

  it('同名不同作者不合并（宁可不并，也不把两本书并成一本）', async () => {
    m.search.mockResolvedValue(page(
      [hit('a', '三体', '刘慈欣', 'u1'), hit('b', '三体', '另一个人', 'u2')],
      [srcState('a'), srcState('b')],
    ))
    const w = await mountExplore()
    await searchFor(w)

    expect(downloadButtons(w)).toBe(2)
    expect(w.text()).not.toContain('条来源')
    expect(w.text()).toContain('共 2 条命中 · 2 本')
  })
})

describe('ExploreView · 逐源状态如实显示', () => {
  /**
   * 第 71 期之前后端不返回逐源状态，界面那条「部分书源检索失败」永远不显示。
   * 现在：一行汇总 + 展开看每个源的原文原因，且**失败与跳过分开**（该去看源 vs 该去改设置）。
   */
  it('失败的源给出原因原文，与「被跳过」分开计数', async () => {
    m.search.mockResolvedValue(page(
      [hit('ok-src', '三体')],
      [
        srcState('ok-src'),
        srcState('boom-src', { ok: false, error: '连接失败：域名不在白名单内' }),
        srcState('off-src', { ok: false, skipped: true, reason: '下载功能未开启：到「设置 → 网络与下载」打开「开放搜索 / 下载」' }),
      ],
    ))
    const w = await mountExplore()
    await searchFor(w)

    expect(w.text()).toContain('已查 3 个源')
    expect(w.text()).toContain('成功 1')
    expect(w.text()).toContain('失败 1')
    expect(w.text()).toContain('被跳过 1')

    await button(w, '详情').trigger('click')
    await flushPromises()

    expect(w.text()).toContain('连接失败：域名不在白名单内')
    // 「被跳过」的原因原文也要显示（第 93 期删掉「仅放行公版源」后，跳过只剩「下载未开启」一种成因）
    expect(w.text()).toContain('下载功能未开启')
  })

  it('一个源都没有时说「没有可用的书源」，而不是「没有找到结果」', async () => {
    m.search.mockResolvedValue(page([], []))
    const w = await mountExplore()
    await searchFor(w)

    expect(w.text()).toContain('没有可用的书源')
    expect(w.text()).not.toContain('没有找到结果')
  })
})

describe('ExploreView · 加载更多（追加，不覆盖）', () => {
  it('第二页**追加**到第一页之后，取完就收起按钮', async () => {
    m.search
      .mockResolvedValueOnce(page([hit('a', '三体', '刘慈欣', 'u1')], [srcState('a')], true, 1))
      .mockResolvedValueOnce(page([hit('a', '球状闪电', '刘慈欣', 'u2')], [srcState('a')], false, 2))
    const w = await mountExplore()
    await searchFor(w)

    expect(downloadButtons(w)).toBe(1)
    await button(w, '加载更多').trigger('click')
    await flushPromises()

    expect(m.search).toHaveBeenLastCalledWith('三体', 2, expect.anything())
    expect(downloadButtons(w)).toBe(2)
    expect(w.text()).toContain('三体')
    expect(w.text()).toContain('球状闪电')
    expect(() => button(w, '加载更多')).toThrow()
  })

  /** 规则源的 `{page}` 只表示「模板支持翻页」：站点不认参数时会一直回吐同一页。 */
  it('这一页没带来新条目时收起「加载更多」（否则按钮永远点得动却是假交互）', async () => {
    const same = hit('a', '三体', '刘慈欣', 'u1')
    m.search
      .mockResolvedValueOnce(page([same], [srcState('a')], true, 1))
      .mockResolvedValueOnce(page([{ ...same }], [srcState('a')], true, 2))
    const w = await mountExplore()
    await searchFor(w)

    await button(w, '加载更多').trigger('click')
    await flushPromises()

    expect(downloadButtons(w)).toBe(1)
    expect(() => button(w, '加载更多')).toThrow()
  })

  it('逐源计数跨页累加（翻页后「成功 N 条」不该反而变小）', async () => {
    m.search
      .mockResolvedValueOnce(page([hit('a', '三体', '刘慈欣', 'u1')], [srcState('a', { count: 1 })], true, 1))
      .mockResolvedValueOnce(page([hit('a', '球状闪电', '刘慈欣', 'u2')], [srcState('a', { count: 1 })], false, 2))
    const w = await mountExplore()
    await searchFor(w)

    await button(w, '加载更多').trigger('click')
    await flushPromises()
    await button(w, '详情').trigger('click')
    await flushPromises()

    expect(w.text()).toContain('2 条')
  })
})

describe('ExploreView · 下载闸门（不搞成「点了才报错」）', () => {
  /**
   * `download.enabled` 默认就是关的：进页面先读 `/api/sources/status`，
   * 把搜索框与按钮置灰、把**后端给的原因原文**摆出来并给出口（第 71 期）。
   */
  it('下载关着时置灰检索并给出出口', async () => {
    m.sourcesStatus.mockResolvedValue({
      items: [status({
        download_enabled: false,
        usable: false,
        blocked_reason: '下载功能未开启：到「设置 → 网络与下载」打开「开放搜索 / 下载」',
      })],
    })
    const w = await mountExplore()

    expect(w.text()).toContain('下载功能未开启')
    expect(w.find('input[aria-label="搜索书名"]').attributes('disabled')).toBeDefined()
    expect(button(w, '检索').attributes('disabled')).toBeDefined()
    expect(w.find('a[href="/settings/ext/network"]').exists()).toBe(true)
    expect(m.search).not.toHaveBeenCalled()
  })

  it('闸门状态读不到时不误拦（真的被拒时后端会带回原因原文）', async () => {
    m.sourcesStatus.mockRejectedValue(new Error('网络不可用'))
    m.search.mockResolvedValue(page([hit('a', '三体')], [srcState('a')]))
    const w = await mountExplore()
    await searchFor(w)

    expect(m.search).toHaveBeenCalled()
    expect(downloadButtons(w)).toBe(1)
  })
})

describe('ExploreView · 行内任务状态', () => {
  it('发起下载后按真实任务状态显示，失败时带上原因原文', async () => {
    m.search.mockResolvedValue(page([hit('a', '三体')], [srcState('a')]))
    m.tasks.mockResolvedValue({
      items: [taskItem({ status: 'failed', error: '没有可接收的书库' })],
      count: 1,
    })
    const w = await mountExplore()
    await searchFor(w)

    await button(w, '下载').trigger('click')
    await flushPromises()

    expect(m.download).toHaveBeenCalledTimes(1)
    expect(w.text()).toContain('失败：没有可接收的书库')
  })

  it('0 库时点下载只提示、不发请求（一次注定失败的往返没必要发）', async () => {
    const library = useLibraryStore()
    library.librariesLoaded = true
    library.libraryEntities = []
    m.search.mockResolvedValue(page([hit('a', '三体')], [srcState('a')]))
    const w = await mountExplore()
    await searchFor(w)

    await button(w, '下载').trigger('click')
    await flushPromises()

    expect(m.download).not.toHaveBeenCalled()
  })
})
