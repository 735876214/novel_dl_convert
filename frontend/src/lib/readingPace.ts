/**
 * 阅读速度（页/小时）—— 单书与全站两处共用**一份**判据。
 *
 * 判据是「页数可不可信」而不是「有没有页数」：
 *
 * - EPUB 没有固定页数这个概念，`core/library._pages_in` 给的是**估算值**；
 * - 漫画（CBZ / CBR）的页数是归档里真实的图片张数；
 * - 其余格式（PDF / 有声书 / TXT）**恒为 0**，那个 0 是「不知道」不是「0 页」。
 *
 * 只有前两种能拿来算，且必须标出是哪一种 —— 「120 页/小时（估算页数）」与
 * 「45 页/小时（真实页数）」是两个可信度不同的结论，混成一个数字就是造假。
 * 算不出来时返回**空串**，调用方整块不渲染（而不是显示「0 页/小时」）。
 */

/** 页数来源 → 展示文案。表里没有的来源一律**不认**（见文件头） */
const PACE_SOURCES: Record<string, string> = {
  estimate: '估算页数',
  archive: '真实页数',
}

export interface PaceInput {
  /** 累计阅读秒数 */
  seconds: number
  /** 页数；0 = 不知道 */
  pages?: number
  /** 页数来源（`estimate` / `archive`）；空串 = 无可靠页数 */
  pages_source?: string
}

/**
 * 秒数 → 速度文案；**算不出来就是空串**。
 *
 * ⚠️ 分母用**累计时长**而不是「读这本书的天数」：那是本项目手头唯一的时长口径
 * （会话表）。它把「中途搁置的几个月」也算进去了 —— 所以这个数字该读作
 * 「这本书摊到每小时读了多少页」，而不是「我读得有多快」。文案里不解释这一层
 * （一句提示塞不下），但口径要在这里写清楚，免得后人拿它去当阅读能力的指标。
 */
export function paceText(b: PaceInput): string {
  const src = PACE_SOURCES[b.pages_source ?? '']
  if (!src) return ''
  if (!b.pages || b.pages <= 0) return ''
  const hours = (b.seconds || 0) / 3600
  if (hours <= 0) return ''
  return `${(b.pages / hours).toFixed(0)} 页/小时（${src}）`
}
