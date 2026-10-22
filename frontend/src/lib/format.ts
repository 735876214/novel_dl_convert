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

/** 字节 → `1.2 GB` 这样的文案。支持到 TB 档。统计页与图表共用一份。 */
export function fmtBytes(bytes: number): string {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let v = bytes
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i += 1
  }
  return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${units[i]}`
}

/** 秒 → `1 小时 20 分` / `35 分`。不足一分钟按一分钟算（有阅读就算数）。 */
export function fmtDuration(seconds: number): string {
  if (!seconds) return '0 分'
  const h = Math.floor(seconds / 3600)
  const m = Math.round((seconds % 3600) / 60)
  if (h > 0) return `${h} 小时 ${m} 分`
  return `${Math.max(1, m)} 分`
}

/** 秒 → `90 分钟` / `3.5 小时` 这样的紧凑文案（图表轴与 tooltip 用，比 fmtDuration 短） */
export function fmtMinutes(seconds: number): string {
  const m = Math.round(seconds / 60)
  if (m < 60) return `${m} 分钟`
  const h = m / 60
  return `${Number.isInteger(h) ? h : h.toFixed(1)} 小时`
}

// ⚠️ 项目里另有**两处** `fmtBytes`，刻意不合并到这里 —— 它们是有意的场景特化：
// `LibraryOverviewWidget.vue:21` 只给 MB / GB 两档（仪表盘小卡片放不下更细的档），
// `MaintenancePage.vue:72` 要处理 null 且不含 TB 档。合并会把特化抹平成一种。

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
export function statusMeta(status: string): StatusMeta {
  // 入参放宽为 string：任务状态来自服务端，本地类型只是收窄视图。
  // 未知值走下面的兜底，不抛错也不误判成「进行中」。
  return STATUS_META[status as TaskStatus] ?? { dot: 'queue', text: '未知', cls: '' }
}


/**
 * **本地**日期串 `YYYY-MM-DD` —— 全前端唯一一处（第 135 期收敛）。
 *
 * ⚠️ **别写 `toISOString().slice(0, 10)`**：那是 **UTC** 日期，在东八区本地
 * 00:00–08:00 之间会算成前一天。服务端口径是本地日（`date` + `start` 合成 naive
 * 本地时间取 `.timestamp()`，聚合用 `time.localtime()` 分日），两边必须同一把尺子，
 * 否则「手工补录」会被记到昨天、当天统计是空的。
 */
export function localDate(d: Date = new Date()): string {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`
}

/**
 * 本地日期串 `YYYY-MM-DD` → 本地**当日零点**的 epoch 秒（第 142 期）。
 *
 * ⚠️ 别用 `Date.parse('2026-10-22')`：按 ECMAScript 规范它是 **UTC 午夜**，在 UTC 以西的
 * 时区（NAS 常见 `TZ=America/New_York`）会退回前一天 —— `ReadingRecord` 的「开始日期」
 * 存下去再读回来就自己退一天。与 `localDate` 同一把尺子：显用本地、存也用本地。
 */
export function localDateToEpoch(s: string): number {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(s || '').trim())
  if (!m) return 0
  return Math.floor(new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])).getTime() / 1000)
}

/** 本地月串 `YYYY-MM`（月历分组用，与 `localDate` 同一时区口径） */
export function localMonth(d: Date = new Date()): string {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}`
}

function pad2(n: number): string {
  return String(n).padStart(2, '0')
}
