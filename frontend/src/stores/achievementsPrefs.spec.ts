import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { DISPLAY_CASE_MAX, useAchievementsPrefsStore } from '@/stores/achievementsPrefs'

/** 第 215 期：成就展示柜（最多 3 个 / 去重 / 远端归一化）。 */
describe('achievementsPrefs', () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
  })

  it('钉选去重、上限 3、可移出', () => {
    const s = useAchievementsPrefsStore()
    s.toggle('a')
    s.toggle('a')            // 再点一次 = 移出
    expect(s.has('a')).toBe(false)
    s.toggle('a'); s.toggle('b'); s.toggle('c'); s.toggle('d')
    expect(s.prefs.display_case).toEqual(['a', 'b', 'c'])
    expect(s.prefs.display_case.length).toBe(DISPLAY_CASE_MAX)
  })

  it('applyRemote 去重截断；exportSync 是拷贝', () => {
    const s = useAchievementsPrefsStore()
    s.applyRemote({ display_case: ['x', 'x', 'y', 'z', 'w'] })
    expect(s.prefs.display_case).toEqual(['x', 'y', 'z'])
    const snap = s.exportSync()
    snap.display_case.push('extra')
    expect(s.prefs.display_case).toEqual(['x', 'y', 'z'])
  })
})
