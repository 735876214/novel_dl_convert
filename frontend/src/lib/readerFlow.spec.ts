import { describe, expect, it } from 'vitest'

import {
  canTrim,
  chunkGeomOf,
  computeWindow,
  localFractionIn,
  pickVisiblePos,
  scrollCompensation,
  type ChunkGeom,
} from '@/lib/readerFlow'

/** 造一个章块几何量：`[pos, top, height]` */
function g(pos: number, top: number, height: number): ChunkGeom {
  return { pos, top, height }
}

describe('readerFlow · computeWindow（滚动连续流的章块窗口）', () => {
  it('没有章节时返回空窗口（不是 [0]）', () => {
    expect(computeWindow(0, 0, true)).toEqual([])
    expect(computeWindow(0, -1, true)).toEqual([])
  })

  it('连续滚动开着：前后各给一章', () => {
    expect(computeWindow(5, 20, true)).toEqual([4, 5, 6])
  })

  it('连续滚动关着：只给「上一章 + 当前章」，不替用户往后看', () => {
    expect(computeWindow(5, 20, false)).toEqual([4, 5])
  })

  it('第一章：向前不越界', () => {
    expect(computeWindow(0, 20, true)).toEqual([0, 1])
    expect(computeWindow(0, 20, false)).toEqual([0])
  })

  it('最后一章：向后不越界（向后那一章不存在就别假装有）', () => {
    expect(computeWindow(19, 20, true)).toEqual([18, 19])
    expect(computeWindow(19, 20, false)).toEqual([18, 19])
  })

  it('只有一章：窗口就一项，不重复', () => {
    expect(computeWindow(0, 1, true)).toEqual([0])
    expect(computeWindow(0, 1, false)).toEqual([0])
  })

  it('越界或小数的 visible 先 clamp 再展开（滚动中间态可能算出小数）', () => {
    expect(computeWindow(-3, 10, true)).toEqual([0, 1])
    expect(computeWindow(99, 10, true)).toEqual([8, 9])
    expect(computeWindow(4.7, 10, true)).toEqual([3, 4, 5])
  })
})

describe('readerFlow · pickVisiblePos（可见章判定）', () => {
  const window3 = [g(4, 0, 1000), g(5, 1000, 1000), g(6, 2000, 1000)]

  it('停在第一块中部 ⇒ 第一块', () => {
    expect(pickVisiblePos(window3, 200, 600)).toBe(4)      // 基准线 200+300=500 < 1000
  })

  it('基准线正好压在下一块顶部 ⇒ 算换章（跨过即换）', () => {
    expect(pickVisiblePos(window3, 700, 600)).toBe(5)      // 基准线 700+300=1000 == 下一块 top
  })

  it('基准线落进第三块 ⇒ 第三块', () => {
    expect(pickVisiblePos(window3, 1800, 600)).toBe(6)     // 基准线 1800+300=2100 >= 2000
  })

  it('滚到最上面（基准线在第一块顶之上）⇒ 仍是第一块', () => {
    expect(pickVisiblePos(window3, 0, 600)).toBe(4)
  })

  it('视口高为 0（量不到布局）⇒ 退化成看顶部', () => {
    expect(pickVisiblePos(window3, 1001, 0)).toBe(5)
  })

  it('章块乱序也取「顶部不超过基准线的最后一个」（不依赖入参顺序）', () => {
    const shuffled = [g(5, 1000, 1000), g(4, 0, 1000)]
    expect(pickVisiblePos(shuffled, 700, 600)).toBe(5)
  })

  it('几何量全为 0（happy-dom 之类无布局环境）⇒ 保守停在第一块，绝不凭零值编位置', () => {
    const blind = [g(4, 0, 0), g(5, 0, 0), g(6, 0, 0)]
    expect(pickVisiblePos(blind, 99999, 600)).toBe(4)
  })

  it('空窗口 ⇒ 0（调用方据此不更新任何位置）', () => {
    expect(pickVisiblePos([], 0, 600)).toBe(0)
  })
})

