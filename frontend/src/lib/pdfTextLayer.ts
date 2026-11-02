/**
 * PDF **文字层**与选区（第 222 期）。
 *
 * ## 为什么要有这一层
 *
 * PDF 的 canvas 只是**图像**：没有文字层就选不了字、搜不了词、也做不了批注。
 * pdf.js 的 `getTextContent()` 给出的文字项带**变换矩阵**，据此可以在 canvas 上
 * 叠一层透明的、绝对定位的文字层 —— 于是「看得见的字」与「可选择的字」落在同一处。
 *
 * ## 坐标口径（最容易错的一层）
 *
 * pdf.js 的文字项坐标是 **PDF 用户空间**（原点左下角、y 向上），而 DOM 是
 * **CSS 像素**（原点左上角、y 向下）。两者差一次「viewport 变换 + y 轴翻转」：
 *
 * ```
 * left = tx * scale
 * top  = viewportHeight - ty * scale - fontHeight
 * ```
 *
 * ⚠️ **必须用同一个 viewport 算**：渲染 canvas 用的是 `page.getViewport({scale})`，
 * 文字层也要用**同一个** viewport 对象（`transform` 相同）—— 否则缩放一改，
 * 文字层就跑偏（选中的字对不上位置）。
 *
 * ## 批注锚点
 *
 * 选区记的是**页码 + 该页内的字符偏移**（`start_off` / `end_off`），而不是像素坐标 ——
 * 像素随缩放 / 窗口大小变，字符偏移不会。页码本身用 `chapter` 字段承载
 * （PDF 的「章」= 页，与 EPUB 的 spine 序号是同一个字段、不同坐标系；这一点在
 * `docs/user-guide.md` 里如实标注）。
 */
/** pdf.js 的文字项（只取我们用到的字段，避免依赖 pdfjs 的类型）。 */
export interface PdfTextItem {
  str: string
  transform: number[]
  width: number
  height: number
  hasEOL?: boolean
}

export interface PdfTextItemWithFont extends PdfTextItem {
  fontName?: string
}

/** 文字层里的一段：一个文字项 + 它在页面上的位置（CSS 像素）。 */
export interface PdfTextSpan {
  /** 文字内容 */
  text: string
  /** 左上角 x（CSS 像素，相对页面） */
  left: number
  /** 左上角 y（CSS 像素，相对页面） */
  top: number
  /** 宽 / 高（CSS 像素） */
  width: number
  height: number
  /** 是否行尾（pdf.js 用它标段落） */
  eol: boolean
  /**
   * 横向拉伸系数（= 文字实际宽 / 该字号下的自然宽）。
   *
   * ⚠️ **必须带上**：PDF 的文字宽度由「字距 + 字号」决定，与字体本身的自然宽度
   * 无关（`width` 是 PDF 里写死的值）。不拉伸的话，选区的高亮框会与看到的字
   * **对不齐** —— 这正是 pdf.js 自己的文字层用 `scaleX` 的原因
   * （见 `pdfjs-dist/web/pdf_viewer.css` 的 `.textLayer` 规则）。
   */
  scaleX: number
}

/**
 * 两个仿射变换相乘（pdf.js 的 `Util.transform` 同样式）。
 *
 * 矩阵是 `[a, b, c, d, e, f]`：
 * ```
 * x' = a·x + c·y + e
 * y' = b·x + d·y + f
 * ```
 */
function mul(m1: number[], m2: number[]): number[] {
  return [
    m1[0] * m2[0] + m1[2] * m2[1],
    m1[1] * m2[0] + m1[3] * m2[1],
    m1[0] * m2[2] + m1[2] * m2[3],
    m1[1] * m2[2] + m1[3] * m2[3],
    m1[0] * m2[4] + m1[2] * m2[5] + m1[4],
    m1[1] * m2[4] + m1[3] * m2[5] + m1[5],
  ]
}

/**
 * 文字项 → 页面上的矩形（CSS 像素）。
 *
 * ⚠️ `viewport` 必须是**渲染 canvas 时用的那一个**（同 scale、同 transform）。
 *
 * 做法与 pdf.js 自己的 `Util.transform(viewport.transform, item.transform)` 一致 ——
 * **y 轴翻转已经包含在 viewport 的 transform 里**（pdf.js 给的是 `[s,0,0,-s,…]`），
 * 所以这里**不必**再翻一次（此前手工翻了一次，结果所有文字都跑到页面外面去了）。
 *
 * @param item  pdf.js 的文字项
 * @param viewport  `page.getViewport({scale})` 的结果
 */
