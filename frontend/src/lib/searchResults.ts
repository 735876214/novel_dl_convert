/**
 * 「探索发现」多源检索结果的纯逻辑（第 71 期）—— **唯一真值源**。
 *
 * 后端把各源命中「列全、别丢、别骗」地交回来（含逐源状态）之后，剩下三件事全是纯计算：
 * 同名合并、匹配度排序、分页追加。单独一个模块的理由与 `readerFlow.ts` 一样 ——
 * 每一条错了都是肉眼可见的毛病（同一本书刷屏 / 最想找的那本排在后面 /
 * 「加载更多」把第一页又显示一遍），塞在组件里既难测也难讲清。组件只做「取数 → 调这里 → 渲染」。
 *
 * ⚠️ **合并必须保守**：宁可两行，不可错并。理由具体到本案：
 * - 书名相同但作者不同 ⇒ 大概率是两本书（同名重名在中文书里很常见）；
 * - 「三体」与「三体 2」「三体（全集）」靠相似度猜，会把不同卷并成一个 ——
 *   并错的代价是用户想下第二卷却点到第一卷，比看到两行糟得多；
 * - 一方作者**未知**（后端用「未知」占位）时无从判断，一律不并。
 */
import type { SearchHit, SearchSourceState } from '@/lib/api'

/** 合并后的「一本书」：一个标题 + 若干来源命中 */
export interface HitGroup {
  /** 分组键：可合并的 = `书名␀作者`（都已归一化）；不可合并的 = `single:<序号>` */
  key: string
  /** 展示用标题（取组内第一条的原文，不做改写） */
  title: string
  /** 展示用作者（组内第一条的作者原文） */
  author: string
  /** 组内各来源的命中，**保持后端给出的顺序** */
  hits: SearchHit[]
}

/**
 * 后端在作者缺失时用的占位（`gutenberg` 就是这么写的）。
 *
 * 它们必须归一化成「不知道」：否则两本毫不相干的书会因为作者都是「未知」而并成一组 ——
 * 这是本模块最容易出错的地方，所以判据放在这里、只放一处。
 */
const UNKNOWN_AUTHORS = new Set([
  '未知', '佚名', '匿名', '不详', '无', 'n/a', 'na', 'unknown', 'anonymous', 'none', '-', '—',
])

