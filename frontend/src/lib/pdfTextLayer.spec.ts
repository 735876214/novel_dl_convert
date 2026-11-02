import { describe, expect, it } from 'vitest'

import {
  annotationsByPage,
  buildTextLayer,
  pagePlainText,
  spanRect,
  type PdfTextItem,
} from '@/lib/pdfTextLayer'

/**
 * PDF 文字层的**坐标换算**（第 223 期）。
 *
 * 这一层最容易错：pdf.js 给的是 **PDF 用户空间**（原点左下、y 向上），
 * DOM 是 **CSS 像素**（原点左上、y 向下）—— 差一次 viewport 变换。
 * 换算错了的表现是「选中的字和看到的位置对不上」，而且**不报错**。
 *
 * ⚠️ **y 轴翻转已经在 viewport 的 transform 里**（pdf.js 给的是 `[s,0,0,-s,…]`），
 * 所以文字层**不必**再翻一次 —— 手工再翻一次会让所有文字跑到页面外面去。
 * 这里的 viewport 就按 pdf.js 的真实形状写（y 分量为负）。
 */

/**
 * 缩放 1 的 viewport —— **pdf.js 实测值**（不是手写的）。
 *
 * 取自一份真实 PDF（200×100 的页面，`BT /F1 12 Tf 10 80 Td (Hello PDF) Tj ET`）：
 * `page.getViewport({scale:1}).transform` = `[1,0,0,-1,0,100]`，同一页的文字项
 * `transform` = `[12,0,0,12,10,80]`、`width` = 54.672、`height` = 12。
 *
 * ⚠️ **y 分量取负**（`-1`）—— pdf.js 的 y 轴翻转**已经在 viewport 里**了，
 * 文字层**不必**再翻一次（手工再翻一次会让所有文字跑到页面外面去）。
 */
const VIEWPORT = { width: 200, height: 100, transform: [1, 0, 0, -1, 0, 100] }

/** pdf.js 的文字项形状：transform = [a,b,c,d,e,f]，其中 a/d 是字号、e/f 是基线位置。 */
function item(str: string, x: number, y: number, width = 10, height = 12): PdfTextItem {
  return { str, transform: [12, 0, 0, 12, x, y], width, height }
}

describe('pdfTextLayer', () => {
  it('spanRect：真实 pdf.js 数据 ⇒ 基线在 PDF 下方，DOM 里字的顶边在基线之上', () => {
    // 实测：viewport [1,0,0,-1,0,100] × item [12,0,0,12,10,80]
    //   ⇒ 设备坐标基线 (10, 20)（100 - 80），字的顶边 = 20 - 12 = 8
    const r = spanRect(item('Hello PDF', 10, 80, 54.672, 12), VIEWPORT)
    expect(r.left).toBeCloseTo(10, 5)
    expect(r.height).toBeCloseTo(12, 5)
    expect(r.top).toBeCloseTo(8, 5)
    expect(r.width).toBeCloseTo(54.672, 3)
  })

  it('spanRect：viewport 有位移时 x / y 都跟着走', () => {
    const vp = { width: 200, height: 100, transform: [1, 0, 0, -1, 5, 107] }
    const r = spanRect(item('A', 10, 80), vp)
    expect(r.left).toBeCloseTo(15, 5)     // 5 + 10
    expect(r.top).toBeCloseTo(107 - 80 - 12, 5)
  })

  it('spanRect：缩放 2 时宽 / 高 / 位置一起放大（viewport 变、item 不变）', () => {
    // 缩放只改 viewport —— 文字层必须用**渲染 canvas 时的那一个**
    const vp2 = { width: 400, height: 200, transform: [2, 0, 0, -2, 0, 200] }
    const r = spanRect(item('Hello PDF', 10, 80, 54.672, 12), vp2)
    expect(r.left).toBeCloseTo(20, 5)
    expect(r.height).toBeCloseTo(24, 5)
    expect(r.top).toBeCloseTo(200 - 160 - 24, 5)
    expect(r.width).toBeCloseTo(109.344, 2)
  })

  it('buildTextLayer：按 top / left 排序（同一行按 left）', () => {
    const spans = buildTextLayer([
      item('B', 30, 80),   // 上行（PDF 里 y 大 = 靠上）
      item('A', 10, 80),   // 上行，靠左
      item('C', 10, 40),   // 下行
    ], VIEWPORT)
    // 读序 = 从上到下、同一行从左到右
    expect(spans.map((s) => s.text)).toEqual(['A', 'B', 'C'])
  })

  it('pagePlainText：与浏览器 Range.toString() 逐字对齐（**不插换行**）', () => {
    const spans = buildTextLayer([
      item('Hello', 10, 80),
      item('World', 10, 40),
    ], VIEWPORT)
    // ⚠️ 插 `\n` 就会与 DOM 里的文字差一位 ⇒ 高亮整体错位
    expect(pagePlainText(spans)).toBe('HelloWorld')
  })

  it('空文字层不炸（扫描件 / 加密 PDF）', () => {
    expect(buildTextLayer([], VIEWPORT)).toEqual([])
    expect(pagePlainText([])).toBe('')
  })

  it('annotationsByPage：按页分组；没有偏移的（别处导入的）不画', () => {
    const byPage = annotationsByPage([
      { chapter: 0, start_off: 3, end_off: 10 },
      { chapter: 0, start_off: 20, end_off: 25 },
      { chapter: 2, start_off: 1, end_off: 5 },
      { chapter: 1, start_off: -1, end_off: 5 },   // 没有偏移 ⇒ 画不出来
      { chapter: -1, start_off: 1, end_off: 5 },   // 序号未知 ⇒ 画不出来
    ])
    expect(Object.keys(byPage).map(Number).sort((a, b) => a - b)).toEqual([0, 2])
    expect(byPage[0]).toHaveLength(2)
    expect(byPage[2]).toHaveLength(1)
  })
})
