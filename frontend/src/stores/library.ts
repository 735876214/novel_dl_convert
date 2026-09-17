import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { api, type BookCard, type BookDetail, type LibraryGroup } from '@/lib/api'
import { COLLECTIONS, LIBRARIES, SMART_SHELVES } from '@/data/collections'
import { evaluateScope, type SmartScope } from '@/lib/smartScope'

/**
 * 书库 store：组合真实书目数据与书库页的筛选状态。
 *
 * 数据来自后端 /api/books（扫描 OUTPUT_DIR 的成品），挂载时按需拉取并缓存；
 * 详情页的章节/文件由 /api/books/{id} 按 id 记忆化获取。
 * 阅读进度等持久化字段将在引入数据库后（Batch 2）接入。
 */
export const useLibraryStore = defineStore('library', () => {
  const books = ref<BookCard[]>([])
  const details = ref<Record<string, BookDetail>>({})
  const loaded = ref(false)
  const loading = ref(false)
  /** 「库」真实分组（格式 / 待修复 / 无封面），来自 /api/libraries */
  const libraryGroups = ref<LibraryGroup[]>([])

  /** 书库页标题与当前标签筛选（对应 v2 的 state.libTitle / state.libTag） */
  const shelfTitle = ref('全部书库')
  const shelfTag = ref('')
  /** 智能书架筛选键（非空时优先于标签筛选） */
  const smartKey = ref('')
  /** 「库」分组筛选键（如 fmt:EPUB / issues:1），优先级最高 */
  const shelfFacet = ref('')

  /** 全部标签去重（书库页筛选 chips 用） */
  const allTags = computed(() => {
    const seen: string[] = []
    books.value.forEach((b) => {
      ;(b.tags || []).forEach((t) => {
        if (!seen.includes(t)) seen.push(t)
      })
    })
    return seen
  })

  /** 智能书架：侧栏标签 → 筛选键 */
  const SMART_KEYS: Record<string, string> = {
    '最近添加': 'recent',
    '未读': 'unread',
    '在读': 'reading',
    '已完成': 'finished',
    '有批注': 'annotated',
  }

  function smartKeyOf(label: string): string {
    return SMART_KEYS[label] ?? ''
  }

  /** 按阅读状态筛书（真实状态优先，无状态行的书按进度兜底推导） */
  function smartBooks(key: string): BookCard[] {
    const byStatus = (s: string) => (b: BookCard) => (b.status ?? derivedStatus(b)) === s
    switch (key) {
      case 'recent':
        return [...books.value].sort((a, b) => (b.mtime || 0) - (a.mtime || 0)).slice(0, 50)
      case 'unread':
        return books.value.filter(byStatus('unread'))
      case 'reading':
        // 搁置/弃读都「翻过」，与在读同属「未读完」的浏览心智
        return books.value.filter((b) => ['reading', 'paused', 'abandoned'].includes(b.status ?? derivedStatus(b)))
      case 'finished':
        return books.value.filter(byStatus('finished'))
      case 'annotated':
        return books.value.filter((b) => (b.annotation_count ?? 0) > 0)
      default:
        // 自定义智能书架：smartKey 形如 scope:{id}，按存储规则在前端求值
        if (key.startsWith('scope:')) {
          const sc = scopes.value.find((s) => `scope:${s.id}` === key)
          return sc ? evaluateScope(books.value, sc.rules, sc.match) : books.value
        }
        return books.value
    }
  }

  /** 无状态行时的进度推导（与后端 stats 口径一致：≥99.5% 读完） */
  function derivedStatus(b: BookCard): 'unread' | 'reading' | 'finished' {
    const p = b.percent ?? 0
    if (p >= 99.5) return 'finished'
    return p > 0 ? 'reading' : 'unread'
  }

  const isSmart = computed(() => Boolean(smartKey.value))

  /** 侧栏「智能书架」计数：label → 数量 */
  const smartCounts = computed<Record<string, number>>(() => {
    const out: Record<string, number> = {}
    for (const label of Object.keys(SMART_KEYS)) out[label] = smartBooks(SMART_KEYS[label]).length
    return out
  })

  /** 按「库」分组键筛书（格式 / 待修复 / 无封面） */
  function facetBooks(key: string): BookCard[] {
    if (key.startsWith('fmt:')) {
      const f = key.slice(4).toUpperCase()
      return books.value.filter((b) => (b.format || '').toUpperCase() === f)
    }
    if (key === 'issues:1') return books.value.filter((b) => (b.issues || []).length > 0)
    if (key === 'nocover:1') {
      return books.value.filter((b) => (b.format || '').toUpperCase() === 'EPUB' && !b.has_cover)
    }
    return books.value
  }

  const shelfBooks = computed(() => {
    if (shelfFacet.value) return facetBooks(shelfFacet.value)
    if (smartKey.value) return smartBooks(smartKey.value)
    if (shelfTag.value) return books.value.filter((b) => (b.tags || []).includes(shelfTag.value))
    return books.value
  })

  /** 继续阅读：有进度且未读完，按最近阅读倒序 */
  const continueReading = computed(() =>
    books.value
      .filter((b) => (b.percent ?? 0) > 0 && (b.percent ?? 0) < 99.5)
      .sort((a, b) => (b.updated_at || 0) - (a.updated_at || 0)),
  )

  async function loadBooks(force = false): Promise<void> {
    if (loaded.value && !force) return
    loading.value = true
    try {
      const res = await api.books()
      books.value = res.items
      loaded.value = true
    } finally {
      loading.value = false
    }
  }

  /** 「库」分组（格式 / 待修复 / 无封面）：真实数据，空则拉取 */
  async function loadLibraries(force = false): Promise<void> {
    if (libraryGroups.value.length && !force) return
    try {
      libraryGroups.value = (await api.libraries()).items
    } catch {
      /* ignore */
    }
  }

  /** 自定义智能书架（smart_scopes 表）：规则存后端、求值在前端 */
  const scopes = ref<SmartScope[]>([])

  async function loadScopes(force = false): Promise<void> {
    if (scopes.value.length && !force) return
    try {
      scopes.value = (await api.smartScopes()).items
    } catch {
      /* ignore */
    }
  }

  /** 自定义书架计数：`scope:{id}` → 数量（侧栏徽标用，与内置 smartCounts 同一模式） */
  const scopeCounts = computed<Record<string, number>>(() => {
    const out: Record<string, number> = {}
    for (const s of scopes.value) {
      out[`scope:${s.id}`] = evaluateScope(books.value, s.rules, s.match).length
    }
    return out
  })

  function findBook(id: string): BookCard | null {
    return books.value.find((b) => b.id === id) ?? null
  }

  async function getBookDetail(id: string, force = false): Promise<BookDetail | null> {
    // force：元数据编辑后必须重取 —— 否则概览标签仍显示改之前的标题/作者/简介
    if (!force && details.value[id]) return details.value[id]
    try {
      const d = await api.bookDetail(id)
      details.value[id] = d
      return d
    } catch {
      return null
    }
  }

  /** 进入书库页并可选带标签筛选 */
  function openShelf(title: string, tag = ''): void {
    shelfTitle.value = title || '全部书库'
    shelfTag.value = tag
    smartKey.value = ''
    shelfFacet.value = ''
  }

  /** 进入智能书架（按阅读状态筛选） */
  function openSmart(title: string, key: string): void {
    shelfTitle.value = title || '智能书架'
    smartKey.value = key
    shelfTag.value = ''
    shelfFacet.value = ''
  }

  /** 进入「库」分组（按格式 / 待修复 / 无封面筛选） */
  function openLibrary(title: string, key: string): void {
    shelfTitle.value = title || '书库'
    shelfFacet.value = key
    smartKey.value = ''
    shelfTag.value = ''
  }

  return {
    books,
    details,
    loaded,
    loading,
    shelfTitle,
    shelfTag,
    smartKey,
    shelfFacet,
    libraryGroups,
    allTags,
    shelfBooks,
    continueReading,
    isSmart,
    smartCounts,
    smartKeyOf,
    smartBooks,
    loadBooks,
    loadLibraries,
    scopes,
    loadScopes,
    scopeCounts,
    findBook,
    getBookDetail,
    openShelf,
    openSmart,
    openLibrary,
    // 侧栏三组条目（静态导航）
    libraries: LIBRARIES,
    smartShelves: SMART_SHELVES,
    collections: COLLECTIONS,
  }
})
