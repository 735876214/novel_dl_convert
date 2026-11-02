/**
 * 自定义智能书架：**类型 + 展示辅助**。
 *
 * ⚠️ 第 218 期起**求值在服务端**（`novelforge/core/bookrules.py`，唯一实现）：
 * 字段清单来自 `GET /api/book-rules`，规则由 `POST /api/smart-scopes/preview`
 * 实时预览、`GET /api/books?scope_id=` 取书。本文件不再包含任何判定逻辑 ——
 * 此前那份 TS 实现与后端白名单是同一判据的两处拷贝。
 */

/** 规则字段。具体可用值以服务端 schema 为准（这里不做联合类型，避免与后端漂移）。 */
export type ScopeField = string

/** 规则操作。同上，以服务端 schema 为准。 */
export type ScopeOp = string

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
  /** 手动排序键（第 154 期；越小越前） */
  sort_order?: number
  /** 命中数（第 218 期起由服务端按当前库计算） */
  count?: number
}

export interface RuleFieldSpec {
  key: string
  label: string
  kind: 'text' | 'list' | 'enum' | 'number'
  ops: string[]
  /** enum 字段的候选值（有值时表单渲染下拉；没有就当自由文本） */
  values?: { value: string; label: string }[]
}

export interface RuleOpSpec {
  key: string
  label: string
  /** false = 「为空 / 不为空」这类无值操作，表单不显示值输入框 */
  needs_value: boolean
}

export interface RuleSchema {
  fields: RuleFieldSpec[]
  ops: RuleOpSpec[]
}

/** `scope:{id}` → id；不是自定义书架键返回 null（侧栏 / 书架 / 仪表盘共用这一份判据）。 */
export function scopeIdOf(key: string | null | undefined): number | null {
  const text = String(key || '')
  if (!text.startsWith('scope:')) return null
  const id = Number(text.slice('scope:'.length))
  return Number.isInteger(id) && id > 0 ? id : null
}

/** schema → 表单用的查找表（字段名 / 字段可用操作 / 操作中文 / 是否需要值）。 */
export function schemaMaps(schema: RuleSchema | null) {
  const fields = schema?.fields || []
  const ops = schema?.ops || []
  const fieldLabels: Record<string, string> = {}
  const fieldOps: Record<string, string[]> = {}
  const fieldValues: Record<string, { value: string; label: string }[]> = {}
  for (const f of fields) {
    fieldLabels[f.key] = f.label
    fieldOps[f.key] = f.ops
    if (f.values?.length) fieldValues[f.key] = f.values
  }
  const opLabels: Record<string, string> = {}
  const opNeedsValue: Record<string, boolean> = {}
  for (const o of ops) {
    opLabels[o.key] = o.label
    opNeedsValue[o.key] = o.needs_value
  }
  return { fieldLabels, fieldOps, fieldValues, opLabels, opNeedsValue }
}

/** 规则的人话描述（管理页 / 列表共用）。schema 缺失时退回原始键名，不编造中文。 */
export function ruleText(r: ScopeRule, schema: RuleSchema | null = null): string {
  const m = schemaMaps(schema)
  const field = m.fieldLabels[r.field] ?? r.field
  const op = m.opLabels[r.op] ?? r.op
  const needsValue = m.opNeedsValue[r.op] ?? true
  return needsValue ? `${field} ${op} ${r.value || '…'}` : `${field} ${op}`
}
