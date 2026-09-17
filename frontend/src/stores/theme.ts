import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { notifyPrefsChanged, suppressing } from '@/lib/prefsBridge'

/**
 * 主题状态。机制照搬 BookOrbit：<html> 上挂 class + localStorage 持久化。
 *
 *   class:       dark / accent-<name> / radius-<name>
 *   storage 键:  theme(默认 system) / accent(默认 neutral) / radius(默认 default)
 *
 * 首屏预置脚本（index.html 内联）与本 store 读写同一套键与 class，
 * 因此不会出现「刷新前后不一致」。
 */
export type ThemeMode = 'light' | 'dark' | 'system'
export type RadiusMode = 'default' | 'sharp' | 'rounded' | 'pill'

const THEME_ORDER: ThemeMode[] = ['light', 'dark', 'system']
export const THEME_LABEL: Record<ThemeMode, string> = {
  light: '浅色',
  dark: '深色',
  system: '跟随系统',
}

export const RADIUS_OPTIONS: Array<{ value: RadiusMode; label: string }> = [
  { value: 'default', label: '默认' },
  { value: 'sharp', label: '直角' },
  { value: 'rounded', label: '圆角' },
  { value: 'pill', label: '胶囊' },
]

function readStored<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    if (raw === null) return fallback
    try {
      return JSON.parse(raw) as T
    } catch {
      return raw as unknown as T
    }
  } catch {
    return fallback
  }
}

function writeStored(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    /* 隐私模式等场景下静默失败，与 v2 行为一致 */
  }
  // 主题 / 点缀色 / 圆角是**三个独立键**，但同属「外观」一块：任一变化都通知同步层
  notifyPrefsChanged()
}

/** 清掉 <html> 上某个前缀的 class */
function stripClassPrefix(prefix: string): void {
  const el = document.documentElement
  const hits: string[] = []
  for (const name of Array.from(el.classList)) {
    if (name.startsWith(prefix)) hits.push(name)
  }
  hits.forEach((name) => el.classList.remove(name))
}

export function prefersDark(): boolean {
  return typeof window.matchMedia === 'function' && window.matchMedia('(prefers-color-scheme: dark)').matches
}

export const useThemeStore = defineStore('theme', () => {
  const theme = ref<ThemeMode>(readStored<ThemeMode>('theme', 'system'))
  const accent = ref<string>(readStored<string>('accent', 'neutral'))
  const radius = ref<RadiusMode>(readStored<RadiusMode>('radius', 'default'))

  const isDark = computed(() => theme.value === 'dark' || (theme.value !== 'light' && prefersDark()))

  /** 把当前状态写进 <html> 的 class（不触碰 localStorage） */
  function applyClasses(): void {
    const el = document.documentElement
    el.classList.toggle('dark', isDark.value)

    stripClassPrefix('accent-')
    if (accent.value !== 'neutral') el.classList.add(`accent-${accent.value}`)

    stripClassPrefix('radius-')
    if (radius.value !== 'default') el.classList.add(`radius-${radius.value}`)
  }

  function setTheme(next: ThemeMode): void {
    theme.value = next
    writeStored('theme', next)
    applyClasses()
  }

  /** 三态轮换：浅色 → 深色 → 跟随系统 */
  function cycleTheme(): ThemeMode {
    const idx = THEME_ORDER.indexOf(theme.value)
    const next = THEME_ORDER[(idx + 1) % THEME_ORDER.length]
    setTheme(next)
    return next
  }

  /** 点缀色：单一入口，一次挂 class，由 accents.css 覆盖全部派生变量 */
  function setAccent(next: string): void {
    accent.value = next || 'neutral'
    writeStored('accent', accent.value)
    applyClasses()
  }

  function setRadius(next: RadiusMode): void {
    radius.value = next || 'default'
    writeStored('radius', radius.value)
    applyClasses()
  }

  /** 「跟随系统」时系统深浅切换要实时反映 */
  function watchSystem(): void {
    if (typeof window.matchMedia !== 'function') return
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    if (typeof mq.addEventListener !== 'function') return
    mq.addEventListener('change', () => {
      if (theme.value === 'system') applyClasses()
    })
  }

  /**
   * 应用远端（模式 / 设备）的外观值。
   * ⚠️ 仍必须经 `applyClasses()` 这一个入口挂 class —— 不要为了「快」直接改 DOM。
   * 写入期间抑制通知（否则会把刚拉下来的值又推回服务端）。
   */
  function applyRemote(next: Partial<{ theme: ThemeMode; accent: string; radius: RadiusMode }>): void {
    suppressing(() => {
      if (next.theme && THEME_ORDER.includes(next.theme)) {
        theme.value = next.theme
        writeStored('theme', next.theme)
      }
      if (typeof next.accent === 'string') {
        accent.value = next.accent || 'neutral'
        writeStored('accent', accent.value)
      }
      if (next.radius && RADIUS_OPTIONS.some((o) => o.value === next.radius)) {
        radius.value = next.radius
        writeStored('radius', radius.value)
      }
    })
    applyClasses()
  }

  return {
    theme,
    accent,
    radius,
    isDark,
    applyClasses,
    setTheme,
    cycleTheme,
    setAccent,
    setRadius,
    watchSystem,
    applyRemote,
  }
})
