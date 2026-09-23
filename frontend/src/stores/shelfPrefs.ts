import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

import { notifyPrefsChanged, suppressing } from '@/lib/prefsBridge'

/**
 * 书架偏好（对应上游书架的 Display 面板）。
 *
 * 存 localStorage，与 `stores/coverPrefs`、`stores/theme` 一致 —— 本项目的「书架状态」类
 * 偏好都在前端。⚠️ 第 43 期起 `collapseSeries`（系列默认折叠）**额外**进偏好同步载荷的
 * `shelf` 块（与上游 `series-collapse-prefs` 同口径，换设备一致）；其余字段（视图 / 排序 /
 * 缩略图点击 / 筛选默认展开）仍**只存本机** —— 它们是「这台设备怎么看书架」。
 *
 * 用 pinia store 是为了让**侧栏进入书架时的设定**与书架页共用一份状态：
 * 从侧栏点不同的库 / 智能书架进来，视图与排序不该被重置。
 */

export type ShelfView = 'grid' | 'list' | 'table'
export type ShelfSort = 'title' | 'author' | 'series' | 'added' | 'progress' | 'pages' | 'stars'
export type SortDir = 'asc' | 'desc'
/** 书卡信息密度：紧凑只给书名 / 标准加作者 / 详细再加格式·年份·页数 */
export type CardInfo = 'compact' | 'standard' | 'detailed'
/** 点击缩略图 / 书卡后去哪：先看详情（默认）还是直接开读 */
export type ThumbnailClick = 'details' | 'reader'

export interface ShelfPrefs {
  view: ShelfView
  sort: ShelfSort
  dir: SortDir
  /** 折叠同系列：同系列的书合成一张卡 / 一行 */
  collapseSeries: boolean
  /**
   * 缩略图点击行为（对应上游 Behavior 页的 Thumbnail clicks）。
   * 默认 `details` —— 与这个开关存在之前的行为一致，老用户的书架不会突然换手感。
   */
  thumbnailClick: ThumbnailClick
  /**
   * 进书架页时统一筛选面板默认展开（对应上游 Behavior 的 Show filter preview by default）。
   * ⚠️ 这是**偏好**（初值），不是当前开合状态 —— 用户展开/收起一次不该改掉默认值。
   */
  filtersOpenByDefault: boolean
}

const KEY = 'nf-shelf-prefs'

export const SHELF_PREFS_DEFAULT: ShelfPrefs = {
  view: 'grid',
  sort: 'added',
  dir: 'desc',
  collapseSeries: false,
  thumbnailClick: 'details',
  filtersOpenByDefault: false,
}

export const THUMBNAIL_CLICK_OPTIONS: { value: ThumbnailClick; label: string; hint: string }[] = [
  { value: 'details', label: '先看详情', hint: '点封面进书籍详情页' },
  { value: 'reader', label: '直接阅读', hint: '能在线读的格式直接进阅读器' },
]

export const SHELF_VIEW_OPTIONS: { value: ShelfView; label: string }[] = [
  { value: 'grid', label: '网格' },
  { value: 'list', label: '列表' },
  { value: 'table', label: '表格' },
]

export const SHELF_SORT_OPTIONS: { value: ShelfSort; label: string }[] = [
  { value: 'added', label: '入库时间' },
  { value: 'title', label: '书名' },
  { value: 'author', label: '作者' },
  { value: 'series', label: '系列' },
  { value: 'progress', label: '阅读进度' },
  { value: 'pages', label: '页数' },
  { value: 'stars', label: '评分' },
]

export const CARD_INFO_OPTIONS: { value: CardInfo; label: string }[] = [
  { value: 'compact', label: '仅书名' },
  { value: 'standard', label: '书名 + 作者' },
  { value: 'detailed', label: '详细' },
]

