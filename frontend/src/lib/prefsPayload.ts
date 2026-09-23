import type { CoverPrefs } from '@/stores/coverPrefs'

import { COVER_PREFS_DEFAULT } from '@/stores/coverPrefs'
import { DISPLAY_PREFS_DEFAULT, type DisplayPrefs } from '@/stores/displayPrefs'
import { AUDIO_PREFS_DEFAULT, type AudioPrefs } from './audioPrefs'
import { COMIC_PREFS_DEFAULT, type ComicPrefs } from './comicPrefs'
import { PDF_PREFS_DEFAULT, type PdfPrefs } from './pdfPrefs'
import { READER_PREFS_DEFAULT, type ReaderPrefs } from './readerPrefs'
import { SHELF_PREFS_DEFAULT } from '@/stores/shelfPrefs'

/**
 * 偏好载荷：**七块**，与服务端 `PREFS_BLOCKS` 一一对应。
 *
 * ⚠️ 七块背后其实是 **9 个 localStorage 键**（`appearance` 一块 = 主题 / 点缀色 / 圆角
 * 三个独立键；`shelf` 一块 = 系列默认折叠，第 43 期并入）—— 按「模块」枚举会漏键，
 * 所以这里按块定义、在同步层里逐块读写。
 *
 * 归一化（`normalizePayload`）是 dirty 判定与推送的前提：把缺省字段补齐、
 * 丢掉未知键，保证「同一份配置」比较结果稳定（键序无关）。
 */

/**
 * 外观块：主题三件套 + 布局 / 显示（第 32 期并入）。
 *
 * 布局字段（`DisplayPrefs`）**平铺**在这里而不是嵌一层子对象 —— `normalizePayload`
 * 是浅合并，嵌套会在旧载荷缺该键时把整层默认值丢掉。平铺则天然向后兼容：
 * 老客户端推上来的外观块没有这几个键，`{...APPEARANCE_DEFAULT, ...old}` 会把它们补成默认值，
 * 且服务端只认块名（`PREFS_BLOCKS` 六块），故**零服务端改动**。
 *
 * ⚠️ 用 `extends` 而不是逐字段抄一遍：以后 `DisplayPrefs` 加字段会自动进入载荷，
 * 不会出现「store 加了、载荷漏了」的静默不同步。
 */
export interface AppearancePrefs extends DisplayPrefs {
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
  shelf: ShelfSyncPrefs
}

/**
 * 书架同步块：**只承载「随账号走」的那一项** —— 系列默认折叠（第 43 期）。
 *
 * 其余书架偏好（视图 / 排序 / 缩略图点击 / 筛选默认展开 / 书卡密度）仍**只存本机**：
 * 它们是「这台设备怎么看书架」，换设备本就该各是各的；只有「系列是否默认折叠」
 * 属于「我怎么看这个书库」，与上游 `series-collapse-prefs` 同口径。
 */
export interface ShelfSyncPrefs {
  collapseSeries: boolean
}

/** 与后端一致的块名白名单（第 9 期起含 audio；第 43 期加 shelf） */
export const PAYLOAD_BLOCKS = ['reader', 'pdf', 'comic', 'audio', 'appearance', 'cover', 'shelf'] as const

/**
 * 外观默认值：主题部分与 stores/theme.ts 的初值一致（system / neutral / default）；
 * 布局部分直接摊开 `DISPLAY_PREFS_DEFAULT`，避免两处默认值各写一遍后走样。
 */
export const APPEARANCE_DEFAULT: AppearancePrefs = {
  theme: 'system',
  accent: 'neutral',
  radius: 'default',
  ...DISPLAY_PREFS_DEFAULT,
}

/** 书架同步块默认值：与 `shelfPrefs` 的 `collapseSeries` 初值同源（缺省关闭） */
export const SHELF_SYNC_DEFAULT: ShelfSyncPrefs = {
  collapseSeries: SHELF_PREFS_DEFAULT.collapseSeries,
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
    shelf: { ...SHELF_SYNC_DEFAULT, ...(r.shelf || {}) },
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
