import { beforeEach, describe, expect, it, vi } from 'vitest'

import { offsetIn, rangeAt, selectionRange } from './textAnchor'

/**
 * 章内字符偏移锚的坐标定义（第 63 期 6/6）。
 *
 * 这个模块的危险之处不在「算不出来」，而在**悄悄算错**：偏移对不上时高亮照样画得出来，
 * 只是画在了邻近的文字上 —— 界面上看着像「差一点」，实则每条都错位，而且没有报错。
 * 所以用例的重心是**往返一致**（取偏移与还原区间必须共用一套坐标）与**越界不猜**。
 *
 * DOM 固定成下面这一个（字符数好数）：
 *
 * ```
 * <div>                     文本节点（章内偏移）
 *   <p>AAA<b>BBB</b>CCC</p>   AAA 0–3 · BBB 3–6 · CCC 6–9
 *   <p>DDD</p>                DDD 9–12
 * </div>
 * ```
 */
let root: HTMLElement
let p1: HTMLElement
let bold: HTMLElement
let p2: HTMLElement

beforeEach(() => {
  document.body.innerHTML = '<div id="r"><p>AAA<b>BBB</b>CCC</p><p>DDD</p></div>'
  root = document.getElementById('r')!
  p1 = root.querySelectorAll('p')[0]!
  bold = root.querySelector('b')!
  p2 = root.querySelectorAll('p')[1]!
})

/** 三个文本节点，按文档顺序 */
const t = () => ({
  aaa: p1.firstChild as Text,
  bbb: bold.firstChild as Text,
  ccc: bold.nextSibling as Text,
  ddd: p2.firstChild as Text,
})

describe('offsetIn：文本节点端点', () => {
  it('首尾相接：每个文本节点的起点是前面所有文字的长度之和', () => {
    expect(offsetIn(root, t().aaa, 0)).toBe(0)
    expect(offsetIn(root, t().bbb, 0)).toBe(3)
    expect(offsetIn(root, t().ccc, 0)).toBe(6)
    expect(offsetIn(root, t().ddd, 0)).toBe(9)
  })

  it('节点内偏移直接累加', () => {
    expect(offsetIn(root, t().aaa, 2)).toBe(2)
    expect(offsetIn(root, t().bbb, 1)).toBe(4)
    expect(offsetIn(root, t().ddd, 3)).toBe(12)
  })

  it('偏移超出节点长度时按节点长度截断（不越过边界去借下一个节点的字）', () => {
    expect(offsetIn(root, t().aaa, 99)).toBe(3)
  })

  it('节点不在 root 里 ⇒ -1（宁可判「没有锚」，也不给一个别的树的坐标）', () => {
    const outside = document.createElement('div')
    outside.textContent = 'ZZZ'
    document.body.appendChild(outside)
    expect(offsetIn(root, outside.firstChild!, 1)).toBe(-1)
  })
})

describe('offsetIn：元素端点（选区端点可以落在元素上）', () => {
  it('offset 0 ⇒ 该元素内容的**开头**', () => {
    expect(offsetIn(root, p1, 0)).toBe(0)
    expect(offsetIn(root, bold, 0)).toBe(3)
    expect(offsetIn(root, p2, 0)).toBe(9)
  })

  it('offset 非 0 ⇒ 该元素内容的**末尾**（浏览器只会产出 childNodes.length 这一种）', () => {
    expect(offsetIn(root, p1, p1.childNodes.length)).toBe(9)
    expect(offsetIn(root, bold, 1)).toBe(6)
  })

  it('元素端点一律**保守**：宁可少框住字，也不把边界外的文字算进来', () => {
    // p1 的内容是 0–9。它的两个端点各只贴住一边，中间的 `<b>` 不会被算到别处去
    expect(offsetIn(root, p1, 0)).toBeLessThanOrEqual(offsetIn(root, bold, 0))
    expect(offsetIn(root, p1, 5)).toBeLessThanOrEqual(9)
  })

  it('没有文字的元素 ⇒ 给章末（一个确定的坐标，而不是 -1）', () => {
    const empty = document.createElement('span')
    root.appendChild(empty)
    expect(offsetIn(root, empty, 0)).toBe(12)
  })
})

