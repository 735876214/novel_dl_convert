/**
 * 「系列目录」（第 152 期）：折叠系列后的阅读器**侧栏卷清单** —— 漫画与 PDF 阅读器共用。
 *
 * 背景：章节流阅读器（EPUB / TXT）的目录抽屉长在 `ReaderView` 上；漫画 / PDF 阅读器
 * 自带工具栏、没有目录入口 —— 于是点开一个 28 册的系列只能一册一册翻，跳册得退到
 * 详情页再点。合集（UNITS）本就有话目录（`UnitsReader`），这里补齐的正是漫画 / PDF
 * 这两处缺口。
 *
 * 数据用既有 `GET /api/series/{name}`（与 `lib/seriesNext` 同一条接口），排序沿用
 * `sortBySeriesIndex`（系列页 / 续接同一份口径）；没有系列名就什么也不拉（侧栏显示
 * 一句「这本没有系列信息」，不显示按钮——显示了一个永远空的侧栏才是假交互）。
 *
 * ⚠️ 这是**第三处**读系列清单（前两处：系列页、`seriesNext`）—— 但它们各答各的问题
 * （页面展示 / 找下一册），这里答「整份清单给侧栏挑」；排序函数与接口都是现成的
 * 单一真值源，没有新增任何判据。
 */
import { computed, ref, watch, type Ref } from 'vue'

import { api, type BookCard } from '@/lib/api'
import { sortBySeriesIndex } from '@/lib/bookInfo'

/** 单册条目里侧栏用得到的字段（`BookCard` 的子集，便于测试桩造数据） */
export type SeriesTocBook = Pick<BookCard, 'id' | 'title' | 'name' | 'series_index' | 'has_cover' | 'c1' | 'c2' | 'format'>

export interface SeriesToc {
  /** 有没有系列名（没有 ⇒ 侧栏显示「无系列」并禁用按钮） */
  hasSeries: boolean
  /** 拉取失败的原因（空串 = 没失败） */
  error: string
  loading: boolean
  /** 系列名（原样） */
  name: string
  /** 排好序的全部册 */
  books: BookCard[]
  /** 当前册在清单里的位置（-1 = 当前书不在清单里，侧栏不高亮任何一行） */
  currentIndex: number
}

export function useSeriesToc(series: Ref<string | undefined>, currentBookId: Ref<string>): SeriesToc {
  const hasSeries = computed(() => !!String(series.value || '').trim())
  const error = ref('')
  const loading = ref(false)
  const books = ref<BookCard[]>([])

  async function load(name: string): Promise<void> {
    loading.value = true
    error.value = ''
    try {
      const d = await api.seriesDetail(name)
      books.value = sortBySeriesIndex(d.books ?? [])
    } catch (e) {
      books.value = []
      error.value = e instanceof Error ? e.message : '加载失败'
    }
    loading.value = false
  }

  watch(
    () => String(series.value || '').trim(),
    (name) => {
      if (!name) {
        books.value = []
        error.value = ''
        loading.value = false
        return
      }
      void load(name)
    },
    { immediate: true },
  )

  const name = computed(() => String(series.value || '').trim())
  /** 当前册在清单里的位置（当前书不在清单里 = -1，侧栏不高亮任何一行） */
  const currentIndex = computed(() =>
    books.value.findIndex((b) => String(b.id) === String(currentBookId.value)),
  )

  return {
    // 与 `books` / `currentIndex` 同一套 getter 口径：模板拿到的是值，不是 ref
    get hasSeries() { return hasSeries.value },
    get error() { return error.value },
    get loading() { return loading.value },
    get name() { return name.value },
    get books() { return books.value },
    get currentIndex() { return currentIndex.value },
  }
}