describe('readerFlow · localFractionIn（章内阅读比例）', () => {
  const geom = g(5, 1000, 800)

  it('章块顶部 ⇒ 0；底部 ⇒ 1', () => {
    expect(localFractionIn(geom, 1000)).toBe(0)
    expect(localFractionIn(geom, 1800)).toBe(1)
  })

  it('章块中部 ⇒ 1/4（供进度条连续变化）', () => {
    expect(localFractionIn(geom, 1200)).toBeCloseTo(0.25, 6)
  })

  it('越出章块上下范围 ⇒ clamp 到 0 / 1（绝不出现负比例或 >100%）', () => {
    expect(localFractionIn(geom, 0)).toBe(0)
    expect(localFractionIn(geom, 99999)).toBe(1)
  })

  it('找不到章块或高度为 0 ⇒ 0', () => {
    expect(localFractionIn(undefined, 1200)).toBe(0)
    expect(localFractionIn(g(5, 1000, 0), 1200)).toBe(0)
  })
})

describe('readerFlow · scrollCompensation（前插/裁上方的补偿量）', () => {
  it('向上前插一章 ⇒ 正数（需把 scrollTop 加大，视觉位置才不动）', () => {
    expect(scrollCompensation(1200, 0)).toBe(1200)
  })

  it('裁掉上方一章 ⇒ 负数（需把 scrollTop 减回去）', () => {
    expect(scrollCompensation(0, 900)).toBe(-900)
  })

  it('上方既插又裁 ⇒ 取净额', () => {
    expect(scrollCompensation(1200, 900)).toBe(300)
  })

  it('下方增删不参与（追加下方天然不移动上方内容）', () => {
    expect(scrollCompensation(0, 0)).toBe(0)
  })
})

describe('readerFlow · canTrim（裁剪安全边界）', () => {
  // 视口 = [1000, 1600)，余量 1 屏 = 600 ⇒ 上界需 <= 1000-600=400，下界需 >= 1600+600=2200
  const view = { scrollTop: 1000, clientHeight: 600 }

  it('还在视口里 ⇒ 不可裁', () => {
    expect(canTrim(g(5, 1100, 400), view.scrollTop, view.clientHeight)).toBe(false)
  })

  it('刚离开视口但不足一屏余量 ⇒ 仍不可裁（惯性会甩出空白）', () => {
    expect(canTrim(g(4, 700, 200), view.scrollTop, view.clientHeight)).toBe(false)   // 底部 900 > 400
    expect(canTrim(g(6, 1700, 200), view.scrollTop, view.clientHeight)).toBe(false)  // 顶部 1700 < 2200
  })

  it('上方留足余量 ⇒ 可裁', () => {
    expect(canTrim(g(3, 0, 400), view.scrollTop, view.clientHeight)).toBe(true)
  })

  it('下方留足余量 ⇒ 可裁', () => {
    expect(canTrim(g(7, 2200, 400), view.scrollTop, view.clientHeight)).toBe(true)
  })

  it('恰好等于余量边界 ⇒ 可裁（>= 判定，不留一个「差 1 像素永远裁不掉」的死块）', () => {
    expect(canTrim(g(3, 0, 400), view.scrollTop, view.clientHeight)).toBe(true)
    expect(canTrim(g(7, 2200, 1), view.scrollTop, view.clientHeight)).toBe(true)
  })

  it('余量屏数可调（0 = 一离开视口就裁）', () => {
    expect(canTrim(g(4, 700, 200), view.scrollTop, view.clientHeight, 0)).toBe(true)
  })
})

describe('readerFlow · chunkGeomOf', () => {
  it('按章位置取几何量；找不到返回 undefined', () => {
    const list = [g(4, 0, 100), g(5, 100, 200)]
    expect(chunkGeomOf(list, 5)?.height).toBe(200)
    expect(chunkGeomOf(list, 9)).toBeUndefined()
  })
})
