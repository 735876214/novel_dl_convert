import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

/**
 * 表格视图的列面板偏好（第 158 期，对齐上游书架的列设置）。
 *
 * 分成两份落盘：
 * - **当前口径**（`nf-table-prefs`）：哪些列可见 / 行高密度 / 是否冻结书名列；
 * - **命名视图**（`nf-table-views`）：用户存下来的组合，可导入导出。
 *
 * 为什么不进偏好同步载荷：这三项是「这台设备怎么看表格」（同 `shelfPrefs` 的视图 /
 * 排序），换设备各自存 —— 与 `displayPrefs`（外观，跨设备同步）不是一类东西。
 *
 * ⚠️ **书名与操作列不可隐藏**：书名是这一行的身份、操作列是唯一入口；
 * 允许隐藏它们会造出「有行没有名字」或「有行没有入口」的表格。判据只在这里一处
 * （`toggleColumn` 直接忽略这两个键），面板只渲染 `TABLE_COLUMNS` 里的六列。
 */

export type TableColumnKey = 'author' | 'series' | 'format' | 'pages' | 'progress' | 'rating'
export type TableDensity = 'compact' | 'standard' | 'comfortable'

/** 可配置列（顺序即表格里的列序）。书名与操作列**不在**这张表里（不可隐藏）。 */
export const TABLE_COLUMNS: { key: TableColumnKey; label: string }[] = [
  { key: 'author', label: '作者' },
  { key: 'series', label: '系列' },
  { key: 'format', label: '格式' },
  { key: 'pages', label: '页数' },
  { key: 'progress', label: '进度' },
  { key: 'rating', label: '评分' },
]

export const DENSITY_OPTIONS: { value: TableDensity; label: string; hint: string }[] = [
  { value: 'compact', label: '紧凑', hint: '一屏看到更多行' },
  { value: 'standard', label: '标准', hint: '默认行高' },
  { value: 'comfortable', label: '宽松', hint: '触屏 / 大字体下更好点' },
]

export interface TablePrefs {
  /** 可见列（只含 `TABLE_COLUMNS` 的键，**按规范顺序**存，不按勾选顺序） */
  columns: TableColumnKey[]
  density: TableDensity
  /** 书名列吸附在左侧（横向滚动时不跟着走） */
  freezeTitle: boolean
}

export interface SavedTableView {
  id: string
  name: string
  prefs: TablePrefs
}

const PREFS_KEY = 'nf-table-prefs'
const VIEWS_KEY = 'nf-table-views'
/** 命名视图上限：这是个便利功能，不是配置仓库 —— 上限避免导入文件把它撑成垃圾场。 */
export const MAX_SAVED_VIEWS = 50

export const TABLE_PREFS_DEFAULT: TablePrefs = {
  columns: TABLE_COLUMNS.map((c) => c.key),
  density: 'standard',
  // 默认不冻结：改造前的表格就是普通滚动，换视图不该突然换手感
  freezeTitle: false,
}

function canonical(keys: unknown): TableColumnKey[] {
  const set = new Set(Array.isArray(keys) ? keys.map(String) : [])
  return TABLE_COLUMNS.map((c) => c.key).filter((k) => set.has(k))
}

function validDensity(v: unknown): TableDensity {
  return DENSITY_OPTIONS.some((o) => o.value === v) ? (v as TableDensity) : TABLE_PREFS_DEFAULT.density
}

/** 校验并补齐一份口径（坏值逐项回默认，不整份丢弃）。 */
export function normalizeTablePrefs(raw: unknown): TablePrefs {
  const p = (raw || {}) as Partial<TablePrefs>
  const cols = Array.isArray(p.columns) ? canonical(p.columns) : TABLE_PREFS_DEFAULT.columns
  return {
    // 空列集合不合法（至少留一列），退回默认可见集
    columns: cols.length ? cols : [...TABLE_PREFS_DEFAULT.columns],
    density: validDensity(p.density),
    freezeTitle: Boolean(p.freezeTitle),
  }
}

function readPrefs(): TablePrefs {
  try {
    const raw = localStorage.getItem(PREFS_KEY)
    return raw ? normalizeTablePrefs(JSON.parse(raw)) : { ...TABLE_PREFS_DEFAULT }
  } catch {
    return { ...TABLE_PREFS_DEFAULT }
  }
}

function readViews(): SavedTableView[] {
  try {
    const raw = localStorage.getItem(VIEWS_KEY)
    if (!raw) return []
    const arr = JSON.parse(raw)
    if (!Array.isArray(arr)) return []
    return arr
      .filter((v) => v && typeof v.id === 'string' && typeof v.name === 'string')
      .slice(0, MAX_SAVED_VIEWS)
      .map((v) => ({ id: v.id, name: v.name, prefs: normalizeTablePrefs(v.prefs) }))
  } catch {
    return []
  }
}

