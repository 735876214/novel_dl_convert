import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi, type Mock } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import OnlineReadCard from '@/components/book/detail/OnlineReadCard.vue'
import { api, type OnlineStatus, type SourceStatus } from '@/lib/api'
import { runCheckUpdate } from '@/lib/checkUpdate'

/**
 * 第 93 期：「在线阅读」卡的**判定契约**。
 *
 * 这一块的失效全是静默的（页面照常渲染、按钮照常可点）：
 *   · 把「不能逐章读」的源也渲染成可点 ⇒ 用户绑完点进阅读器才 400（假交互）；
 *   · 把闸门的原因换成自编的一句话 ⇒ 用户不知道该去哪儿打开开关；
 *   · 绑定失败时不显示后端原文 ⇒ 只剩「点了没反应」。
 *
 * ⚠️ 本组件**不自己判**一个源能不能用（`usable` 与 `online_support` 都读后端给的字段）。
 * 这条纪律用第一、二条用例钉住：换一份判据就会红。
 */
vi.mock('@/lib/api', () => ({
  api: {
    onlineStatus: vi.fn(),
    sourcesStatus: vi.fn(),
    onlineBind: vi.fn(),
    onlineUnbind: vi.fn(),
  },
  // 与真实实现同形：有服务端给的原因就用它，没有才用兜底 —— 失败那一条用例
  // 要验的正是「后端原文有没有被显示出来」，写成恒返回 fallback 就测不出来了。
  apiErrorMessage: (e: unknown, fallback: string) =>
    (e instanceof Error && e.message) ? e.message : fallback,
}))

/**
 * 「检查更新 / 整本覆盖」只替掉**执行**那一半（`checkUpdate.spec.ts` 已把轮询 / 报告 /
 * 超时全量钉死）。确认文案取**真实现**（`importActual`）—— 它是「整本重写、进度可能错位」
 * 这句承诺的唯一出处，在这里另抄一份就等于允许它两处漂移。
 */
vi.mock('@/lib/checkUpdate', async () => {
  const actual = await vi.importActual<typeof import('@/lib/checkUpdate')>('@/lib/checkUpdate')
  return { ...actual, runCheckUpdate: vi.fn() }
})

const m = {
  onlineStatus: vi.mocked(api.onlineStatus),
  sourcesStatus: vi.mocked(api.sourcesStatus),
  onlineBind: vi.mocked(api.onlineBind),
  onlineUnbind: vi.mocked(api.onlineUnbind),
  runCheckUpdate: vi.mocked(runCheckUpdate),
}

/**
 * `window.confirm` 的替身。
 * ⚠️ happy-dom **根本没有实现 `confirm`**（不是「默认返回 true」，是这个函数不存在），
 * 所以在它上面 `vi.spyOn` 会直接抛「不是一个函数」。必须自己装一个。
 */
function setConfirm(answer: boolean): Mock<(message?: string) => boolean> {
  const spy = vi.fn<(message?: string) => boolean>(() => answer)
  window.confirm = spy
  return spy
}

function confirmText(spy: Mock<(message?: string) => boolean>): string {
  return String(spy.mock.calls[0]?.[0] ?? '')
}

function status(over: Partial<SourceStatus> = {}): SourceStatus {
  return {
    name: 'stub-src',
    display_name: '示例书站',
    domains: ['example.test'],
    public: false,
    user: false,
    download_enabled: true,
    cookie: { has: false, mtime: null, size: 0 },
    usable: true,
    blocked_reason: '',
    online_support: '',
    ...over,
  }
}

function onlineStatus(over: Partial<OnlineStatus> = {}): OnlineStatus {
  return {
    bound: false,
    source: '',
    display_name: '',
    url: '',
    title: '',
    pos: 0,
    seen: 0,
    cache: { total: 0, cached: 0, single: false, fetched_at: 0 },
    available: false,
    reason: '',
    has_sidecar: false,
    updatable: false,
    update_reason: '',
    ...over,
  }
}

async function mountCard(): Promise<VueWrapper> {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/book/:id', name: 'book', component: { template: '<div/>' } },
      { path: '/online/:id', name: 'online', component: { template: '<div/>' } },
    ],
  })
  await router.push('/book/book-a')
  await router.isReady()
  const w = mount(OnlineReadCard, {
    props: { bookId: 'book-a' },
    global: { plugins: [router] },
  })
  await flushPromises()
  return w
}

function rowButtons(w: VueWrapper, label: string) {
  return w.findAll('button').filter((b) => b.text().includes(label))
}

beforeEach(() => {
  vi.clearAllMocks()
  // 默认「还没绑定」—— 需要已绑定态的用例自己覆盖（表格里那几条写明了的才是重点）
  m.onlineStatus.mockResolvedValue(onlineStatus())
  m.sourcesStatus.mockResolvedValue({ items: [] } as never)
  m.runCheckUpdate.mockResolvedValue({ ok: true, message: '已检查，没有新章节' })
})

