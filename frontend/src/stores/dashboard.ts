import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'

import {
  DEFAULT_SHELF_LAYOUT,
  DEFAULT_SHELVES,
  DEFAULT_WIDGET_IDS,
  MAX_SHELVES,
  WIDGET_IDS,
  type ShelfDef,
  type ShelfLayout,
  type ShelfType,
  type WidgetId,
} from '@/data/dashboard'

const SHELF_TYPES: ShelfType[] = ['continue', 'recent', 'discover', 'scope']

/**
 * 仪表盘偏好：部件的启用与顺序、书架行的启用与顺序。
 *
 * 与 BookOrbit 的差异（已知偏离，已在计划中标注）：
 *   BookOrbit 把 widget 偏好存服务端账户、shelf 偏好存 localStorage；
 *   本项目纯静态无后端，**两者都存 localStorage**。
 *   将来接后端时只需替换 widget 的读写实现，渲染层契约不变。
 */
const WIDGET_KEY = 'dashboard-widgets'
const SHELF_KEY = 'dashboard-shelves'
/** 书架总布局（单列 / 两列，第 82 期新增键） */
const LAYOUT_KEY = 'dashboard-shelf-layout'

export interface WidgetPref {
  id: WidgetId
  enabled: boolean
}

function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return fallback
    return JSON.parse(raw) as T
  } catch {
    return fallback
  }
}

function writeJson(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    /* 忽略存储不可用 */
  }
}

/**
 * 合并策略：持久化项与注册表做并集。
 *   · 注册表新增的部件默认启用并追加到尾部（老用户的偏好不被覆盖）
 *   · 注册表中已消失的 id 丢弃
 */
function mergeWidgets(stored: WidgetPref[] | null): WidgetPref[] {
  const valid = (stored ?? []).filter((p) => WIDGET_IDS.includes(p.id))
  const seen = new Set(valid.map((p) => p.id))
  const added = WIDGET_IDS.filter((id) => !seen.has(id)).map((id) => ({
    id,
    enabled: DEFAULT_WIDGET_IDS.includes(id),
  }))
  return [...valid, ...added].map((p) => ({ ...p }))
}

/** 书架行数收敛到 1..3（旧数据缺字段 ⇒ 当 1，不写迁移脚本） */
function normalizeRows(value: unknown): number {
  const n = Math.round(Number(value))
  return Number.isFinite(n) ? Math.min(3, Math.max(1, n)) : 1
}

/**
 * 库范围收敛（第 83 期）：只留非空字符串并去重。
 *
 * **空数组 = 全部书库**（`lib/shelfScope.ts` 的唯一口径）——所以这里**不**做「至少一个」的兜底：
 * 那是面板的交互约束（取消最后一个勾选时拒绝），不是数据约束。
 * ⚠️ 指向已删除书库的 id 保留在偏好里（store 不知道有哪些库），过滤时忽略即可。
 */
function normalizeLibraryIds(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  const out: string[] = []
  for (const v of value) {
    if (typeof v === 'string' && v && !out.includes(v)) out.push(v)
  }
  return out
}

function mergeShelves(stored: ShelfDef[] | null): ShelfDef[] {
  // 只按「类型合法」保留用户书架（含自定义的 scope / 额外行），而不是按默认 id 白名单，
  // 否则用户新增的行一刷新就丢。
  const valid = (stored ?? []).filter(
    (s): s is ShelfDef => Boolean(s) && typeof s.id === 'string' && SHELF_TYPES.includes(s.type),
  )
  const seen = new Set(valid.map((s) => s.id))
  const added = DEFAULT_SHELVES.filter((d) => !seen.has(d.id))
  const merged = [...valid, ...added].slice(0, MAX_SHELVES).map((s) => ({
    ...s,
    rows: normalizeRows(s.rows),
    library_ids: normalizeLibraryIds(s.library_ids),
  }))
  return merged.length
    ? merged
    : DEFAULT_SHELVES.map((s) => ({ ...s, rows: 1, library_ids: [] }))
}

/** 布局值只认两个合法档，其它（含旧数据里的脏值）一律回落单列 */
function normalizeLayout(value: unknown): ShelfLayout {
  return value === 'two-columns' ? 'two-columns' : DEFAULT_SHELF_LAYOUT
}

