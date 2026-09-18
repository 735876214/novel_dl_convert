import type { CoverPrefs } from '@/stores/coverPrefs'

import { COVER_PREFS_DEFAULT } from '@/stores/coverPrefs'
import { AUDIO_PREFS_DEFAULT, type AudioPrefs } from './audioPrefs'
import { COMIC_PREFS_DEFAULT, type ComicPrefs } from './comicPrefs'
import { PDF_PREFS_DEFAULT, type PdfPrefs } from './pdfPrefs'
import { READER_PREFS_DEFAULT, type ReaderPrefs } from './readerPrefs'

/**
 * 偏好载荷：**六块**，与服务端 `PREFS_BLOCKS` 一一对应。
 *
 * ⚠️ 六块背后其实是 **8 个 localStorage 键**（`appearance` 一块 = 主题 / 点缀色 / 圆角
 * 三个独立键）—— 按「模块」枚举会漏键，所以这里按块定义、在同步层里逐块读写。
 *
 * 归一化（`normalizePayload`）是 dirty 判定与推送的前提：把缺省字段补齐、
 * 丢掉未知键，保证「同一份配置」比较结果稳定（键序无关）。
 */

export interface AppearancePrefs {
  theme: string
  accent: string
  radius: string
}

export interface PrefsPayload {
  reader: ReaderPrefs
  pdf: PdfPrefs
  comic: ComicPrefs
  audio: AudioPrefs
  appearance: AppearancePrefs
  cover: CoverPrefs
}

/** 与后端一致的块名白名单（第 9 期起含 audio） */
export const PAYLOAD_BLOCKS = ['reader', 'pdf', 'comic', 'audio', 'appearance', 'cover'] as const

/** 外观默认值：与 stores/theme.ts 的初值保持一致（system / neutral / default） */
export const APPEARANCE_DEFAULT: AppearancePrefs = {
  theme: 'system',
  accent: 'neutral',
  radius: 'default',
}

/** 补齐缺省字段、丢弃未知块，得到一份可用于比较与推送的完整载荷 */
export function normalizePayload(raw: Partial<PrefsPayload> | null | undefined): PrefsPayload {
  const r = (raw || {}) as Partial<PrefsPayload>
  return {
    reader: { ...READER_PREFS_DEFAULT, ...(r.reader || {}) },
    pdf: { ...PDF_PREFS_DEFAULT, ...(r.pdf || {}) },
    comic: { ...COMIC_PREFS_DEFAULT, ...(r.comic || {}) },
    audio: { ...AUDIO_PREFS_DEFAULT, ...(r.audio || {}) },
    appearance: { ...APPEARANCE_DEFAULT, ...(r.appearance || {}) },
    cover: { ...COVER_PREFS_DEFAULT, ...(r.cover || {}) },
  }
}

/** 深比较：对象按键名排序后逐字段比较，数组按序 —— 用于 dirty 判定 */
export function payloadEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true
  if (typeof a !== typeof b) return false
  if (Array.isArray(a) || Array.isArray(b)) {
    if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) return false
    return a.every((v, i) => payloadEqual(v, b[i]))
  }
  if (a && b && typeof a === 'object') {
    const ka = Object.keys(a as Record<string, unknown>).sort()
    const kb = Object.keys(b as Record<string, unknown>).sort()
    if (ka.length !== kb.length || ka.some((k, i) => k !== kb[i])) return false
    return ka.every((k) =>
      payloadEqual((a as Record<string, unknown>)[k], (b as Record<string, unknown>)[k]),
    )
  }
  return false
}