/** 视图 id：时间戳 + 进程内序号（不用随机数 —— 测试里要可预测、可复现）。 */
let seq = 0
function newId(): string {
  seq += 1
  return `v${Date.now().toString(36)}-${seq}`
}

export const useTablePrefsStore = defineStore('tablePrefs', () => {
  const prefs = ref<TablePrefs>(readPrefs())
  const views = ref<SavedTableView[]>(readViews())

  function savePrefs(): void {
    try {
      localStorage.setItem(PREFS_KEY, JSON.stringify(prefs.value))
    } catch {
      /* 隐私模式不可写：本次会话仍生效 */
    }
  }

  function saveViews(): void {
    try {
      localStorage.setItem(VIEWS_KEY, JSON.stringify(views.value))
    } catch {
      /* 同上 */
    }
  }

  function patch(p: Partial<TablePrefs>): void {
    prefs.value = normalizeTablePrefs({ ...prefs.value, ...p })
    savePrefs()
  }

  /** 勾 / 取消一列。书名与操作列不在可切换集合里，传进来也不会生效。 */
  function toggleColumn(key: TableColumnKey): void {
    if (!TABLE_COLUMNS.some((c) => c.key === key)) return
    const has = prefs.value.columns.includes(key)
    const next = has
      ? prefs.value.columns.filter((k) => k !== key)
      : canonical([...prefs.value.columns, key])
    // 至少留一列：全取消会让表格只剩书名与操作，等于把「表格」变成列表
    if (!next.length) return
    patch({ columns: next })
  }

  function reset(): void {
    prefs.value = { ...TABLE_PREFS_DEFAULT, columns: [...TABLE_PREFS_DEFAULT.columns] }
    savePrefs()
  }

  /** 存一份命名视图（同名则覆盖：用户再点「保存」通常就是想更新那一份）。 */
  function saveView(name: string): SavedTableView | null {
    const n = String(name || '').trim()
    if (!n) return null
    const existing = views.value.find((v) => v.name === n)
    const item: SavedTableView = {
      id: existing?.id || newId(),
      name: n,
      prefs: normalizeTablePrefs({ ...prefs.value }),
    }
    views.value = existing
      ? views.value.map((v) => (v.id === existing.id ? item : v))
      : [...views.value, item].slice(-MAX_SAVED_VIEWS)
    saveViews()
    return item
  }

  function applyView(id: string): boolean {
    const v = views.value.find((x) => x.id === id)
    if (!v) return false
    prefs.value = normalizeTablePrefs(v.prefs)
    savePrefs()
    return true
  }

  function deleteView(id: string): void {
    views.value = views.value.filter((v) => v.id !== id)
    saveViews()
  }

  /** 导出命名视图（JSON 文本，含版本字段便于以后迁移）。 */
  function exportViews(): string {
    return JSON.stringify({ version: 1, views: views.value }, null, 2)
  }

  /**
   * 导入命名视图：逐条校验，**合法的进、坏条目逐条忽略**并回报数量。
   *
   * 同名视图不覆盖 —— 导入是「把别人那份加进来」，覆盖会让用户丢了自己的那一份。
   */
  function importViews(text: string): { added: number; skipped: number; error: string } {
    let data: unknown
    try {
      data = JSON.parse(text)
    } catch {
      return { added: 0, skipped: 0, error: '不是合法的 JSON' }
    }
    const rawList = Array.isArray(data)
      ? data
      : (data && typeof data === 'object' ? (data as { views?: unknown }).views : null)
    if (!Array.isArray(rawList)) return { added: 0, skipped: 0, error: '找不到 views 数组' }
    let added = 0
    let skipped = 0
    const next = [...views.value]
    for (const raw of rawList) {
      const v = (raw || {}) as Partial<SavedTableView>
      const name = typeof v.name === 'string' ? v.name.trim() : ''
      if (!name || !v.prefs || next.some((x) => x.name === name) || next.length >= MAX_SAVED_VIEWS) {
        skipped += 1
        continue
      }
      next.push({ id: newId(), name, prefs: normalizeTablePrefs(v.prefs) })
      added += 1
    }
    views.value = next
    saveViews()
    return { added, skipped, error: '' }
  }

  watch(prefs, () => savePrefs(), { deep: true })

  return {
    prefs,
    views,
    patch,
    toggleColumn,
    reset,
    saveView,
    applyView,
    deleteView,
    exportViews,
    importViews,
  }
})
