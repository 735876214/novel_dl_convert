import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { BOOKS, type Book } from '@/data/books'
import { BOOK_FILES, COLLECTIONS, LIBRARIES, SANTI_VOLUMES, SMART_SHELVES } from '@/data/collections'
import { SOURCES } from '@/data/sources'

/**
 * 书库 store：全部演示数据 + 书库页的筛选状态。
 *
 * 数据本体放在 src/data/*，此处只做组合与派生，避免单个文件过长。
 */
export const useLibraryStore = defineStore('library', () => {
  const books = ref<Book[]>(BOOKS)
  const sources = ref(SOURCES)

  /** 书库页标题与当前标签筛选（对应 v2 的 state.libTitle / state.libTag） */
  const shelfTitle = ref('全部书库')
  const shelfTag = ref('')

  const enabledSourceCount = computed(() => sources.value.filter((s) => s.on).length)
  const totalPages = computed(() => books.value.reduce((sum, b) => sum + b.pages, 0))

  /** 全部标签去重（书库页筛选 chips 用） */
  const allTags = computed(() => {
    const seen: string[] = []
    books.value.forEach((b) => {
      b.tags.forEach((t) => {
        if (!seen.includes(t)) seen.push(t)
      })
    })
    return seen
  })

  const shelfBooks = computed(() =>
    shelfTag.value ? books.value.filter((b) => b.tags.includes(shelfTag.value)) : books.value,
  )

  /** 继续阅读：按进度降序取前 6（仪表盘书架行用） */
  const continueReading = computed(() =>
    books.value
      .filter((b) => b.progress > 0 && b.progress < 100)
      .sort((a, b) => b.progress - a.progress),
  )

  function findBook(id: number): Book | null {
    return books.value.find((b) => b.id === id) ?? null
  }

  /** 进入书库页并可选带标签筛选 */
  function openShelf(title: string, tag = ''): void {
    shelfTitle.value = title || '全部书库'
    shelfTag.value = tag
  }

  return {
    books,
    sources,
    shelfTitle,
    shelfTag,
    enabledSourceCount,
    totalPages,
    allTags,
    shelfBooks,
    continueReading,
    findBook,
    openShelf,
    // 侧栏三组条目与详情页数据（只读，直接透出）
    libraries: LIBRARIES,
    smartShelves: SMART_SHELVES,
    collections: COLLECTIONS,
    santiVolumes: SANTI_VOLUMES,
    bookFiles: BOOK_FILES,
  }
})
