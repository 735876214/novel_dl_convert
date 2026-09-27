/**
 * 批注的**展示口径**（唯一一份）。
 *
 * 起因是「章节」这一栏：本应用自己写的批注知道章节**序号**，而设备回传的批注
 * （KOReader）只知道章节**标题** —— 上游给的是 `getTocTitleByPage` 的结果，不是下标。
 * 后端因此把序号记成 `-1`（未知），把标题原样存在 `chapter_title`。
 *
 * 两个调用方（批注总览页、详情页的批注 tab）此前各写各的 `第 {{ chapter + 1 }} 章`。
 * 那个写法对序号未知的批注会渲染出**「第 1 章」** —— 一条设备批注明明来自第十二章，
 * 界面上却写着第一章，而且没有任何地方能看出这是猜的。
 */

/** 章节那一栏该显示什么；返回空串表示「没有可显示的信息」（调用方就别渲染这一栏）。 */
export function chapterLabel(a: { chapter: number; chapter_title?: string }): string {
  // 序号已知：本应用自己的口径（后端存 0 基，界面显示 1 基）
  if (typeof a.chapter === 'number' && a.chapter >= 0) return `第 ${a.chapter + 1} 章`
  // 序号未知：只有设备给得出标题时才显示标题；连标题都没有就**什么都不显示**
  return (a.chapter_title || '').trim()
}

/**
 * 能不能跳到那条批注所在的位置。
 *
 * **序号未知就不能跳** —— 阅读器只认 `?chapter=<序号>`，拿 `-1` 去跳会落到章首，
 * 用户以为「点进去就到那条批注」，实际到的是第一章开头。宁可少给不可错给：
 * 不显示成链接，用户就不会以为它能点。
 */
export function canJumpTo(a: { chapter: number }): boolean {
  return typeof a.chapter === 'number' && a.chapter >= 0
}

/** 来源标识的中文名。未知来源原样返回（不编一个「其他」掩盖它）。 */
export const ORIGIN_LABELS: Record<string, string> = {
  web: '本应用阅读器',
  koreader: 'KOReader',
  kobo: 'Kobo',
}

export function originLabel(origin?: string): string {
  const k = (origin || '').trim()
  return ORIGIN_LABELS[k] || k
}
