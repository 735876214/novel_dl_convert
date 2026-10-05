import { describe, expect, it } from 'vitest'

import { dashboardPageState, type DashboardPageInput } from '@/lib/dashboardPageState'

/**
 * 仪表盘**页级**三态的判据（第 98 期）。
 *
 * 这张表就是「什么叫页面级加载」的**完整定义**：它只吃真实请求状态，所以每条规则都要有
 * 正反两面 —— 既要证明该遮的时候遮，更要证明**不该遮的时候绝不遮**。后者才是这一期的重点：
 * 第 82 / 83 期拒绝做页级三态的理由恰恰是「硬造一个 page-level flag 会是假的」。
 */
function input(over: Partial<DashboardPageInput> = {}): DashboardPageInput {
  return {
    noLibraries: false,
    emptied: false,
    statsLoaded: false,
    statsError: '',
    booksLoading: true,
    booksError: '',
    ...over,
  }
}

describe('dashboardPageState', () => {
  it('两条请求都还没 settle 且书目在路上 ⇒ loading（唯一该显示页级骨架的窗口）', () => {
    expect(dashboardPageState(input())).toBe('loading')
  })

  it('统计一到手就不再遮（哪怕书目还在路上）—— 有真数据就不许盖住', () => {
    expect(dashboardPageState(input({ statsLoaded: true }))).toBe('ready')
  })

  it('统计失败但书目还在路上 ⇒ 只算区块级失败，不升级成整页错误', () => {
    expect(dashboardPageState(input({ statsError: '统计挂了' }))).toBe('ready')
  })

  it('两条都失败且什么都没拿到 ⇒ error（页级给一次「一起重试」）', () => {
    expect(
      dashboardPageState(input({ statsError: '统计挂了', booksError: '书库挂了', booksLoading: false })),
    ).toBe('error')
  })

  it('已经拿到过统计就不算整页错误（失败只出在后续刷新）', () => {
    expect(dashboardPageState(input({ statsLoaded: true, statsError: 'x', booksError: 'y' }))).toBe(
      'ready',
    )
  })

  it('0 个书库 ⇒ empty（让位给首屏引导；且空态优先于 loading / error）', () => {
    expect(dashboardPageState(input({ noLibraries: true }))).toBe('empty')
    expect(
      dashboardPageState(input({ noLibraries: true, statsError: 'x', booksError: 'y' })),
    ).toBe('empty')
  })

  it('部件与书架全关 ⇒ empty（让位给 DashboardWelcome）', () => {
    expect(dashboardPageState(input({ emptied: true }))).toBe('empty')
  })

  it('没有任何请求在路上时直接 ready —— 不许凭「刚进页面」就显示骨架', () => {
    expect(dashboardPageState(input({ booksLoading: false }))).toBe('ready')
  })
})
