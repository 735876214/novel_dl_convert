import { describe, expect, it } from 'vitest'

import { prefsSyncDecision } from '@/stores/prefSync'

/**
 * 第 56 期：远端变更判定的**纯函数**契约。
 *
 * 三条结果各自对应一种产品行为，都必须显式钉住：
 * - `noop`：什么都不做（含 1s 容差 —— 时间戳是秒级 float，本机回环不该误判成「别的设备」）；
 * - `apply-remote`：静默应用远端（沿用既有「服务端为准」策略）；
 * - `conflict`：**只提示不覆盖**（本机有未推送改动，选择权交给用户）。
 */
describe('prefsSyncDecision（第 56 期：远端变更判定）', () => {
  it('远端更旧或相同 ⇒ noop', () => {
    expect(prefsSyncDecision({ remoteSeen: 100, localSeen: 100, hasPending: false })).toBe('noop')
    expect(prefsSyncDecision({ remoteSeen: 90, localSeen: 100, hasPending: true })).toBe('noop')
  })

  it('1 秒容差内的「新」也算 noop（秒级 float 的回环）', () => {
    expect(prefsSyncDecision({ remoteSeen: 101, localSeen: 100, hasPending: false })).toBe('noop')
  })

  it('远端确实更新、本机无未推送改动 ⇒ 静默应用', () => {
    expect(prefsSyncDecision({ remoteSeen: 200, localSeen: 100, hasPending: false }))
      .toBe('apply-remote')
  })

  it('远端确实更新、但本机也有未推送改动 ⇒ 冲突（只提示不覆盖）', () => {
    expect(prefsSyncDecision({ remoteSeen: 200, localSeen: 100, hasPending: true }))
      .toBe('conflict')
  })

  it('没有远端基准（未登记 / 无记录）⇒ noop，不凭空判成冲突', () => {
    expect(prefsSyncDecision({ remoteSeen: 0, localSeen: 0, hasPending: true })).toBe('noop')
  })
})