function read(): ShelfPrefs {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return { ...SHELF_PREFS_DEFAULT }
    const p = JSON.parse(raw) as Partial<ShelfPrefs>
    return {
      view: SHELF_VIEW_OPTIONS.some((o) => o.value === p.view)
        ? (p.view as ShelfView)
        : SHELF_PREFS_DEFAULT.view,
      sort: SHELF_SORT_OPTIONS.some((o) => o.value === p.sort)
        ? (p.sort as ShelfSort)
        : SHELF_PREFS_DEFAULT.sort,
      dir: p.dir === 'asc' || p.dir === 'desc' ? p.dir : SHELF_PREFS_DEFAULT.dir,
      collapseSeries: Boolean(p.collapseSeries),
      // 老存档没有这个字段 ⇒ 落回 `details`，与开关出现之前的行为一致
      thumbnailClick: THUMBNAIL_CLICK_OPTIONS.some((o) => o.value === p.thumbnailClick)
        ? (p.thumbnailClick as ThumbnailClick)
        : SHELF_PREFS_DEFAULT.thumbnailClick,
      filtersOpenByDefault: Boolean(p.filtersOpenByDefault),
    }
  } catch {
    return { ...SHELF_PREFS_DEFAULT }
  }
}

export const useShelfPrefsStore = defineStore('shelfPrefs', () => {
  const prefs = ref<ShelfPrefs>(read())
  /** 书卡信息密度是书架级的独立偏好（不在 ShelfPrefs 里，因为它更像「显示」而非「书架状态」） */
  const cardInfo = ref<CardInfo>('standard')
  /**
   * 是否展开统一筛选面板。**当前开合状态**，初值取偏好 `filtersOpenByDefault` ——
   * 用户展开/收起只改状态、不改偏好，所以「默认」要回设置页改。
   */
  const filtersOpen = ref(prefs.value.filtersOpenByDefault)

  function save(): void {
    try {
      localStorage.setItem(KEY, JSON.stringify(prefs.value))
    } catch {
      /* 隐私模式下不可写：本次会话仍生效 */
    }
    notifyPrefsChanged()
  }

  function patch(p: Partial<ShelfPrefs>): void {
    prefs.value = { ...prefs.value, ...p }
    save()
  }

  /** 点同一列时切换升降序，点不同列时用该列的默认方向 */
  function sortBy(key: ShelfSort): void {
    const numeric = key === 'added' || key === 'progress' || key === 'pages' || key === 'stars'
    if (prefs.value.sort === key) {
      patch({ dir: prefs.value.dir === 'asc' ? 'desc' : 'asc' })
    } else {
      // 时间 / 数值类默认降序（新的、大的在前），文本类默认升序
      patch({ sort: key, dir: numeric ? 'desc' : 'asc' })
    }
  }

  function reset(): void {
    prefs.value = { ...SHELF_PREFS_DEFAULT }
    cardInfo.value = 'standard'
    save()
  }

  /**
   * 应用远端 `shelf` 块（第 43 期）：**只挑可同步键** `collapseSeries`，逐键校验后写入。
   *
   * 传进来的是整个 shelf 块；其余字段都是本机专属的（视图 / 排序 / 缩略图点击 / 筛选默认展开），
   * 整体 merge 会把它们冲成远端默认值 —— 故逐键挑、不整体 merge。做法对齐 `displayPrefs.applyRemote`。
   * 期间抑制通知，避免把刚拉下来的值又推回去（回环）。
   */
  function applyRemote(next: Partial<{ collapseSeries: boolean }>): void {
    suppressing(() => {
      if (typeof next.collapseSeries === 'boolean') {
        prefs.value = { ...prefs.value, collapseSeries: next.collapseSeries }
      }
      save()
    })
  }

  // 兜底：本 store 直接暴露了 `prefs` ref，`prefs.prefs.x = v` 这种写法不经过 patch。
  // 照 `displayPrefs` 的写法，watcher 保证它仍然落盘并通知同步层。
  watch(prefs, () => suppressing(() => save()), { deep: true })

  return { prefs, cardInfo, filtersOpen, patch, sortBy, reset, applyRemote }
})
