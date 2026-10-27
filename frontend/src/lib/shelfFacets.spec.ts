import { describe, expect, it } from 'vitest'

import { coverCounts, statusCounts, tallyTags, tallyText } from './shelfFacets'

/**
 * 第 156 期：书架筛选面板的**计数**。
 *
 * 计数口径必须与书架筛选同一套（格式大写、语言去空白、状态真实值优先），
 * 否则会出现「下拉写 12 本、筛出来 11 本」这种没人会去查的静默错误。
 */
describe('shelfFacets', () => {
  it('文本分面：去空、归一、计数并按值排序', () => {
    const opts = tallyText(['epub', ' EPUB ', '', undefined, 'PDF'], (v) => v.trim().toUpperCase())
    expect(opts).toEqual([
      { value: 'EPUB', count: 2 },
      { value: 'PDF', count: 1 },
    ])
  })

  it('题材是多值：每本书的每个标签各计一次', () => {
    const opts = tallyTags([{ tags: ['科幻', '经典'] }, { tags: ['科幻'] }, { tags: [] }])
    expect(opts).toEqual([
      { value: '经典', count: 1 },
      { value: '科幻', count: 2 },
    ])
  })

  it('封面两态计数', () => {
    expect(coverCounts([{ has_cover: true }, { has_cover: false }, { has_cover: true }]))
      .toEqual({ yes: 2, no: 1 })
  })

  it('状态计数：真实状态优先，没有状态行才按进度阈值兜底', () => {
    const counts = statusCounts([
      { status: 'finished', percent: 3 },   // 真实状态压过进度
      { status: 'paused', percent: 50 },    // paused 归「在读」桶（与筛选同口径）
      { status: null, percent: 100 },       // 阈值兜底 → 已读完
      { status: null, percent: 0 },         // → 未读
    ])
    expect(counts).toEqual({ unread: 1, reading: 1, finished: 2 })
  })
})
