/**
 * 目录分组与段名的**唯一真值源**（第 85 期）。
 *
 * 阅读器左侧目录栏（`views/ReaderView.vue`）与详情页「目录」标签
 * （`components/book/detail/ChaptersTab.vue`）共用这一份规则 —— 两处各写一遍「无名段叫什么」
 * 必然漂移（此前就是：侧栏不显示段名、详情页把空段名回落成「目录」）。
 *
 * 后端（`core/reading_list.py`）给出的形状：`[{volume, kind?, chapters}]`
 *   · 卷段：`volume = "第一卷"`，无 `kind`；
 *   · 前后段：`volume = ""`，`kind = "front" | "back"`（楔子 / 序章 / 番外 / 后记…）；
 *   · 无名正文段：`volume = ""`，无 `kind`。
 * ⚠️ 前后段里的条目**没有 `num`**（不参与编号）。
 */
import type { BookChapter, BookVolume } from '@/lib/api'

/** 分组后的一项（`pos` 是它在阅读器 `flat` 序列里的位置 —— 点击只按位置跳） */
export interface TocItem {
  title: string
  pos: number
  /** 段内序号；**缺省 = 无编号条目**，界面不显示序号 */
  num?: number
}

/** 分组后的一个段 */
export interface TocGroup {
  /** 段名（见 `groupLabel`）——永远非空，两处目录都用它当标题 */
  label: string
  /** 卷名（空 = 无名段）。侧栏据此决定「出不出表头」 */
  volume: string
  kind?: 'front' | 'back'
  /** 侧栏是否渲染段头：**只有有名卷出**（无名段只在缩进上区别于卷内章节） */
  headered: boolean
  /** 折叠记忆用的稳定键（两处目录共用；段名可能重复，所以带上首项位置） */
  key: string
  items: TocItem[]
}

/**
 * 段名。
 *
 * 无名段（`volume` 为空）**不给假卷名**，由显示层统一叫法：
 * 卷前段 → 「卷前」、卷尾段 → 「卷尾」、其余 → 「正文」。
 */
export function groupLabel(v: Pick<BookVolume, 'volume' | 'kind'>): string {
  if (v.volume) return v.volume
  if (v.kind === 'front') return '卷前'
  if (v.kind === 'back') return '卷尾'
  return '正文'
}

/**
 * 把后端章节树摊成「段 → 条目」，并给每项带上它在 `flat` 里的位置。
 *
 * 口径与改造前逐字保持一致的两点（第 61 期定的，别顺手改）：
 * 1. `index === undefined` 的条目**跳过**（点不开的死项不渲染）；
 * 2. 空的无名段**不产出**（`items` 为空且没有卷名）。
 */
export function tocGroups(chapters: BookVolume[] | undefined): TocGroup[] {
  let k = 0
  const out: TocGroup[] = []
  for (const v of chapters ?? []) {
    const items: TocItem[] = []
    for (const c of v.chapters as BookChapter[]) {
      if (c.index === undefined) continue
      items.push({ title: c.title, pos: k, num: c.num })
      k += 1
    }
    if (!items.length && !v.volume) continue
    const label = groupLabel(v)
    out.push({
      label,
      volume: v.volume,
      kind: v.kind,
      headered: !!v.volume,
      key: `${label}#${items[0]?.pos ?? k}`,
      items,
    })
  }
  return out
}
