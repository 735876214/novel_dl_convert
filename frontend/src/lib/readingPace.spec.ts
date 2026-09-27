import { describe, expect, it } from 'vitest'

import { paceText } from '@/lib/readingPace'

/**
 * 「阅读速度」是全站与详情页共用的**唯一**判据。它在两种情况下必须闭嘴：
 * 页数来源不可信、以及根本不知道页数 —— 前者若按 0 算会得出「0 页/小时」（假的），
 * 后者（PDF / 有声书，pages 恒 0）若照算会得出无穷大。
 */
describe('阅读速度 · 只在页数可信时给结论', () => {
  it('EPUB 估算页数：算出速度并标明来源', () => {
    // 300 页读了 5 小时 ⇒ 60 页/小时
    expect(paceText({ seconds: 5 * 3600, pages: 300, pages_source: 'estimate' }))
      .toBe('60 页/小时（估算页数）')
  })

  it('漫画归档真实页数：来源文案与估算不同', () => {
    // 120 页读了 2 小时 ⇒ 60 页/小时
    expect(paceText({ seconds: 2 * 3600, pages: 120, pages_source: 'archive' }))
      .toBe('60 页/小时（真实页数）')
  })

  it('页数为 0（PDF / 有声书「不知道」）→ 空串，不是无穷大', () => {
    expect(paceText({ seconds: 3600, pages: 0, pages_source: 'estimate' })).toBe('')
    expect(paceText({ seconds: 3600, pages_source: 'archive' })).toBe('')
  })

  it('页数来源不认（含空串 / 未知格式）→ 空串，不按 0 算', () => {
    expect(paceText({ seconds: 3600, pages: 300 })).toBe('')
    expect(paceText({ seconds: 3600, pages: 300, pages_source: '' })).toBe('')
    expect(paceText({ seconds: 3600, pages: 300, pages_source: 'unknown' })).toBe('')
    expect(paceText({ seconds: 3600, pages: 300, pages_source: 'pdf' })).toBe('')
  })

  it('没读过（时长为 0）→ 空串，不显示「0 页/小时」', () => {
    expect(paceText({ seconds: 0, pages: 300, pages_source: 'estimate' })).toBe('')
  })

  it('秒数与页数都缺省 → 空串（不抛错）', () => {
    expect(paceText({ seconds: 0 })).toBe('')
  })
})
