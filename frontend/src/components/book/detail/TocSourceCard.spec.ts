import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api, type TocSourceItem, type TocSourceRow } from '@/lib/api'
import TocSourceCard from '@/components/book/detail/TocSourceCard.vue'

/**
 * 「目录来源」区块（第 85 期批次 B）。
 *
 * 这块是**出网**的入口，所以重点全在「不骗人」上：
 * 1. 不可用 / 未验证必须如实标注，而且**按钮点不动**（不做假交互）；
 * 2. 失败必须显示后端给的原因原文，并且**照样刷新**（失败也落库，父级要重取详情）；
 * 3. 「还原为本地目录」只在**当前真的用着书城目录**时才出现。
 */
vi.mock('@/lib/api', () => ({
  api: { tocSources: vi.fn(), tocFetch: vi.fn(), tocClear: vi.fn() },
  apiErrorMessage: (e: unknown, fallback: string) =>
    (e as { detail?: string })?.detail || fallback,
}))

const m = {
  sources: vi.mocked(api.tocSources),
  fetch: vi.mocked(api.tocFetch),
  clear: vi.mocked(api.tocClear),
}

function item(over: Partial<TocSourceItem> = {}): TocSourceItem {
  return {
    id: 'fanqie',
    label: '番茄小说',
    home: 'https://fanqienovel.com',
    status: 'needs_credentials',
    verified: false,
    note: '目录页可匿名打开，但站点有风控',
    usable: true,
    blocked_reason: '',
    ...over,
  }
}

function row(over: Partial<TocSourceRow> = {}): TocSourceRow {
  return {
    source: 'fanqie',
    label: '番茄小说',
    state: '',
    ok: true,
    note: '',
    manual: false,
    confidence: 1,
    matched_title: '三体',
    store_ref: '',
    fetched_at: 0,
    entry_count: 10,
    mapped: 8,
    ...over,
  }
}

async function mountCard(props: Record<string, unknown> = {}): Promise<VueWrapper> {
  const w = mount(TocSourceCard, { props: { bookId: 'b1', ...props } })
  await flushPromises()
  return w
}

beforeEach(() => {
  m.sources.mockReset()
  m.fetch.mockReset()
  m.clear.mockReset()
  m.sources.mockResolvedValue({ items: [item()], enabled: true, reason: '' })
})

describe('目录来源：如实标注', () => {
  it('未验证与不可用都标出来，且不可用的按钮点不动', async () => {
    m.sources.mockResolvedValue({
      items: [
        item(),
        item({
          id: 'weread',
          label: '微信读书',
          status: 'unsupported',
          usable: false,
          blocked_reason: '目录要登录态且接口带签名参数，本批只登记',
        }),
      ],
      enabled: true,
      reason: '',
    })
    const w = await mountCard()
    expect(w.text()).toContain('未验证')
    expect(w.text()).toContain('本批只登记')

    const buttons = w.findAll('button')
    const wechat = buttons.find((b) => b.text().includes('取目录') && b.attributes('disabled') !== undefined)
    expect(wechat, '不可用来源的按钮必须是 disabled').toBeTruthy()

    // 点它也不该发请求
    await w.findAll('button').at(-1)!.trigger('click')
    expect(m.fetch).not.toHaveBeenCalled()
  })

  it('闸门关着时把原因原样显示出来', async () => {
    m.sources.mockResolvedValue({
      items: [item({ usable: false, blocked_reason: '取目录未开启：到「设置 → 网络与下载」打开' })],
      enabled: false,
      reason: '取目录未开启：到「设置 → 网络与下载」打开',
    })
    const w = await mountCard()
    expect(w.text()).toContain('取目录未开启')
    expect(w.find('button').attributes('disabled')).toBeDefined()
  })

  it('当前用着书城目录时才出现「还原为本地目录」', async () => {
    const off = await mountCard({ sources: [row({ ok: false, note: '没匹配到' })], applied: '' })
    expect(off.text()).not.toContain('还原为本地目录')
    expect(off.text()).toContain('没匹配到')

    const on = await mountCard({ sources: [row()], applied: 'fanqie' })
    expect(on.text()).toContain('还原为本地目录')
    expect(on.text()).toContain('已对齐 8 / 10 条')
  })
})

describe('目录来源：动作', () => {
  it('取目录成功后 emit changed 并报出对齐条数', async () => {
    m.fetch.mockResolvedValue({ mapped: 8, total: 10, matched_title: '三体', confidence: 1 })
    const w = await mountCard()
    await w.findAll('button').at(-1)!.trigger('click')
    await flushPromises()

    expect(m.fetch).toHaveBeenCalledWith('b1', 'fanqie', '')
    expect(w.emitted('changed')).toHaveLength(1)
    expect(w.text()).toContain('已对齐 8 / 10 章')
  })

  it('手动填了书页地址就带上去', async () => {
    m.fetch.mockResolvedValue({ mapped: 1, total: 1, matched_title: '三体', confidence: 1 })
    const w = await mountCard()
    await w.find('input[aria-label="书页地址"]').setValue('https://x/1')
    await w.findAll('button').at(-1)!.trigger('click')
    expect(m.fetch).toHaveBeenCalledWith('b1', 'fanqie', 'https://x/1')
  })

  it('失败也要显示原因并照样 emit changed（失败同样落库）', async () => {
    m.fetch.mockRejectedValue({ detail: '在「番茄小说」里没匹配到《三体》' })
    const w = await mountCard()
    await w.findAll('button').at(-1)!.trigger('click')
    await flushPromises()

    expect(w.text()).toContain('没匹配到')
    expect(w.emitted('changed')).toHaveLength(1)
  })

  it('还原为本地目录', async () => {
    m.clear.mockResolvedValue({ ok: true, cleared: 1 })
    const w = await mountCard({ sources: [row()], applied: 'fanqie' })
    const btn = w.findAll('button').find((b) => b.text().includes('还原为本地目录'))!
    await btn.trigger('click')
    await flushPromises()

    expect(m.clear).toHaveBeenCalledWith('b1')
    expect(w.emitted('changed')).toHaveLength(1)
    expect(w.text()).toContain('已还原为本地目录')
  })
})