/** 书名里**不参与比对**的符号（书名号、各种括号、分隔与标点、空白） */
const TITLE_NOISE = /[《》〈〉「」『』【】[\]()（）<>·•・.,，。:：;；!！?？"'“”‘’`~_\-—–\\/|+*=&^%$#@\s]/g

/**
 * 书名归一化：全角→半角、去书名号与标点、去空白、ASCII 小写。
 *
 * 用 `NFKC` 而不是自己写一张全角映射表：它同时覆盖全角字母/数字/标点
 * （`Ｔｈｅ` → `The`、`（` → `(`），手写表一定会漏。
 * ⚠️ **不做**「去副标题 / 去序号」：那是猜，会制造错误合并（见模块注释）。
 */
export function normalizeTitle(raw: string): string {
  return String(raw ?? '')
    .normalize('NFKC')
    .replace(TITLE_NOISE, '')
    .toLowerCase()
}

/**
 * 作者归一化：取第一个作者、去标点空白、ASCII 小写；占位作者一律归为**空串**（= 不知道）。
 *
 * 多作者不排序、不做「姓 名 ↔ 名 姓」的猜测：那两件事都需要语言知识，猜错就是错误合并。
 */
export function normalizeAuthor(raw: string): string {
  const text = String(raw ?? '')
  const whole = text.normalize('NFKC').replace(TITLE_NOISE, '').toLowerCase()
  // ⚠️ 占位判定要在**按分隔符切多作者之前**：`N/A` 里的 `/` 既是多作者分隔符，
  // 本身又是一个「没有作者」的占位 —— 先切就会把它切成孤零零一个 `n`。
  if (!whole || UNKNOWN_AUTHORS.has(whole)) return ''
  const first = text.split(/[,，;；/、&]|\band\b/i)[0] ?? ''
  const s = first.normalize('NFKC').replace(TITLE_NOISE, '').toLowerCase()
  return UNKNOWN_AUTHORS.has(s) ? '' : s
}

/**
 * 把命中按「同一本书」合并（第 71 期）。
 *
 * 只有**书名与作者都归一化成功且分别相同**才合并；其余一律各自成组
 * （作者未知、书名空、单条命中都走这条路）。组内顺序 = 后端给出的顺序，
 * 组间顺序 = 首次出现的顺序（排序交给 `rankGroups`）。
 */
export function groupHits(hits: SearchHit[]): HitGroup[] {
  const out: HitGroup[] = []
  const at = new Map<string, HitGroup>()
  hits.forEach((hit, i) => {
    const nt = normalizeTitle(hit.title ?? '')
    const na = normalizeAuthor(hit.author ?? '')
    const key = nt && na ? `${nt}\u0000${na}` : `single:${i}`
    const found = at.get(key)
    if (found) {
      found.hits.push(hit)
      return
    }
    const g: HitGroup = { key, title: hit.title ?? '', author: hit.author ?? '', hits: [hit] }
    at.set(key, g)
    out.push(g)
  })
  return out
}

/**
 * 组内**去重后的来源名**（「N 个来源」里的 N，以及展开后逐条列的徽章）。
 *
 * 用 `Set` 而不是 `hits.length`：同一个源可能给出多条（不同版本），
 * 那时说「2 条命中」比说「2 个来源」诚实。
 */
export function sourcesOf(group: HitGroup): string[] {
  return [...new Set(group.hits.map((h) => h.source).filter(Boolean))]
}

/** 书名匹配档位：0 完全相同 > 1 前缀/包含 > 2 其它（越小越前） */
function matchTier(title: string, keyword: string): number {
  if (!keyword) return 2
  const t = normalizeTitle(title)
  if (!t) return 3
  if (t === keyword) return 0
  if (t.startsWith(keyword) || t.includes(keyword)) return 1
  return 2
}

/**
 * 按匹配度排序（稳定）：书名完全相同 → 前缀/包含 → 其它；同档内**有作者的优先**；
 * 再同则保持原顺序。
 *
 * 显式带上「原下标」做兜底比较：`Array.sort` 的稳定性在规范里是有保证的，
 * 但这里再钉一次，免得将来有人把实现换成不稳定的比较器时顺序开始抖。
 * ⚠️ 不修改入参数组（返回新数组）—— 列表在分页追加后会被重新排，
 * 就地排会让「上一页的顺序」变成一份会被悄悄改写的状态。
 */
export function rankGroups(groups: HitGroup[], keyword: string): HitGroup[] {
  const kw = normalizeTitle(keyword)
  return groups
    // ⚠️ 判「有没有作者」要用**归一化后**的（`normalizeAuthor`）而不是原文字符串：
    // 作者原文是「未知」这种占位时它非空，按真值判会把它当成「有作者信息」排到前面。
    .map((g, i) => ({ g, i, tier: matchTier(g.title, kw), noAuthor: normalizeAuthor(g.author) ? 0 : 1 }))
    .sort((a, b) => (a.tier - b.tier) || (a.noAuthor - b.noAuthor) || (a.i - b.i))
    .map((x) => x.g)
}

/**
 * 把新一页的命中**追加**到已累计的结果上，返回新数组与真正新增的条数。
 *
 * 去重键是 `source + url`：同源同地址在分页里重复出现（有些站点「最后一页」会不停
 * 回吐同一页内容）时就跳过，避免列表里出现成对重复。**不同源**的同名书不去重 ——
 * 那正是要合并展示的对象（交给 `groupHits`）。
 */
export function appendHits(existing: SearchHit[], incoming: SearchHit[]): { hits: SearchHit[]; added: number } {
  const seen = new Set(existing.map((h) => `${h.source}\u0000${h.url}`))
  const fresh: SearchHit[] = []
  for (const h of incoming) {
    const k = `${h.source}\u0000${h.url}`
    if (seen.has(k)) continue
    seen.add(k)
    fresh.push(h)
  }
  return { hits: [...existing, ...fresh], added: fresh.length }
}

/**
 * 「加载更多」还要不要留着？
 *
 * 两个条件缺一不可：后端说**可能还有**（`has_more`）**且**这一页真的带来了新条目。
 * 后半条是必要的兜底：规则源的 `{page}` 只表示「模板支持翻页」，站点不认这个参数时
 * 会不停回吐同一页 —— 那时按钮会永远点得动却永远没有新东西（一条典型的假交互）。
 */
export function keepLoadingMore(apiHasMore: boolean, added: number): boolean {
  return apiHasMore && added > 0
}

/**
 * 逐源状态按界面要的三态切开（顺序保持后端给的注册顺序）。
 *
 * 三态刻意分得比「成功 / 失败」细：**被跳过**（闸门）与**失败**（网络/解析）
 * 是两件不同的事，原因与用户该做什么都不同，合并成一类只会让人不知道该改哪。
 */
export function mergeSourceStates(prev: SearchSourceState[], next: SearchSourceState[]): SearchSourceState[] {
  const before = new Map(prev.map((s) => [s.name, s]))
  // 计数**累加**（失败原因 / 跳过原因 / has_more 以新页为准）：界面上「成功 N 条」
  // 说的是「列表里来自这个源的条数」；只留最后一页的数字，翻页后它反而会变小。
  const out = next.map((s) => ({ ...s, count: s.count + (before.get(s.name)?.count ?? 0) }))
  // 上一页有、这一页没回来的源（两次请求之间书源表变了）留着：
  // 让它的失败原因凭空消失，比多显示一行糟糕。
  const seen = new Set(next.map((s) => s.name))
  for (const s of prev) if (!seen.has(s.name)) out.push(s)
  return out
}

export function splitSources(sources: SearchSourceState[]): {
  ok: SearchSourceState[]
  failed: SearchSourceState[]
  skipped: SearchSourceState[]
} {
  const ok: SearchSourceState[] = []
  const failed: SearchSourceState[] = []
  const skipped: SearchSourceState[] = []
  for (const s of sources) {
    if (s.skipped) skipped.push(s)
    else if (s.ok) ok.push(s)
    else failed.push(s)
  }
  return { ok, failed, skipped }
}
