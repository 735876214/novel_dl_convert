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
export function fmtBytes(bytes: number | null | undefined, empty = '—'): string {
  if (bytes === null || bytes === undefined || Number.isNaN(Number(bytes))) return empty
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let v = bytes
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i += 1
  }
  // 小数位：≥10 或 B 档取整，其余一位；**整数值不留 `.0`**（`1.0 KB` → `1 KB`）。
  const text = v.toFixed(v >= 10 || i === 0 ? 0 : 1)
  return `${text.endsWith('.0') ? text.slice(0, -2) : text} ${units[i]}`
}

/** 秒 → `1 小时 20 分` / `35 分钟`。不足一分钟按一分钟算（有阅读就算数）。 */
export function fmtDuration(seconds: number): string {
  if (!seconds) return '0 分钟'
  const h = Math.floor(seconds / 3600)
  const m = Math.round((seconds % 3600) / 60)
  if (h > 0) return `${h} 小时 ${m} 分`
  return `${Math.max(1, m)} 分钟`
}

/** 秒 → `90 分钟` / `3.5 小时` 这样的紧凑文案（图表轴与 tooltip 用，比 fmtDuration 短） */
export function fmtMinutes(seconds: number): string {
  const m = Math.round(seconds / 60)
  if (m < 60) return `${m} 分钟`
  const h = m / 60
  return `${Number.isInteger(h) ? h : h.toFixed(1)} 小时`
}

/** epoch **秒** → `2026-11-06`。**全前端唯一一处**（第 265 期把 6 份本地副本收回）。 */
export function fmtDay(sec: number | null | undefined, empty = '—'): string {
  const d = new Date(Number(sec) * 1000)
  if (!sec || Number.isNaN(d.getTime())) return empty
  return localDate(d)
}

/** epoch **秒** → `2026-11-06 14:30`（分）。唯一一处。 */
export function fmtDateTime(sec: number | null | undefined, empty = '—'): string {
  const d = new Date(Number(sec) * 1000)
  if (!sec || Number.isNaN(d.getTime())) return empty
  return `${localDate(d)} ${pad2(d.getHours())}:${pad2(d.getMinutes())}`
}

/** epoch **秒** → `2026-11-06 14:30:05`（秒）。唯一一处。 */
export function fmtDateTimeSec(sec: number | null | undefined, empty = '—'): string {
  const d = new Date(Number(sec) * 1000)
  if (!sec || Number.isNaN(d.getTime())) return empty
  return `${localDate(d)} ${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`
}

/** 钟点 `HH:mm`（从 Date 取本地时分）。时间轴 tooltip 与图表刻度共用。 */
export function fmtClockHM(d: Date): string {
  return `${pad2(d.getHours())}:${pad2(d.getMinutes())}`
}

/**
 * **时长 / 播放位置** → `1:05:20` / `5:20`。
 *
 * 与 `fmtDuration`（`1 小时 20 分`）刻意分开：这里是**时钟读数**（音轨进度、书签时间点），
 * 那里是**人话**（「读了多久」）。
 */
export function fmtClock(sec: number): string {
  const s0 = Number.isFinite(sec) ? Math.max(0, Math.floor(sec)) : 0
  const h = Math.floor(s0 / 3600)
  const m = Math.floor(s0 / 60) % 60
  const s = s0 % 60
  return h ? `${h}:${pad2(m)}:${pad2(s)}` : `${m}:${pad2(s)}`
}

/** 相对时间 → `刚刚` / `3 小时前` / `2 天前`。唯一一处。 */
export function fmtAgo(sec: number | null | undefined, empty = '—'): string {
  if (!sec) return empty
  const diff = Math.max(0, Date.now() / 1000 - Number(sec))
  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`
  return `${Math.floor(diff / 86400)} 天前`
}

/**
 * 「今天 14:30 / 11-06 14:30 / 2025-11-06 14:30」—— 越近越省年份。
 *
 * Book Dock 那类「刚发生过的事」用它：一眼看出是不是今天的，比完整日期有用。
 */
export function fmtWhen(sec: number | null | undefined, empty = '—'): string {
  const d = new Date(Number(sec) * 1000)
  if (!sec || Number.isNaN(d.getTime())) return empty
  const hm = `${pad2(d.getHours())}:${pad2(d.getMinutes())}`
  const now = new Date()
  if (d.getFullYear() === now.getFullYear()) {
    if (d.getMonth() === now.getMonth() && d.getDate() === now.getDate()) return `今天 ${hm}`
    return `${pad2(d.getMonth() + 1)}-${pad2(d.getDate())} ${hm}`
  }
  return `${localDate(d)} ${hm}`
}

// ⚠️ 上面的 `fmt*` 是**唯一实现**（第 265 期收敛：此前 `fmtBytes` 有 11 份本地副本、
// 日期/时间有 13 份，取整规则 5 种 ⇒ 同一个 1.5 MB 在不同页面显示 1.5/1.50/2 MB）。
// `tests/test_shared_formatters_265.py` 钉住「除了本文件，不许再定义这些名字」。

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
