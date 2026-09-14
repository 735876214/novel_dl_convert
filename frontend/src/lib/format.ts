/**
 * 格式化与展示用的小工具。
 *
 * 注意：v2 里有一个 esc() 用于手工拼 HTML 时转义，迁移到 Vue 后不再需要
 * —— Vue 的 {{ }} 插值默认转义，v-html 只用在内部常量上。
 */
import type { TaskStatus } from '@/data/tasks'

/** 取整加百分号 */
export function pct(n: number): string {
  return `${Math.round(n)}%`
}

/** 千分位 */
export function thousands(n: number): string {
  return n.toLocaleString('zh-CN')
}

/** 大数字缩写：1200 → 1.2k */
export function compact(n: number): string {
  if (n < 1000) return String(n)
  if (n < 10000) return `${(n / 1000).toFixed(1)}k`
  return `${Math.round(n / 1000)}k`
}

export interface StatusMeta {
  dot: string
  text: string
  cls: string
}

const STATUS_META: Record<TaskStatus, StatusMeta> = {
  running: { dot: 'run', text: '进行中', cls: '' },
  done: { dot: 'done', text: '已完成', cls: 'ok' },
  queued: { dot: 'queue', text: '排队中', cls: '' },
  failed: { dot: 'fail', text: '失败', cls: 'err' },
}

/** 任务状态 → 圆点样式 / 文案 / 徽章 class。迁移自 v2 的 statusMeta() */
export function statusMeta(status: TaskStatus): StatusMeta {
  return STATUS_META[status] ?? { dot: 'queue', text: '未知', cls: '' }
}
