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

/**
 * 背景纹理档位（第 227 期）。
 *
 * ⚠️ **这份清单是唯一真值源**：设置页的下拉、`<html>` 上的 class（`texture-<key>`）
 * 与 `assets/theme/texture.css` 的规则**一一对应**。加一档 = 这里加一行 +
 * CSS 里写一条规则；少写规则就等于该档「选了没变化」。
 */
export const TEXTURE_OPTIONS: Array<{ value: string; label: string }> = [
  { value: 'none', label: '无' },
  { value: 'dots', label: '圆点' },
  { value: 'grid', label: '网格' },
  { value: 'diagonal', label: '斜纹' },
  { value: 'crosshatch', label: '交叉斜纹' },
  { value: 'noise', label: '噪点' },
  { value: 'paper', label: '纸纹' },
  { value: 'checker', label: '棋盘' },
  { value: 'rings', label: '同心圆' },
  { value: 'bars', label: '竖条' },
  { value: 'waves', label: '波浪' },
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
  /** 背景纹理（第 227 期）：`texture-<key>` class。默认 `none`（不改变现有观感）。 */
  const texture = ref<string>(readStored<string>('texture', 'none'))

  const isDark = computed(() => theme.value === 'dark' || (theme.value !== 'light' && prefersDark()))

  /** 把当前状态写进 <html> 的 class（不触碰 localStorage） */
  function applyClasses(): void {
    const el = document.documentElement
    el.classList.toggle('dark', isDark.value)

    stripClassPrefix('accent-')
    if (accent.value !== 'neutral') el.classList.add(`accent-${accent.value}`)

    stripClassPrefix('radius-')
    if (radius.value !== 'default') el.classList.add(`radius-${radius.value}`)

    // 第 227 期：背景纹理。**始终挂 class**（含 `none`）—— CSS 里 `texture-none`
    // 把强度归零；这样「切档」只需要换 class，不必记「上一个是什么」。
    stripClassPrefix('texture-')
    el.classList.add(`texture-${texture.value || 'none'}`)
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

  /** 背景纹理（第 227 期）。未知档位回落 `none`（不选一个 CSS 里没有的档）。 */
  function setTexture(next: string): void {
    const ok = TEXTURE_OPTIONS.some((o) => o.value === next)
    texture.value = ok ? next : 'none'
    writeStored('texture', texture.value)
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
  function applyRemote(next: Partial<{ theme: ThemeMode; accent: string; radius: RadiusMode; texture: string }>): void {
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
      if (typeof next.texture === 'string' && TEXTURE_OPTIONS.some((o) => o.value === next.texture)) {
        texture.value = next.texture
        writeStored('texture', texture.value)
      }
    })
    applyClasses()
  }

  return {
    theme,
    accent,
    radius,
    texture,
    isDark,
    applyClasses,
    setTheme,
    cycleTheme,
    setAccent,
    setRadius,
    setTexture,
    watchSystem,
    applyRemote,
  }
})