export const useDashboardStore = defineStore('dashboard', () => {
  const widgets = ref<WidgetPref[]>(mergeWidgets(readJson<WidgetPref[] | null>(WIDGET_KEY, null)))
  const shelves = ref<ShelfDef[]>(
    mergeShelves(readJson<ShelfDef[] | null>(SHELF_KEY, null)).map((s) => ({ ...s })),
  )
  /** 书架总布局：单列 / 两列（第 82 期对齐 BookOrbit 的 SHELF_LAYOUT） */
  const shelfLayout = ref<ShelfLayout>(normalizeLayout(readJson<unknown>(LAYOUT_KEY, null)))

  watch(widgets, (v) => writeJson(WIDGET_KEY, v), { deep: true })
  watch(shelves, (v) => writeJson(SHELF_KEY, v), { deep: true })
  watch(shelfLayout, (v) => writeJson(LAYOUT_KEY, v))

  const enabledWidgets = computed(() => widgets.value.filter((w) => w.enabled))
  const enabledShelves = computed(() => shelves.value.filter((s) => s.enabled))

  /** 全部部件与书架都被关闭时的空状态 */
  const isEmpty = computed(() => enabledWidgets.value.length === 0 && enabledShelves.value.length === 0)

  const canAddShelf = computed(() => shelves.value.length < MAX_SHELVES)

  function toggleWidget(id: WidgetId): void {
    const target = widgets.value.find((w) => w.id === id)
    if (target) target.enabled = !target.enabled
  }

  function toggleShelf(id: string): void {
    const target = shelves.value.find((s) => s.id === id)
    if (target) target.enabled = !target.enabled
  }

  /** 拖拽排序：把 from 位置的项移到 to 位置 */
  function moveWidget(from: number, to: number): void {
    if (from === to || from < 0 || to < 0) return
    const list = widgets.value
    if (from >= list.length || to >= list.length) return
    const [moved] = list.splice(from, 1)
    list.splice(to, 0, moved)
  }

  /**
   * 按「可见子集的新顺序」重排部件（第 82 期，行内拖拽用）。
   *
   * ⚠️ 行内渲染的是**可见子集**（已启用 ∩ 已实现 ∩ 当前库能力满足），
   * 而 `moveWidget` 用的是**全量**列表索引 —— 直接把可见索引传过去会排错位。
   * 做法：取可见项在全量列表中的下标集合，按新顺序回填对应 id，
   * 不可见项保持原相对次序填进剩余下标。
   */
  function applyVisibleOrder(orderedIds: WidgetId[]): void {
    if (!orderedIds.length) return
    const slotOf = new Map(orderedIds.map((id, i) => [id, i]))
    const visibleSlots: number[] = []
    widgets.value.forEach((w, i) => {
      if (slotOf.has(w.id)) visibleSlots.push(i)
    })
    if (visibleSlots.length !== orderedIds.length) return
    const next = [...widgets.value]
    orderedIds.forEach((id, i) => {
      next[visibleSlots[i]] = { ...next[visibleSlots[i]], id }
    })
    widgets.value = next
  }

  /** 书架总布局（单列 / 两列） */
  function setShelfLayout(layout: ShelfLayout): void {
    shelfLayout.value = layout
  }

  /** 设置某个书架行的行数（1..3，越界夹取；行数决定该行拉取的封面数） */
  function setShelfRows(id: string, rows: number): void {
    const target = shelves.value.find((s) => s.id === id)
    if (target) target.rows = normalizeRows(rows)
  }

  /**
   * 设置某个书架行的「库范围」（第 83 期）。
   *
   * **传空数组 = 全部书库** —— 面板的「全部书库」选项就是调它（而不是另设一个布尔字段）。
   * 判定侧的唯一解释在 `lib/shelfScope.ts::filterByLibraries`。
   */
  function setShelfLibraries(id: string, ids: string[]): void {
    const target = shelves.value.find((s) => s.id === id)
    if (target) target.library_ids = normalizeLibraryIds(ids)
  }

  function moveShelf(from: number, to: number): void {
    if (from === to || from < 0 || to < 0) return
    const list = shelves.value
    if (from >= list.length || to >= list.length) return
    const [moved] = list.splice(from, 1)
    list.splice(to, 0, moved)
  }

  /** 键盘可达路径：上移 / 下移（与 BookOrbit 的上下箭头一致） */
  function shiftWidget(id: WidgetId, delta: -1 | 1): void {
    const idx = widgets.value.findIndex((w) => w.id === id)
    if (idx < 0) return
    const to = idx + delta
    if (to < 0 || to >= widgets.value.length) return
    moveWidget(idx, to)
  }

  function shiftShelf(id: string, delta: -1 | 1): void {
    const idx = shelves.value.findIndex((s) => s.id === id)
    if (idx < 0) return
    const to = idx + delta
    if (to < 0 || to >= shelves.value.length) return
    moveShelf(idx, to)
  }

  /** 至少保留 1 个书架：最后一个不可移除 */
  function removeShelf(id: string): void {
    if (shelves.value.length <= 1) return
    shelves.value = shelves.value.filter((s) => s.id !== id)
  }

  function addShelf(def: ShelfDef): boolean {
    if (!canAddShelf.value) return false
    shelves.value.push({ ...def })
    return true
  }

  /** 恢复默认：部件与书架都回到出厂状态（含清空库范围与行数） */
  function reset(): void {
    widgets.value = WIDGET_IDS.map((id) => ({ id, enabled: DEFAULT_WIDGET_IDS.includes(id) }))
    shelves.value = DEFAULT_SHELVES.map((s) => ({ ...s, rows: 1, library_ids: [] }))
    shelfLayout.value = DEFAULT_SHELF_LAYOUT
  }

  return {
    widgets,
    shelves,
    shelfLayout,
    enabledWidgets,
    enabledShelves,
    isEmpty,
    canAddShelf,
    toggleWidget,
    toggleShelf,
    moveWidget,
    moveShelf,
    applyVisibleOrder,
    setShelfLayout,
    setShelfRows,
    setShelfLibraries,
    shiftWidget,
    shiftShelf,
    removeShelf,
    addShelf,
    reset,
  }
})
