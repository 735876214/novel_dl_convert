/**
 * 从封面图取「色调」（详情页背景染色用，第 20 期）。
 *
 * 照搬来的 `cover-effects.css` 里 `.book-detail-cover-tint` 早就写好了，但一直没接线
 * （它是上游 CSS 的照搬件，此前全仓无任何 .vue 用它）—— 这里补上「取色」这一半。
 *
 * 三条约定：
 * 1. **失败一律返回 `null`**（图加载失败 / canvas 不可用 / 取不到有效像素）——
 *    调用方不设变量，CSS 那边 `hsl(var(--cover-tint-hue) …)` 整条失效 → 不染色，
 *    于是天然有回退，不会留下黑块或透明块。
 * 2. **同源**才取色：封面走本应用的 `/api/books/{id}/cover`，同源因此 canvas 不会被污染。
 * 3. 只取**两个色相**（上游的 Two colours 形态）：按色相分桶取最多的两桶，
 *    第二桶与第一桶太近就复用它（CSS 那边也会把 -2 继承为 -1）。
 */

export interface CoverTint {
  /** 主色相（0–359） */
  hue: number
  /** 主色饱和度（0–100） */
  saturation: number
  /** 次色相 */
  hue2: number
  saturation2: number
}

const SAMPLE = 16          // 采样到 16×16，够用且几乎无成本
const BUCKETS = 12         // 色相分桶（每桶 30°）

function rgbToHsl(r: number, g: number, b: number): [number, number, number] {
  const rr = r / 255
  const gg = g / 255
  const bb = b / 255
  const max = Math.max(rr, gg, bb)
  const min = Math.min(rr, gg, bb)
  const l = (max + min) / 2
  if (max === min) return [0, 0, l]
  const d = max - min
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min)
  let h: number
  if (max === rr) h = ((gg - bb) / d + (gg < bb ? 6 : 0)) * 60
  else if (max === gg) h = ((bb - rr) / d + 2) * 60
  else h = ((rr - gg) / d + 4) * 60
  return [h, s, l]
}

function sample(img: HTMLImageElement): CoverTint | null {
  try {
    const canvas = document.createElement('canvas')
    canvas.width = SAMPLE
    canvas.height = SAMPLE
    const ctx = canvas.getContext('2d')
    if (!ctx) return null
    ctx.drawImage(img, 0, 0, SAMPLE, SAMPLE)
    const { data } = ctx.getImageData(0, 0, SAMPLE, SAMPLE)

    const buckets = Array.from({ length: BUCKETS }, () => ({ h: 0, s: 0, n: 0 }))
    for (let i = 0; i < data.length; i += 4) {
      if (data[i + 3] < 128) continue                       // 半透明像素不参与
      const [h, s, l] = rgbToHsl(data[i], data[i + 1], data[i + 2])
      // 近黑 / 近白 / 灰（低饱和）都不是「封面的颜色」，是噪声
      if (l < 0.12 || l > 0.92 || s < 0.08) continue
      const bucket = buckets[Math.min(BUCKETS - 1, Math.floor(h / (360 / BUCKETS)))]
      bucket.h += h
      bucket.s += s
      bucket.n += 1
    }

    const ranked = buckets.filter((b) => b.n > 0).sort((a, b) => b.n - a.n)
    if (!ranked.length) return null
    const first = ranked[0]
    const hue1 = first.h / first.n
    const second = ranked.find((b) => Math.abs(b.h / b.n - hue1) > 24) ?? first
    const clamp = (v: number) => Math.max(0, Math.min(1, v))
    return {
      hue: Math.round(hue1),
      saturation: Math.round(clamp(first.s / first.n) * 100),
      hue2: Math.round(second.h / second.n),
      saturation2: Math.round(clamp(second.s / second.n) * 100),
    }
  } catch {
    return null                                             // 画布被污染等异常 → 不染色
  }
}

/**
 * 取色入口。`url` 为空、或超过 `timeoutMs` 仍未加载完 → 返回 `null`。
 * **不抛异常**：这是纯装饰，不该影响详情页渲染。
 */
export function extractCoverTint(url: string, timeoutMs = 6000): Promise<CoverTint | null> {
  return new Promise((resolve) => {
    if (!url || typeof document === 'undefined') {
      resolve(null)
      return
    }
    let settled = false
    const finish = (value: CoverTint | null) => {
      if (settled) return
      settled = true
      window.clearTimeout(timer)
      resolve(value)
    }
    const timer = window.setTimeout(() => finish(null), timeoutMs)
    const img = new Image()
    img.onload = () => finish(sample(img))
    img.onerror = () => finish(null)
    img.src = url
  })
}
