import type { BookCard } from '@/lib/api'
import { statusLabelOf } from '@/lib/readingThresholds'

/**
 * 书卡上要展示哪几类信息 —— **单一来源**。
 *
 * 抽出来的原因：书架、系列详情、作者详情都要显示同一批信息，
 * 各自写一套必然走样（同一个字段在 A 页叫「2019 · 英语」、在 B 页叫「英语 2019」）。
 *
 * 对齐上游的 5 类：格式徽章 / 系列 #序号 / 出版日期·语言 / 题材 / 进度（进度不在这里，它是独立元素）。
 */

/** 系列内序号，形如 `#3`；空串表示没有序号 */
export function seriesIndexLabel(b: BookCard): string {
  return b.series_index ? `#${b.series_index}` : ''
}

/** 出版信息：`2019 · 英语`（缺项自动省略，不会留下孤零零的分隔符） */
export function pubLabel(b: BookCard): string {
  return [b.year, b.language].filter(Boolean).join(' · ')
}

/**
 * 格式徽章文本：`EPUB`。
 *
 * `UNITS` 是内部的**形态**标记（一个目录 = 一本书，见 core/units.py），不是文件格式 ——
 * 把 `UNITS` 原样印在徽章上对用户没有意义，所以给它一个中文标签。
 */
export function formatLabel(b: BookCard): string {
  const fmt = (b.format || '').toUpperCase()
  return fmt === 'UNITS' ? '合集' : fmt
}

/**
 * 页数：`320≈`
 * 带上「≈」是因为它**是估算值**（EPUB 没有固定页数，见 core/library._pages_in）。
 * 不标估算就等于把估算当事实展示。
 *
 * 有声书没有「页」的概念，改显示轨数（`12 轨`）——「0 页」是错误信息。
 * 序号单元合集同理显示话数（`12 话`）：一话对应磁盘上的一个文件，
 * 这个数是**实数**不是估算（`tracks` 就是话清单的长度，见 core/units.py）。
 */
export function pagesLabel(b: BookCard): string {
  const fmt = (b.format || '').toUpperCase()
  if (fmt === 'AUDIO' || fmt === 'UNITS') {
    const n = b.tracks ?? 0
    return n > 0 ? `${n} ${fmt === 'UNITS' ? '话' : '轨'}` : ''
  }
  if (!b.pages) return ''
  return b.pages_source === 'estimate' ? `${b.pages}≈` : String(b.pages)
}

/** 详细模式的元信息行：`EPUB · 2019 · 英语 · 320≈` */
export function metaOf(b: BookCard): string {
  return [formatLabel(b), pubLabel(b), pagesLabel(b)].filter(Boolean).join(' · ')
}

/** 题材（来自 EPUB 的 dc:subject）。默认最多 2 个，超出用 `+N` 收尾 */
export function tagsLabel(b: BookCard, max = 2): string {
  const tags = b.tags || []
  if (!tags.length) return ''
  if (tags.length <= max) return tags.join(' · ')
  return `${tags.slice(0, max).join(' · ')} +${tags.length - max}`
}

/**
 * 阅读状态文案：**真实状态优先**；没有状态行（status 为 null）才按进度兜底推导。
 *
 * ⚠️ 第 40 期起判定收敛到 `lib/readingThresholds.ts`（阈值可配，三份拷贝就是三个真相源）。
 * 本函数的「状态优先」语义**原样保留**，只是兜底那一半不再自己算。
 */
export function statusLabel(b: BookCard): string {
  return statusLabelOf(b)
}

/**
 * 按序号排序（系列页 / 同系列折叠时用）。
 *
 * 没有序号的书排在**最后**并按书名兜底，而不是当成序号 0 排到最前 ——
 * 「缺序号」不等于「第一册」，混在一起会让人误读阅读顺序。
 */
export function sortBySeriesIndex(list: BookCard[]): BookCard[] {
  return [...list].sort((a, b) => {
    const x = a.series_index ? Number(a.series_index) : NaN
    const y = b.series_index ? Number(b.series_index) : NaN
    const xOk = !Number.isNaN(x)
    const yOk = !Number.isNaN(y)
    if (xOk && yOk && x !== y) return x - y
    if (xOk !== yOk) return xOk ? -1 : 1
    return (a.title || a.name).localeCompare(b.title || b.name, 'zh')
  })
}