describe('rangeAt：偏移区间 → DOM Range', () => {
  it('区间落在一个文本节点内', () => {
    const hit = rangeAt(root, 3, 6)
    expect(hit?.text).toBe('BBB')
  })

  it('区间跨多个文本节点（也跨元素边界）时文字按文档顺序拼接', () => {
    expect(rangeAt(root, 1, 11)?.text).toBe('AABBBCCCDD')
    expect(rangeAt(root, 2, 7)?.text).toBe('ABBBC')
  })

  it('**末端越过整章 ⇒ null**（书变短了，这个偏移已经没有意义）', () => {
    // 整章 12 个字。13 是个合法下标数，但落到 DOM 上无解 —— 不许「截断到章末」
    // 画一段出来：那会把区间挪到一段用户没划过的文字上。
    expect(rangeAt(root, 9, 13)).toBeNull()
    expect(rangeAt(root, 0, 99)).toBeNull()
    expect(rangeAt(root, 12, 13)).toBeNull()
  })

  it('起点越界 / 空区间 / 倒置区间 ⇒ null', () => {
    expect(rangeAt(root, 12, 12)).toBeNull()   // 空区间
    expect(rangeAt(root, 5, 5)).toBeNull()
    expect(rangeAt(root, 8, 3)).toBeNull()     // 倒置
    expect(rangeAt(root, -1, 5)).toBeNull()
  })

  it('区间起点落在文本节点边界上时归属明确（不会漏掉第一个字）', () => {
    // 3 是 AAA 的末尾、也是 BBB 的起点。`start < acc + len` 让它归给**后**一个节点，
    // 于是取出来的是「从 BBB 起」而不是空区间。
    expect(rangeAt(root, 3, 5)?.text).toBe('BB')
  })
})

describe('两处调用必须共用同一套坐标（往返一致）', () => {
  it('offsetIn 取到的偏移，rangeAt 还原回同一个 (node, offset)', () => {
    const { bbb } = t()
    // 只到 `len - 1`：节点**末尾**那个偏移是另一回事，见下一条
    for (let off = 0; off < bbb.data.length; off++) {
      const abs = offsetIn(root, bbb, off)
      const hit = rangeAt(root, abs, abs + 1)
      expect(hit).not.toBeNull()
      expect(hit!.range.startContainer).toBe(bbb)
      expect(hit!.range.startOffset).toBe(off)
    }
  })

  it('节点末尾的偏移与下一个节点开头的偏移是**同一个位置**，只是两种写法', () => {
    // `offsetIn(root, bbb, 3)` = 6、`rangeAt(root, 6, …)` 给的是 ccc@0 —— 看起来「不一样」，
    // 其实指的是同一个字缝。`rangeAt` 一律归给**后**一个节点（`start < acc + len`），
    // 这样同一个绝对偏移只有一种 DOM 写法，不会出现「同样的区间画出两种高亮」。
    const { bbb, ccc } = t()
    expect(offsetIn(root, bbb, bbb.data.length)).toBe(offsetIn(root, ccc, 0))
    const hit = rangeAt(root, 6, 7)!
    expect(hit.range.startContainer).toBe(ccc)
    expect(hit.range.startOffset).toBe(0)
    expect(hit.text).toBe('C')
  })

  it('整章的每一个字符都能原样往返（错位会在这里露出来）', () => {
    const all = [t().aaa, t().bbb, t().ccc, t().ddd]
    const flat = all.map((n) => n.data).join('')
    for (let i = 0; i < flat.length; i++) {
      expect(rangeAt(root, i, i + 1)?.text).toBe(flat[i])
    }
  })

  it('选区往返：拖选一段文字，取出的偏移能还原出同一段文字', () => {
    const r = document.createRange()
    r.setStart(t().bbb, 1)
    r.setEnd(t().ccc, 2)
    const sel = window.getSelection()!
    sel.removeAllRanges()
    sel.addRange(r)

    const span = selectionRange(root)
    expect(span).toEqual({ start: 4, end: 8 })
    expect(rangeAt(root, span!.start, span!.end)?.text).toBe('BBCC')
  })
})

