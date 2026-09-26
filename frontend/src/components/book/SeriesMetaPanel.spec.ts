/**
 * 系列元数据面板（第 57 期：四字段编辑 + 逐字段恢复）。
 *
 * ## 这个文件真正在防什么
 *
 * 面板的展示部分（徽标 / 来源 / 册数）错了只是不好看，**写错 payload 才是事故**：
 *   · 「保存」必须是**四字段一起提交**（否则只改了简介、把用户刚填的出版社丢掉）；
 *   · 「恢复在线」必须**只提交那一个字段的空串** —— 后端 `set_local` 把「空串」解释为
 *     「撤销该字段的覆盖」，若顺手把其它字段也带上，就把用户其它字段的覆盖一起清了；
 *   · 首发年写坏值（`19` / `abcd`）**不能发出去**：db 里会留下一个永远匹配不上的年份。
 *
 * 所以下面每条都盯 payload，而不是「屏幕上有没有这段字」。
 */
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import SeriesMetaPanel from '@/components/book/SeriesMetaPanel.vue'
import { api, type SeriesMeta, type SeriesMetaState } from '@/lib/api'

vi.mock('@/lib/api', () => ({
  api: {
    saveSeriesMeta: vi.fn(),
    fetchSeriesMeta: vi.fn(),
  },
}))

const mockSave = vi.mocked(api.saveSeriesMeta)

function mkMeta(over: Partial<SeriesMeta> = {}): SeriesMeta {
  return {
    name: '银河帝国',
    description: '银河帝国系列简介',
    publisher: '读客',
    first_year: '1951',
    tags: ['科幻', '太空歌剧'],
    owned_count: 3,
    declared_count: 7,
    overridden: { description: false, publisher: false, first_year: false, tags: false },
    source: 'openlibrary',
    score: 0.8,
    fetched_at: 0,
    ...over,
  }
}

function field(value: string | string[], over = false): SeriesMetaState['description'] {
  return { value, online: value, aggregated: value, local: over ? value : '', overridden: over }
}

function mkState(): SeriesMetaState {
  return {
    description: field('银河帝国系列简介'),
    publisher: field('读客'),
    first_year: field('1951'),
    tags: field(['科幻', '太空歌剧']),
  }
}

function mountPanel(meta: SeriesMeta, state: SeriesMetaState | null = mkState()): VueWrapper {
  return mount(SeriesMetaPanel, {
    props: { name: meta.name, meta, state },
  })
}

const btn = (w: VueWrapper, text: string) => w.findAll('button').find((b) => b.text().trim() === text)
/** 字段区的逐字段恢复入口（简介的恢复按钮文案不同：「↺ 恢复在线」） */
const fieldRestoreBtns = (w: VueWrapper) =>
  w.findAll('button').filter((b) => b.text().trim() === '↺ 恢复')

beforeEach(() => {
  setActivePinia(createPinia())
  mockSave.mockReset()
  mockSave.mockResolvedValue({ ok: true, meta: mkMeta(), state: mkState() })
})

describe('SeriesMetaPanel · 保存', () => {
  it('四字段一起提交，题材用「、」连接', async () => {
    const w = mountPanel(mkMeta())
    await btn(w, '编辑')!.trigger('click')

    const inputs = w.findAll('input')
    expect(inputs.length).toBe(3)
    await inputs[0].setValue('新星出版社')
    await inputs[1].setValue('1952')
    await inputs[2].setValue('科幻、赛博朋克')
    await w.find('textarea').setValue('改过的简介')
    await btn(w, '保存')!.trigger('click')
    await flushPromises()

    expect(mockSave).toHaveBeenCalledTimes(1)
    expect(mockSave).toHaveBeenCalledWith('银河帝国', {
      description: '改过的简介',
      publisher: '新星出版社',
      first_year: '1952',
      tags: '科幻、赛博朋克',
    })
    // 保存后回到展示态（不让编辑框常驻把页面撑长）
    expect(btn(w, '编辑')).toBeTruthy()
  })

  it('首发年非法时不提交（挡住写坏值）', async () => {
    const w = mountPanel(mkMeta())
    await btn(w, '编辑')!.trigger('click')
    await w.findAll('input')[1].setValue('19')
    await btn(w, '保存')!.trigger('click')
    await flushPromises()

    expect(mockSave).not.toHaveBeenCalled()
  })

  it('首发年留空是合法输入（= 清除该字段覆盖）', async () => {
    const w = mountPanel(mkMeta())
    await btn(w, '编辑')!.trigger('click')
    await w.findAll('input')[1].setValue('')
    await btn(w, '保存')!.trigger('click')
    await flushPromises()

    expect(mockSave).toHaveBeenCalledWith(
      '银河帝国',
      expect.objectContaining({ first_year: '' }),
    )
  })
})

describe('SeriesMetaPanel · 逐字段恢复在线', () => {
  it('只提交该字段的空串，不牵连其它字段', async () => {
    const w = mountPanel(mkMeta({
      overridden: { description: true, publisher: true, first_year: false, tags: false },
    }))
    await flushPromises()

    // 字段区里只有被覆盖的出版社有「恢复」（简介的入口在头部，文案不同）
    expect(fieldRestoreBtns(w).length).toBe(1)

    await fieldRestoreBtns(w)[0].trigger('click')
    await flushPromises()

    expect(mockSave).toHaveBeenCalledTimes(1)
    expect(mockSave).toHaveBeenCalledWith('银河帝国', { publisher: '' })
  })

  it('简介的恢复入口在头部（只提交 description）', async () => {
    const w = mountPanel(mkMeta({
      overridden: { description: true, publisher: false, first_year: false, tags: false },
    }))
    const head = w.findAll('button').find((b) => b.text().trim() === '↺ 恢复在线')!
    await head.trigger('click')
    await flushPromises()

    expect(mockSave).toHaveBeenCalledWith('银河帝国', { description: '' })
  })
})

describe('SeriesMetaPanel · 展示', () => {
  it('未覆盖时标出来源（成员书聚合 / 在线），覆盖时标「本地」', () => {
    const w = mountPanel(mkMeta({
      overridden: { description: false, publisher: true, first_year: false, tags: false },
    }))
    const text = w.text()

    expect(text).toContain('出版社 · 读客')
    expect(text).toContain('本地')
    expect(text).toContain('成员书聚合')
    expect(text).toContain('册数 · 已有 3 册 / 外部声明共 7 册')
  })

  it('简介为空时如实说明「未找到可信来源」，不留占位假话', () => {
    const w = mountPanel(mkMeta({ description: '', source: '', score: 0 }))

    expect(w.text()).toContain('未找到可信的在线系列简介')
  })
})
