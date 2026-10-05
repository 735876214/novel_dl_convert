/**
 * 单书元数据编辑器（第 5 个标签）。本文件盯的是**第 63 期新加的两类字段**：
 * 副标题与 9 个提供商 ID。
 *
 * ## 这个文件真正在防什么
 *
 * 新字段的 UI 是**循环渲染**出来的，于是「漏配一处」不会崩、也不会报错：
 *
 *   · **漏进 `CATALOG_FIELDS`** ⇒ 那个字段在页面上根本没有输入框，
 *     在线抓回来的 ID 用户既看不到也改不了（`标签是静默的缺席`）；
 *   · **`v-model` 串了** ⇒ 用户改 A 字段、提交的却是 B 字段的值。
 *     这比「少一个字段」糟得多 —— 它**改坏了一个本来正确的值**，
 *     而且后端无从判断（payload 看起来完全正常）。
 *
 * 所以第二条不是「页面上有没有这段字」，而是**逐字段改一遍、再逐字段核对 payload**。
 * 另外钉住 `POLICY_FIELDS` / 字段表的**完整性**：加了类型忘了加表，字段就是不可达的。
 */
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import MetadataEditor from '@/components/book/MetadataEditor.vue'
import { api, type BookMetadata, type BookMetadataFields } from '@/lib/api'
import {
  CATALOG_FIELDS,
  DB_ONLY_FIELDS,
  FIELD_LABELS,
  IDENTITY_FIELDS,
  POLICY_FIELDS,
  PROVIDER_ID_FIELDS,
} from '@/lib/metadataFields'

vi.mock('@/lib/api', () => ({
  api: {
    bookMetadata: vi.fn(),
    setBookMetadata: vi.fn(),
    revertBookMetadata: vi.fn(),
    lockBookMetadata: vi.fn(),
  },
}))

const m = {
  load: vi.mocked(api.bookMetadata),
  save: vi.mocked(api.setBookMetadata),
}

const BOOK_ID = 'lib$aaa'

/** 每个字段给一个**各不相同**的值 —— 串了 v-model 才会现形（全填一样的值就测不出来） */
function valueOf(k: keyof BookMetadataFields): string | string[] {
  if (k === 'tags') return ['科幻']
  if (k === 'narrators') return []
  return `V-${k}`
}

function makeFields(): BookMetadataFields {
  // 先攒成可索引的对象再断言一次 —— `BookMetadataFields` 没有索引签名，
  // 直接逐键写会被 `vue-tsc` 判成可疑转换（TS2352）。断言只留这一处。
  const out: Record<string, unknown> = {}
  for (const k of Object.keys(FIELD_LABELS) as (keyof BookMetadataFields)[]) {
    out[k] = valueOf(k)
  }
  return out as unknown as BookMetadataFields
}

function makeMeta(): BookMetadata {
  const fields = makeFields()
  const meta: BookMetadata['meta'] = {}
  for (const k of Object.keys(FIELD_LABELS)) {
    meta[k] = { value: fields[k as keyof BookMetadataFields], online: '', opf: '', overridden: false, locked: false }
  }
  return { id: BOOK_ID, name: '三体.epub', format: 'EPUB', editable: true, fields, meta, locked: [], custom: [] }
}

async function mountEditor(): Promise<VueWrapper> {
  const w = mount(MetadataEditor, { props: { bookId: BOOK_ID }, global: { plugins: [createPinia()] } })
  await flushPromises()
  return w
}

/** 某个字段的输入框（按 `<label>` 里的中文名定位 —— 与用户看到的是同一个锚） */
function input(w: VueWrapper, k: keyof BookMetadataFields) {
  const label = w.findAll('label').find((l) => l.text().includes(FIELD_LABELS[k]))
  if (!label) throw new Error(`页面上找不到字段「${FIELD_LABELS[k]}」（${k}）`)
  return label.find('input')
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  m.load.mockResolvedValue(makeMeta())
  m.save.mockImplementation(async (_id, fields) => ({
    ok: true, changed: ['x'], unknown: [], fields: fields as BookMetadataFields,
    meta: makeMeta().meta, custom: [],
  }) as never)
})