describe('OnlineReadCard · 源列表的可用态（第 93 期）', () => {
  it('不能逐章阅读的源如实标注原因，按钮点不动', async () => {
    m.sourcesStatus.mockResolvedValue({
      items: [status({ online_support: '这个书源不支持逐章在线阅读：它只能整本取回' })],
    } as never)
    const w = await mountCard()

    expect(w.text()).toContain('这个书源不支持逐章在线阅读')
    const btn = rowButtons(w, '绑定并开始')[0]
    expect(btn.attributes('disabled')).toBeDefined()
    w.unmount()
  })

  it('闸门关着的源同样标注原文且按钮点不动', async () => {
    m.sourcesStatus.mockResolvedValue({
      items: [status({ usable: false, blocked_reason: '下载与搜索已在设置里关闭' })],
    } as never)
    const w = await mountCard()

    expect(w.text()).toContain('下载与搜索已在设置里关闭')
    expect(rowButtons(w, '绑定并开始')[0].attributes('disabled')).toBeDefined()
    w.unmount()
  })

  it('可用源给「绑定并开始」，绑定成功后回显书名与置信度', async () => {
    m.sourcesStatus.mockResolvedValue({ items: [status()] } as never)
    m.onlineBind.mockResolvedValue({
      source: 'stub-src', display_name: '示例书站', url: 'https://example.test/page/1',
      title: '三体', confidence: 0.93, manual: false, pos: 0,
    })
    const w = await mountCard()

    const btn = rowButtons(w, '绑定并开始')[0]
    expect(btn.attributes('disabled')).toBeUndefined()
    await btn.trigger('click')
    await flushPromises()

    expect(m.onlineBind).toHaveBeenCalledWith('book-a', { source: 'stub-src', url: undefined })
    expect(w.text()).toContain('三体')
    expect(w.text()).toContain('0.93')
    // 绑完要让详情页重新取一次详情（头部入口据此显示）
    expect(w.emitted('changed')).toBeTruthy()
    w.unmount()
  })

  it('手动填了书页地址就原样带给后端（跳过自动匹配）', async () => {
    m.sourcesStatus.mockResolvedValue({ items: [status()] } as never)
    m.onlineBind.mockResolvedValue({
      source: 'stub-src', display_name: '示例书站', url: 'https://example.test/page/9',
      title: '', confidence: 1, manual: true, pos: 0,
    })
    const w = await mountCard()

    await w.find('input[aria-label="书页地址"]').setValue('  https://example.test/page/9  ')
    await rowButtons(w, '绑定并开始')[0].trigger('click')
    await flushPromises()

    expect(m.onlineBind).toHaveBeenCalledWith('book-a', {
      source: 'stub-src', url: 'https://example.test/page/9',
    })
    w.unmount()
  })

  it('绑定失败时显示后端的原因原文，且列表仍在（不是把错误吞掉）', async () => {
    m.sourcesStatus.mockResolvedValue({ items: [status()] } as never)
    m.onlineBind.mockRejectedValue(new Error('在「示例书站」里没匹配到《三体》（最高置信度 0.20，阈值 0.6）'))
    const w = await mountCard()

    await rowButtons(w, '绑定并开始')[0].trigger('click')
    await flushPromises()

    expect(w.text()).toContain('没匹配到')
    expect(w.text()).toContain('阈值 0.6')
    expect(rowButtons(w, '绑定并开始').length).toBe(1)
    w.unmount()
  })
})

describe('OnlineReadCard · 已绑定态（第 93 期）', () => {
  it('显示源名 / 在线位置 / 缓存章数，并给出「开始在线读」', async () => {
    m.onlineStatus.mockResolvedValue(onlineStatus({
      bound: true, source: 'stub-src', display_name: '示例书站',
      url: 'https://example.test/page/1', pos: 6,
      cache: { total: 30, cached: 4, single: false, fetched_at: 0 },
      available: true,
    }))
    m.sourcesStatus.mockResolvedValue({ items: [status()] } as never)
    const w = await mountCard()

    const text = w.text()
    expect(text).toContain('示例书站')
    expect(text).toContain('example.test')
    expect(text).toContain('第 7 章')            // pos 是 0 起，显示成人读的 1 起
    expect(text).toContain('本机已缓存 4 章')
    expect(rowButtons(w, '开始在线读').length).toBe(1)
    expect(rowButtons(w, '解绑').length).toBe(1)
    w.unmount()
  })

  it('已绑定但不可用时如实写出原因，且不给「开始在线读」', async () => {
    m.onlineStatus.mockResolvedValue(onlineStatus({
      bound: true, source: 'stub-src', display_name: '示例书站',
      url: 'https://example.test/page/1', available: false,
      reason: '这个书源不支持逐章在线阅读：它只能整本取回',
    }))
    m.sourcesStatus.mockResolvedValue({ items: [status()] } as never)
    const w = await mountCard()

    expect(w.text()).toContain('这个书源不支持逐章在线阅读')
    expect(rowButtons(w, '开始在线读').length).toBe(0)
    w.unmount()
  })

  it('解绑只删登记，并如实说明缓存留着', async () => {
    m.onlineStatus.mockResolvedValue(onlineStatus({
      bound: true, source: 'stub-src', display_name: '示例书站',
      url: 'https://example.test/page/1', available: true,
    }))
    m.sourcesStatus.mockResolvedValue({ items: [status()] } as never)
    m.onlineUnbind.mockResolvedValue({ ok: true, cleared: 1 })
    const w = await mountCard()

    await rowButtons(w, '解绑')[0].trigger('click')
    await flushPromises()

    expect(m.onlineUnbind).toHaveBeenCalledWith('book-a')
    expect(w.text()).toContain('缓存留着')
    w.unmount()
  })
})