export function spanRect(
  item: PdfTextItem,
  viewport: { width: number; height: number; transform: number[] },
): { left: number; top: number; width: number; height: number; scaleX: number } {
  const vp = viewport.transform
  const it = item.transform
  const t = mul(vp, it)
  // 缩放：viewport 的横向尺度
  const scale = Math.hypot(vp[0] ?? 1, vp[1] ?? 0) || 1
  // 文字高度（文字空间 → 设备像素）
  const height = Math.max(1, (item.height || 0) * scale)
  // `t[4] / t[5]` = 文字基线原点的设备坐标（y 向下：基线在字的下方）
  const left = t[4] ?? 0
  const top = (t[5] ?? 0) - height
  const width = Math.max(1, (item.width || 0) * scale)
  // 横向拉伸：PDF 里写死的字宽 ÷ 该字号下的自然宽。
  // 自然宽按「字号 × 0.5 × 字符数」估（西文平均字宽约 0.5em；中文约 1em，
  // 估得偏小 ⇒ scaleX 偏大，仍是**等比**拉伸，不会把字压变形）。
  const natural = Math.max(1, (item.height || 12) * 0.5 * Math.max(1, item.str?.length || 1))
  const scaleX = Math.max(0.05, Math.min(20, width / natural))
  return {
    left,
    top,
    width,
    height,
    scaleX,
  }
}

/**
 * 一页的文字项 → 文字层片段（按 `top` 排序，**同一行的合成一段**）。
 *
 * 合成同一行是必要的：pdf.js 常把一行拆成很多小项（每个词 / 每段 run 一项），
 * 逐项定位会让选区「跳格」，而浏览器对选区的判断需要**连续的文本节点**。
 *
 * @param items 该页的文字项
 * @param viewport 同上
 * @param lineTolerance 同一行的判定容差（CSS 像素）。字号越小越要小，
 *   取值 3 在常见字号下不会把相邻两行并成一行。
 */
export function buildTextLayer(
  items: PdfTextItem[],
  viewport: { width: number; height: number; transform: number[] },
  lineTolerance = 3,
): PdfTextSpan[] {
  const spans: PdfTextSpan[] = []
  for (const it of items || []) {
    if (!it || it.str === undefined || it.str === null) continue
    const r = spanRect(it, viewport)
    spans.push({
      text: it.str,
      left: r.left,
      top: r.top,
      width: r.width,
      height: r.height,
      eol: Boolean(it.hasEOL),
      scaleX: r.scaleX,
    })
  }
  spans.sort((a, b) => (Math.abs(a.top - b.top) > lineTolerance ? a.top - b.top : a.left - b.left))
  return spans
}

/** 片段 → 一行文本（同一行内的片段按 left 顺序拼）。 */
export function lineText(spans: PdfTextSpan[]): string {
  return spans.map((s) => s.text).join('')
}

/**
 * 页面文字 → 全文（**字符偏移的坐标系**）。
 *
 * ⚠️ 这里**不插换行**：字符偏移必须与浏览器 `Range.toString()` 的结果**逐字对齐**
 * （文字层 DOM 里就是这些片段首尾相接，中间没有换行符）—— 插了 `\n` 就会差一位，
 * 高亮整体错位。
 *
 * 换行只在**视觉**上由 CSS 的行盒决定，不进文字内容。
 */
export function pagePlainText(spans: PdfTextSpan[]): string {
  return spans.map((s) => s.text).join('')
}

/**
 * 一批批注 → 按页分组（每页一份，用于在文字层上重画高亮）。
 *
 * ⚠️ 坐标是**字符偏移**不是像素 —— 页面上的高亮盒要在**拿到文字层片段之后**
 * 按偏移换算（因为换算需要那一页的文字项）。
 */
export function annotationsByPage(
  annotations: { chapter: number; start_off?: number; end_off?: number }[],
): Record<number, { start_off: number; end_off: number }[]> {
  const out: Record<number, { start_off: number; end_off: number }[]> = {}
  for (const a of annotations) {
    const ch = Number(a.chapter)
    if (!Number.isFinite(ch) || ch < 0) continue
    const s = Number(a.start_off ?? -1)
    const e = Number(a.end_off ?? -1)
    if (s < 0 || e <= s) continue
    ;(out[ch] ||= []).push({ start_off: s, end_off: e })
  }
  return out
}