describe('元数据编辑器 · 字段表的完整性', () => {
  /**
   * 后端 `fileops.METADATA_FIELDS` 有 21 项。加了类型定义却不加进这两张表，
   * 那个字段就**不可达** —— 页面上没有它的输入框，用户连看都看不到。
   * 这里逐字列出来（不用 `Object.keys(FIELD_LABELS)` 生成），加字段必须有意改一次。
   */
  it('每个可编辑字段都落在某一组里（加了字段忘了挂到界面上会红）', () => {
    const reachable = new Set<string>([
      ...IDENTITY_FIELDS, ...CATALOG_FIELDS,
      // 这三项各有自己的 UI 块，不在这两张表里
      'tags', 'narrators', 'description',
    ])
    expect([...Object.keys(FIELD_LABELS)].filter((k) => !reachable.has(k))).toEqual([])
  })

  it('提供商 ID 正好 9 个，且全部在 CATALOG 段里', () => {
    expect(PROVIDER_ID_FIELDS).toHaveLength(9)
    expect(new Set(CATALOG_FIELDS)).toEqual(new Set(['isbn', ...PROVIDER_ID_FIELDS]))
    // 副标题归 IDENTITY（上游同款分段）
    expect(IDENTITY_FIELDS).toContain('subtitle')
  })

  it('抓取策略表与「引擎真会抓的字段」同集合', () => {
    // 与后端 `metafetch._FINALIZE_FIELDS` 同集合（= `_VALUE_KEYS` + 封面；
    // 后端有测试钉住那两者，这里补上跨语言这一半）。
    // ⚠️ 第 103 期起 **含 series / series_index / narrators**：`metafetch` 把这三项接进了
    // 抓取线（候选结构 + `_VALUE_KEYS` 都加了），所以策略表里也必须有 ——
    // 少一边的表现是「这一项在设置页里根本看不见」，静默失效。
    const editable = [...IDENTITY_FIELDS, ...CATALOG_FIELDS, 'tags', 'narrators', 'description']
    expect(new Set(POLICY_FIELDS)).toEqual(new Set([...editable, 'cover']))
    expect(POLICY_FIELDS).toContain('date')       // 先前 Book Dock 抄成 year 的那一项
    expect(POLICY_FIELDS).not.toContain('year')
    expect(POLICY_FIELDS).toContain('series')
    expect(POLICY_FIELDS).toContain('series_index')
    expect(POLICY_FIELDS).toContain('narrators')
  })

  it('「没有 OPF 对应物」的字段表覆盖了全部 DB-only 字段', () => {
    // 这几个字段写不进 OPF（后端 `patch_opf_meta` 只认它那串 if/elif）。
    expect(new Set(DB_ONLY_FIELDS)).toEqual(new Set(['narrators', 'subtitle', ...PROVIDER_ID_FIELDS]))
    // 它们必须都在可编辑字段里，否则这张表就是一份死清单
    for (const k of DB_ONLY_FIELDS) expect(FIELD_LABELS).toHaveProperty(k)
  })
})

describe('元数据编辑器 · 提供商 ID 真的挂到了界面上', () => {
  it('9 个 ID 与副标题都有输入框，且带的是自己的生效值', async () => {
    const w = await mountEditor()
    for (const k of [...PROVIDER_ID_FIELDS, 'subtitle'] as (keyof BookMetadataFields)[]) {
      expect(input(w, k).element.value).toBe(`V-${k}`)
    }
  })

  it('两段分组标题都渲染出来了（标识 / 目录号）', async () => {
    const w = await mountEditor()
    expect(w.text()).toContain('标识')
    expect(w.text()).toContain('目录号')
  })

  /**
   * **判据力所在**：逐字段改一遍再逐字段核对 payload。
   * 只断言「输入框都在」是测不出 `v-model` 串线的 —— 串了之后框还在，值也显示得对，
   * 只有提交那一刻才出事。
   */
  it('逐个改一遍，提交的 payload 每个字段都对得上（v-model 串线会红）', async () => {
    const w = await mountEditor()

    const touched = [...PROVIDER_ID_FIELDS, 'subtitle', 'isbn'] as (keyof BookMetadataFields)[]
    for (const k of touched) {
      await input(w, k).setValue(`NEW-${k}`)
    }
    await flushPromises()

    const saveBtn = w.findAll('button').find((b) => b.text().trim() === '保存')
    expect(saveBtn).toBeTruthy()
    await saveBtn!.trigger('click')
    await flushPromises()

    expect(m.save).toHaveBeenCalledTimes(1)
    const fields = m.save.mock.calls[0][1] as Record<string, unknown>
    for (const k of touched) {
      expect(fields[k]).toBe(`NEW-${k}`)
    }
    // 没碰过的字段必须原样带回去（漏带 = 后端按「撤销覆盖」处理，把值清掉）
    for (const k of Object.keys(FIELD_LABELS) as (keyof BookMetadataFields)[]) {
      if (!touched.includes(k) && k !== 'tags' && k !== 'narrators') {
        expect(fields[k]).toBe(valueOf(k))
      }
    }
  })

  it('改一个 ID 不会把别的 ID 一起改掉', async () => {
    const w = await mountEditor()
    await input(w, 'goodreads_id').setValue('99999')
    await flushPromises()

    // 屏幕上：改的那个新值，其余仍是原值（串了 v-model 时这里会显出别人的值）
    expect(input(w, 'goodreads_id').element.value).toBe('99999')
    for (const k of PROVIDER_ID_FIELDS) {
      if (k !== 'goodreads_id') expect(input(w, k).element.value).toBe(`V-${k}`)
    }
  })
})

describe('元数据编辑器 · 提供商 ID 没有 OPF 原值', () => {
  /**
   * ID 与 `narrators` 同一种待遇：经 `meta_override` 落库、**不写回书文件**，
   * 所以「恢复在线」对它们而言是「回落到在线值、没有就为空」。
   * 文案不能写成「回到文件原值」—— 那对 ID 是假话（文件里根本没有这个字段）。
   */
  it('已覆盖且无在线值时，文案说的是「该字段为空」而不是「回到文件原值」', async () => {
    const meta = makeMeta()
    meta.meta.google_books_id = {
      value: 'zyTCAlFPjgYC', online: '', opf: '', overridden: true, locked: false,
    }
    meta.fields.google_books_id = 'zyTCAlFPjgYC'
    m.load.mockResolvedValue(meta)

    const w = await mountEditor()
    const label = w.findAll('label').find((l) => l.text().includes(FIELD_LABELS.google_books_id))!
    expect(label.text()).toContain('恢复在线')
    expect(label.text()).toContain('该字段为空')
    expect(label.text()).not.toContain('回到文件原值')
  })
})