describe('OnlineReadCard · 检查更新 / 用源站整本覆盖（第 93 期 E5）', () => {
  /** 可更新 = 闸门开着 且（有留档 或 有绑定）；这里取「下载来的书」：有留档、**没绑定** */
  function updatable(over: Partial<OnlineStatus> = {}): OnlineStatus {
    return onlineStatus({ has_sidecar: true, updatable: true, ...over })
  }

  it('可更新 ⇒ 给出「检查更新」与「用源站整本覆盖本地」两颗按钮', async () => {
    m.onlineStatus.mockResolvedValue(updatable())
    const w = await mountCard()

    expect(rowButtons(w, '检查更新').length).toBe(1)
    expect(rowButtons(w, '用源站整本覆盖本地').length).toBe(1)
    // 没绑定 ⇒ 不给「开始在线读」/「解绑」（那两项的判据是 bound）
    expect(rowButtons(w, '开始在线读').length).toBe(0)
    expect(rowButtons(w, '解绑').length).toBe(0)
    w.unmount()
  })

  it('「检查更新」默认**只追加**：不带 overwrite，报告就地显示在这张卡上', async () => {
    m.onlineStatus.mockResolvedValue(updatable())
    m.runCheckUpdate.mockResolvedValue({ ok: true, message: '新增 3 章' })
    const w = await mountCard()

    await rowButtons(w, '检查更新')[0].trigger('click')
    await flushPromises()

    // ⚠️ 第二个参数缺省 ⇒ 「只追加」那条路（既有章一个字都不动）
    expect(m.runCheckUpdate).toHaveBeenCalledWith('book-a')
    // 报告**原样**贴出来，不跳任务中心（用户就站在这儿刚点的按钮）
    expect(w.text()).toContain('新增 3 章')
    expect(w.emitted('changed')).toBeTruthy()
    w.unmount()
  })

  it('「整本覆盖」说清代价并二次确认，确认后才带 overwrite=true', async () => {
    m.onlineStatus.mockResolvedValue(updatable({ title: '三体' }))
    m.runCheckUpdate.mockResolvedValue({ ok: true, message: '已按源站整本重写' })
    const spy = setConfirm(true)
    const w = await mountCard()

    await rowButtons(w, '用源站整本覆盖本地')[0].trigger('click')
    await flushPromises()

    const text = confirmText(spy)
    expect(text).toContain('三体')
    // 代价必须写明：它**不是**「更彻底地检查更新」，而是另一件事
    expect(text).toContain('整本重写')
    expect(text).toContain('进度')
    expect(m.runCheckUpdate).toHaveBeenCalledWith('book-a', { overwrite: true })
    expect(w.text()).toContain('整本重写')
    w.unmount()
  })

  it('点「取消」⇒ 一个字都不写（既没覆盖，也没白问一次后端）', async () => {
    m.onlineStatus.mockResolvedValue(updatable())
    setConfirm(false)
    const w = await mountCard()

    await rowButtons(w, '用源站整本覆盖本地')[0].trigger('click')
    await flushPromises()

    expect(m.runCheckUpdate).not.toHaveBeenCalled()
    expect(w.emitted('changed')).toBeUndefined()
    w.unmount()
  })

  it('有留档但当前不可更新 ⇒ 说出后端给的原因，两颗按钮都不出现', async () => {
    m.onlineStatus.mockResolvedValue(onlineStatus({
      has_sidecar: true,
      updatable: false,
      update_reason: '下载与搜索已在设置里关闭：到「设置 → 网络与下载」打开',
    }))
    const w = await mountCard()

    expect(w.text()).toContain('下载与搜索已在设置里关闭')
    expect(rowButtons(w, '检查更新').length).toBe(0)
    expect(rowButtons(w, '用源站整本覆盖本地').length).toBe(0)
    w.unmount()
  })
})
