/**
 * 侧栏三组导航条目的静态骨架（库 / 智能书架 / 收藏夹）。
 *
 * 计数一律不写死在数据里：
 *   · 智能书架 —— 由 stores/library.ts 按真实阅读状态（进度 / 批注数）计算。
 *   · 收藏夹   —— 由后端 SQLite 提供（见 stores/collections.ts）。
 *   · 库       —— 暂无真实分类数据源，只保留入口、不显示计数（避免假数字）。
 */

export interface NavEntry {
  id: string
  label: string
  icon: string
  /** 计数；不写则不渲染计数胶囊 */
  count?: number
}

/** 书库（侧栏「库」组）：条目由后端按格式/元数据真实聚合，这里仅保留空占位 */
export const LIBRARIES: NavEntry[] = []

/** 智能书架：标签与 store 的筛选键一一对应（见 SMART_KEYS） */
export const SMART_SHELVES: NavEntry[] = [
  { id: 'ss-recent', label: '最近添加', icon: 'sparkle' },
  { id: 'ss-unread', label: '未读', icon: 'sparkle' },
  { id: 'ss-reading', label: '在读', icon: 'sparkle' },
  { id: 'ss-done', label: '已完成', icon: 'sparkle' },
  { id: 'ss-annotated', label: '有批注', icon: 'sparkle' },
]

/** 收藏夹：条目来自后端 SQLite，这里仅保留空占位（侧栏会用真实数据覆盖） */
export const COLLECTIONS: NavEntry[] = []
