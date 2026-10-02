/**
 * 书源列表的**统计 / 筛选 / 排序**（第 86 期 sources-ui 增强 A+B 的纯逻辑）。
 *
 * 为什么抽成独立模块而不是写在 `SourcesView` 里：这套判据要被**单测钉住** ——
 * 尤其「统计条上的数字」与「点它筛出来的条数」必须永远相等，不相等时用户会认为
 * 界面在骗他（而组件里的一段 computed 只能靠跑起来肉眼比对）。
 *
 * 判据只依赖 `/api/sources` 已下发的字段（`enabled/imported/supported/group`）
 * 与台账里的最近验证（`verified_at/verify_ok/verify_ms`）—— **不新增接口**。
 */

export type Supported = 'yes' | 'partial' | 'no'

/** 列表里一行的**最小形状**（接口多给的字段不影响这里）。 */
export interface SourceLike {
  name: string
  display_name?: string
  /** 用户源（有规则文件）；false = 内置源（由代码注册） */
  user?: boolean
  enabled?: boolean
  imported?: boolean
  supported?: Supported | string
  group?: string
  /** 台账最近验证时间；`undefined` / `null` = **没验证过**（不是失败！） */
  verified_at?: number | null
  verify_ok?: boolean | null
  verify_ms?: number
}

export type SortKey = 'name' | 'group' | 'verified' | 'imported'

export interface SourceQuery {
  /** 名称 / 显示名 / 分组的模糊匹配（小写包含） */
  q?: string
  supported?: '' | Supported
  origin?: '' | 'imported' | 'manual'
  group?: string
  state?: '' | 'enabled' | 'disabled'
  verified?: '' | 'ok' | 'failed' | 'never'
  sort?: SortKey
  desc?: boolean
}

export const EMPTY_QUERY: SourceQuery = {
  q: '',
  supported: '',
  origin: '',
  group: '',
  state: '',
  verified: '',
  sort: 'name',
  desc: false,
}

const _text = (s: SourceLike): string =>
  `${s.name || ''} ${s.display_name || ''} ${s.group || ''}`.toLowerCase()

/** 这批源一共验证过没有（`verified_at` 有值才算）。 */
export const hasVerified = (s: SourceLike): boolean =>
  s.verified_at !== undefined && s.verified_at !== null

/** 徽章统计：列表条数就是这些数字的总和（`filterSources` 保证与之逐项相等）。 */
export interface SourceStats {
  total: number
  enabled: number
  disabled: number
  imported: number
  manual: number
  usable: number
  partial: number
  unsupported: number
  neverVerified: number
  verifyFailed: number
}

export function sourceStats(list: SourceLike[]): SourceStats {
  const st: SourceStats = {
    total: list.length, enabled: 0, disabled: 0, imported: 0, manual: 0,
    usable: 0, partial: 0, unsupported: 0, neverVerified: 0, verifyFailed: 0,
  }
  for (const s of list) {
    // ⚠️ 缺省口径与后端一致：没有台账行的源按「启用 / 未导入 / 可用」处理
    //（手写源就是这个形态，见 `sources/store.list_sources`）。
    if (s.enabled === false) st.disabled += 1
    else st.enabled += 1
    if (s.imported) st.imported += 1
    else st.manual += 1
    if (s.supported === 'no') st.unsupported += 1
    else if (s.supported === 'partial') st.partial += 1
    else st.usable += 1
    if (!hasVerified(s)) st.neverVerified += 1
    else if (s.verify_ok === false) st.verifyFailed += 1
  }
  return st
}

export function groupOptions(list: SourceLike[]): string[] {
  const set = new Set<string>()
  for (const s of list) if (s.group) set.add(s.group)
  return [...set].sort((a, b) => a.localeCompare(b, 'zh'))
}

function _match(s: SourceLike, q: SourceQuery): boolean {
  const text = (q.q || '').trim().toLowerCase()
  if (text && !_text(s).includes(text)) return false
  if (q.supported && (s.supported || 'yes') !== q.supported) return false
  if (q.origin === 'imported' && !s.imported) return false
  if (q.origin === 'manual' && s.imported) return false
  if (q.group && (s.group || '') !== q.group) return false
  if (q.state === 'enabled' && s.enabled === false) return false
  if (q.state === 'disabled' && s.enabled !== false) return false
  if (q.verified === 'ok' && !(hasVerified(s) && s.verify_ok === true)) return false
  if (q.verified === 'failed' && s.verify_ok !== false) return false
  // ⚠️「未验证」与「验证失败」是**两种状态**：这里只挑从没验证过的，
  //    绝不把失败也算进来（否则用户会以为失败=没试过，从而不做任何处置）。
  if (q.verified === 'never' && hasVerified(s)) return false
  return true
}

function _cmp(a: SourceLike, b: SourceLike, key: SortKey, dir: number): number {
  if (key === 'verified') {
    const ah = hasVerified(a)
    const bh = hasVerified(b)
    // ⚠️「没验证过」**永远排最后**（不受升降序影响）：它是「还没做」，
    //    不是「最小的值」—— 跟着方向跑会让用户以为它验证得很早/很晚。
    if (ah !== bh) return ah ? -1 : 1
    if (ah && bh) {
      const d = Number(a.verified_at) - Number(b.verified_at)
      if (d !== 0) return dir * d
    }
  } else if (key === 'imported') {
    const d = Number(!!b.imported) - Number(!!a.imported)   // 导入的排前面
    if (d !== 0) return dir * d
  } else if (key === 'group') {
    const d = (a.group || '').localeCompare(b.group || '', 'zh')
    if (d !== 0) return dir * d
  } else {
    const d = (a.name || '').localeCompare(b.name || '', 'zh')
    if (d !== 0) return dir * d
  }
  // 兜底永远**升序**：同键内按名称，顺序不随排序方向翻（否则同一组内看起来像随机）
  return (a.name || '').localeCompare(b.name || '', 'zh')
}

/** 筛选 + 排序（**纯函数**，不改入参）。空查询 = 原样返回（仅按名称升序）。 */
export function filterSources(list: SourceLike[], q: SourceQuery = {}): SourceLike[] {
  const out = list.filter((s) => _match(s, q))
  const key = q.sort || 'name'
  const dir = q.desc ? -1 : 1
  return out.sort((a, b) => _cmp(a, b, key, dir))
}
