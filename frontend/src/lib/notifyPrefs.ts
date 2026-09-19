import type { LogItem } from '@/lib/api'

/**
 * 通知偏好：按「活动类别」控制通知中心显示哪些记录。
 *
 * ⚠️ 与上游的差异（页面里也如实标注）：
 *   上游的通知是**服务端投递**——每类事件可设 Off / Problems / All，可走邮件等渠道，并有已读态。
 *   本项目的「通知」就是活动日志的视图（`GET /api/logs`），没有投递渠道、没有已读态。
 *   因此这里的开关是**客户端过滤**：按日志的 `action` 归类、按 `status` 决定 Off/Problems/All
 *   实际生效的范围就是通知中心与日志页看到的条目。
 *
 * 类别 ←→ 后端 action 常量的映射见 `novelforge/core/activity_log.py`（转换/添加/重命名/清理）。
 */

export type NotifyLevel = 'off' | 'problems' | 'all'

export interface NotifyCategory {
  id: string
  label: string
  /** 匹配日志条目的 action 值 */
  actions: string[]
  desc: string
}

export const NOTIFY_CATEGORIES: NotifyCategory[] = [
  { id: 'convert', label: '转换', actions: ['转换'], desc: 'txt → EPUB 的转换结果' },
  { id: 'add', label: '添加', actions: ['添加'], desc: '文件进入成品目录的记录' },
  { id: 'rename', label: '重命名', actions: ['重命名'], desc: '实体改名（服务端元数据）与同名冲突修复' },
  { id: 'recycle', label: '清理', actions: ['清理'], desc: '重复书 / 缺失资源移入回收目录' },
]

export const NOTIFY_LEVELS: { value: NotifyLevel; label: string; hint: string }[] = [
  { value: 'off', label: '关闭', hint: '完全不显示该类记录' },
  { value: 'problems', label: '仅失败', hint: '只显示失败的记录' },
  { value: 'all', label: '全部', hint: '成功与失败都显示' },
]

export type NotifyPrefs = Record<string, NotifyLevel>

export const NOTIFY_PREFS_KEY = 'nf-notify-prefs'

/** 默认全开（与改动前的行为一致，避免升级后通知突然消失） */
export const NOTIFY_PREFS_DEFAULT: NotifyPrefs = {
  convert: 'all',
  add: 'all',
  rename: 'all',
  recycle: 'all',
}

export function readNotifyPrefs(): NotifyPrefs {
  try {
    const raw = localStorage.getItem(NOTIFY_PREFS_KEY)
    if (!raw) return { ...NOTIFY_PREFS_DEFAULT }
    const parsed = JSON.parse(raw) as Partial<NotifyPrefs>
    const out: NotifyPrefs = { ...NOTIFY_PREFS_DEFAULT }
    for (const c of NOTIFY_CATEGORIES) {
      const v = parsed?.[c.id]
      if (v === 'off' || v === 'problems' || v === 'all') out[c.id] = v
    }
    return out
  } catch {
    return { ...NOTIFY_PREFS_DEFAULT }
  }
}

export function saveNotifyPrefs(prefs: NotifyPrefs): void {
  try {
    localStorage.setItem(NOTIFY_PREFS_KEY, JSON.stringify(prefs))
  } catch {
    /* 隐私模式下 localStorage 不可写：偏好仅本次会话生效 */
  }
}

/** 条目所属类别；未识别的 action 返回 null（这类条目始终显示，不会被偏好误隐藏） */
export function categoryOf(item: LogItem): NotifyCategory | null {
  const action = String(item.action ?? '')
  if (!action) return null
  return NOTIFY_CATEGORIES.find((c) => c.actions.includes(action)) ?? null
}

/** 按偏好过滤日志条目。
 *
 * 泛型化的原因：`NotificationItem`（日志 + id + 已读态）继承自 `LogItem`，
 * 若这里固定返回 `LogItem[]`，调用方过完滤就丢了 id / read 字段。
 */
export function applyNotifyPrefs<T extends LogItem>(items: T[], prefs: NotifyPrefs): T[] {
  return items.filter((it) => {
    const cat = categoryOf(it)
    if (!cat) return true
    const level = prefs[cat.id] ?? 'all'
    if (level === 'off') return false
    if (level === 'problems') return String(it.status ?? '') === '失败'
    return true
  })
}

/** 被偏好隐藏的条数（用于在通知中心给出可解释的提示，而不是让用户以为记录丢了） */
export function hiddenByPrefs(items: LogItem[], prefs: NotifyPrefs): number {
  return items.length - applyNotifyPrefs(items, prefs).length
}