describe('selectionRange 的边界', () => {
  it('没有选区 / 折叠选区 ⇒ null（不返回一个 {start:0,end:0} 的假区间）', () => {
    window.getSelection()!.removeAllRanges()
    expect(selectionRange(root)).toBeNull()
  })

  it('选区**整段**落在 root 之外 ⇒ null（不拿别的 DOM 树的坐标去锚本章）', () => {
    const outside = document.createElement('div')
    outside.textContent = 'ZZZ'
    document.body.appendChild(outside)
    const r = document.createRange()
    r.setStart(outside.firstChild!, 0)
    r.setEnd(outside.firstChild!, 2)
    const sel = window.getSelection()!
    sel.removeAllRanges()
    sel.addRange(r)

    expect(selectionRange(root)).toBeNull()
  })

  it('**只有一半**在 root 里（从正文往外拖到页面空白）⇒ 也要 null', () => {
    // 上面那条证明不了「端点判 -1」这件事：两个端点都在外面时 a 和 b 都是 -1，
    // `a === b` 那条判据就足以返回 null，`a < 0 || b < 0` 看着像没生效。
    // 真正需要它的是**只越界一头**：此时 a 是个合法偏移、b 是 -1，
    // 少了这半条判断就会返回 `{start: -1, end: a}` —— 一个左右颠倒的区间，
    // 里面混着「不知道」的哨兵值 -1 冒充真实坐标。
    const outside = document.createElement('div')
    outside.textContent = 'ZZZ'
    document.body.appendChild(outside)
    const r = document.createRange()
    r.setStart(t().aaa, 1)
    r.setEnd(outside.firstChild!, 2)
    const sel = window.getSelection()!
    sel.removeAllRanges()
    sel.addRange(r)

    expect(offsetIn(root, t().aaa, 1)).toBe(1)          // 前一端是有效的
    expect(offsetIn(root, outside.firstChild!, 2)).toBe(-1) // 后一端不是
    expect(selectionRange(root)).toBeNull()
  })

  it('反向拖选（从后往前）取出的区间与正向一致', () => {
    // 浏览器把反向拖选也表述成一个有序的 `Range`（`startContainer` 恒在 `endContainer`
    // 之前），所以这里两种拖法本来就该给出同一个区间。
    const r = document.createRange()
    r.setStart(t().aaa, 1)
    r.setEnd(t().ccc, 2)
    const sel = window.getSelection()!
    sel.removeAllRanges()
    sel.addRange(r)
    expect(selectionRange(root)).toEqual({ start: 1, end: 8 })
  })

  it('起止**倒置**时仍然给出有序区间（真实 Range 不会这样，但这是函数的契约）', () => {
    // 上面那条证明不了「定序」这件事 —— 真实 `Range` 永远是有序的（DOM 的
    // `setStart`/`setEnd` 会自动把越界的那一头拉回来），`Math.min/Math.max` 因此是
    // **防御性**的，没有任何真实输入能让它生效。所以这里**手搓**一个倒置的假 Range
    // （`document.createRange()` 造不出来，规范会把它归一成折叠区间），
    // 把契约钉在函数边界上：不论给什么顺序，出来的必须是 `start <= end`。
    const reversed = {
      startContainer: t().ccc,
      startOffset: 2,
      endContainer: t().aaa,
      endOffset: 1,
    }
    vi.spyOn(window, 'getSelection').mockReturnValue({
      isCollapsed: false,
      rangeCount: 1,
      getRangeAt: () => reversed,
    } as unknown as Selection)
    expect(selectionRange(root)).toEqual({ start: 1, end: 8 })
  })
})
