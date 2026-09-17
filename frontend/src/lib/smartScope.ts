import type { BookCard } from './api'

/**
 * 自定义智能书架：规则的**存储在后端**（smart_scopes 表），**求值在前端**——
 * 书单本来就整体下发到客户端（含作者/出版社/题材/状态/评分），没必要为筛选再打一次接口。
 * 规则口径必须与后端校验一致（server.py 的 SCOPE_FIELDS / SCOPE_OPS），改动要两边同步。
 */

/** 规则字段。文本类用 contains 族，format/status 只支持 equals，stars/year 数值比较 */
export type ScopeField =
  | 'title' | 'author' | 'series' | 'publisher' | 'language'
  | 'tag' | 'format' | 'status' | 'stars' | 'year'

export type ScopeOp = 'contains' | 'not_contains' | 'equals' | 'at_least' | 'at_most'

export interface ScopeRule {
  field: ScopeField
  op: ScopeOp
  value: string
}

export interface SmartScope {
  id: number
  name: string
  rules: ScopeRule[]
  /** all = 规则全部满足（且），any = 满足其一（或） */
  match: 'all' | 'any'
  created_at: number
}

/** 每个字段允许的操作（与后端校验一致） */
export const FIELD_OPS: Record<ScopeField, ScopeOp[]> = {
  title: ['contains', 'not_contains', 'equals'],
  author: ['contains', 'not_contains', 'equals'],
  series: ['contains', 'not_contains', 'equals'],
  publisher: ['contains', 'not_contains', 'equals'],
  language: ['contains', 'not_contains', 'equals'],
  tag: ['contains', 'not_contains', 'equals'],
  format: ['equals'],
  status: ['equals'],
  stars: ['at_least', 'at_most'],
  year: ['at_least', 'at_most'],
}

export const FIELD_LABELS: Record<ScopeField, string> = {
  title: '书名',
  author: '作者',
  series: '系列',
  publisher: '出版社',
  language: '语言',
  tag: '题材',
  format: '格式',
  status: '阅读状态',
  stars: '评分',
  year: '出版年',
}

export const OP_LABELS: Record<ScopeOp, string> = {
  contains: '包含',
  not_contains: '不包含',
  equals: '等于',
  at_least: '至少',
  at_most: '至多',
}

/** 阅读状态口径：与 bookInfo.statusLabel / library.derivedStatus 一致（≥99.5% 读完） */
function statusOf(b: BookCard): string {
  if (b.status) return b.status
  const p = b.percent ?? 0
  if (p >= 99.5) return 'finished'
  return p > 0 ? 'reading' : 'unread'
}

function norm(v: unknown): string {
  return String(v ?? '').trim().toLowerCase()
}

/** 单条规则对一本书的判定。空 value 的规则视为恒真（用户还没填完，先不排除书） */
function ruleHit(b: BookCard, r: ScopeRule): boolean {
  const v = String(r.value ?? '').trim()
  if (!v) return true
  const needle = v.toLowerCase()
  switch (r.field) {
    case 'title':
    case 'author':
    case 'series':
    case 'publisher':
    case 'language': {
      const hay = norm(b[r.field])
      if (r.op === 'equals') return hay === needle
      if (r.op === 'not_contains') return !hay.includes(needle)
      return hay.includes(needle)
    }
    case 'tag': {
      const tags = (b.tags || []).map(norm)
      if (r.op === 'not_contains') return !tags.some((t) => t.includes(needle))
      if (r.op === 'equals') return tags.includes(needle)
      return tags.some((t) => t.includes(needle))
    }
    case 'format':
      return (b.format || '').toUpperCase() === v.toUpperCase()
    case 'status':
      return statusOf(b) === v
    case 'stars': {
      const n = Number(b.stars ?? 0)
      return r.op === 'at_most' ? n <= Number(v) : n >= Number(v)
    }
    case 'year': {
      const y = Number(String(b.year ?? '').replace(/\D/g, ''))
      if (!y) return false // 没标年份的书不参与年份比较，别被 0 归到「至多」
      return r.op === 'at_most' ? y <= Number(v) : y >= Number(v)
    }
    default:
      return true
  }
}

/** 求值一个书架规则组。match all = 且，any = 或；空规则 = 全部 */
export function evaluateScope(books: BookCard[], rules: ScopeRule[], match: 'all' | 'any'): BookCard[] {
  const rs = (rules || []).filter(Boolean)
  if (!rs.length) return books
  return books.filter((b) =>
    match === 'any' ? rs.some((r) => ruleHit(b, r)) : rs.every((r) => ruleHit(b, r)),
  )
}

/** 规则的人话描述，列表页与管理页共用 */
export function ruleText(r: ScopeRule): string {
  return `${FIELD_LABELS[r.field] ?? r.field} ${OP_LABELS[r.op] ?? r.op} ${r.value || '…'}`
}
