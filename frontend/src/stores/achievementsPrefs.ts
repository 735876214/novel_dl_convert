import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

import { notifyPrefsChanged, suppressing } from '@/lib/prefsBridge'

/**
 * 成就展示柜（第 215 期）：用户挑最多 3 个**已解锁**成就钉在成就页顶部。
 *
 * 与阅读偏好同档：进偏好同步载荷的 `achievements` 块（换设备一致）；localStorage
 * 仍作首屏缓存。只存成就 key，不存进度 / 解锁时间（那些由后端实时算）。
 */
export interface AchievementsPrefs {
  display_case: string[]
}

const KEY = 'nf-achievements-prefs'
export const DISPLAY_CASE_MAX = 3

export const ACHIEVEMENTS_PREFS_DEFAULT: AchievementsPrefs = { display_case: [] }

function normalizeKeys(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  const out: string[] = []
  for (const v of value) {
    if (typeof v !== 'string') continue
    const k = v.trim()
    if (k && !out.includes(k)) out.push(k)
    if (out.length >= DISPLAY_CASE_MAX) break
  }
  return out
}

function read(): AchievementsPrefs {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return { ...ACHIEVEMENTS_PREFS_DEFAULT }
    const p = JSON.parse(raw) as Partial<AchievementsPrefs>
    return { display_case: normalizeKeys(p.display_case) }
  } catch {
    return { ...ACHIEVEMENTS_PREFS_DEFAULT }
  }
}

export const useAchievementsPrefsStore = defineStore('achievementsPrefs', () => {
  const prefs = ref<AchievementsPrefs>(read())

  watch(prefs, (v) => {
    try {
      localStorage.setItem(KEY, JSON.stringify(v))
    } catch {
      /* 隐私模式 */
    }
    notifyPrefsChanged()
  }, { deep: true })

  function has(key: string): boolean {
    return prefs.value.display_case.includes(key)
  }

  function toggle(key: string): void {
    if (has(key)) {
      prefs.value = { ...prefs.value, display_case: prefs.value.display_case.filter((k) => k !== key) }
    } else if (prefs.value.display_case.length < DISPLAY_CASE_MAX) {
      prefs.value = { ...prefs.value, display_case: [...prefs.value.display_case, key] }
    }
  }

  function applyRemote(raw?: Partial<AchievementsPrefs> | null): void {
    if (!raw) return
    suppressing(() => {
      prefs.value = { display_case: normalizeKeys(raw.display_case) }
    })
  }

  function exportSync(): AchievementsPrefs {
    return { display_case: [...prefs.value.display_case] }
  }

  return { prefs, has, toggle, applyRemote, exportSync }
})
