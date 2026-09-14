import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'

import {
  DEFAULT_SHELVES,
  DEFAULT_WIDGET_IDS,
  MAX_SHELVES,
  WIDGET_IDS,
  type ShelfDef,
  type WidgetId,
} from '@/data/dashboard'

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

function mergeShelves(stored: ShelfDef[] | null): ShelfDef[] {
  const valid = (stored ?? []).filter((s) => DEFAULT_SHELVES.some((d) => d.id === s.id))
  const seen = new Set(valid.map((s) => s.id))
  const added = DEFAULT_SHELVES.filter((d) => !seen.has(d.id))
  const merged = [...valid, ...added].slice(0, MAX_SHELVES)
  return merged.length ? merged : DEFAULT_SHELVES.map((s) => ({ ...s }))
}

export const useDashboardStore = defineStore('dashboard', () => {
  const widgets = ref<WidgetPref[]>(mergeWidgets(readJson<WidgetPref[] | null>(WIDGET_KEY, null)))
  const shelves = ref<ShelfDef[]>(
    mergeShelves(readJson<ShelfDef[] | null>(SHELF_KEY, null)).map((s) => ({ ...s })),
  )

  watch(widgets, (v) => writeJson(WIDGET_KEY, v), { deep: true })
  watch(shelves, (v) => writeJson(SHELF_KEY, v), { deep: true })

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

  /** 恢复默认：部件与书架都回到出厂状态 */
  function reset(): void {
    widgets.value = WIDGET_IDS.map((id) => ({ id, enabled: DEFAULT_WIDGET_IDS.includes(id) }))
    shelves.value = DEFAULT_SHELVES.map((s) => ({ ...s }))
  }

  return {
    widgets,
    shelves,
    enabledWidgets,
    enabledShelves,
    isEmpty,
    canAddShelf,
    toggleWidget,
    toggleShelf,
    moveWidget,
    moveShelf,
    shiftWidget,
    shiftShelf,
    removeShelf,
    addShelf,
    reset,
  }
})
