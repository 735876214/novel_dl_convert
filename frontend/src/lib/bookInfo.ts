import type { BookCard } from '@/lib/api'

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

/** 格式徽章文本：`EPUB` */
export function formatLabel(b: BookCard): string {
  return (b.format || '').toUpperCase()
}

/**
 * 页数：`320≈`
 * 带上「≈」是因为它**是估算值**（EPUB 没有固定页数，见 core/library._pages_in）。
 * 不标估算就等于把估算当事实展示。
 */
export function pagesLabel(b: BookCard): string {
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

/** 阅读状态文案：**真实状态优先**；没有状态行（status 为 null）才按进度兜底推导 */
export function statusLabel(b: BookCard): string {
  if (b.status) {
    const map = { unread: '未读', reading: '在读', finished: '已读完', paused: '搁置', abandoned: '弃读' }
    return map[b.status] ?? ''
  }
  const p = b.percent ?? 0
  if (p >= 99.5) return '已读完'
  return p > 0 ? '在读' : '未读'
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
