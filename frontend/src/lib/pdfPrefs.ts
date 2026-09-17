/**
 * PDF 阅读偏好（滚动模式 / 页展 / 适配方式 / 缩放）。
 *
 * 与 `readerPrefs`（eBook）分开存：两类阅读器的设置项完全不相干，
 * 混在一个键里会让「恢复默认」之类的操作互相牵连。
 * 单一数据源：localStorage 的 `pdf-prefs`（阅读器与设置页共读写）。
 */
import { notifyPrefsChanged } from './prefsBridge'

/** Page = 一次一页（翻页）；Scrolled = 纵向连续；Horizontal = 横向连续 */
export type PdfScrollMode = 'page' | 'scrolled' | 'horizontal'
/** None = 单页；Odd = 奇页在右（1,3,5… 与后一页并排）；Even = 偶页在右；Auto = 按宽度自动 */
export type PdfSpread = 'none' | 'odd' | 'even' | 'auto'
export type PdfFit = 'page' | 'width' | 'auto' | 'custom'

export interface PdfPrefs {
  scrollMode: PdfScrollMode
  spread: PdfSpread
  fit: PdfFit
  /** 仅 fit = custom 时生效（0.5–3） */
  zoom: number
}

export const PDF_PREFS_KEY = 'pdf-prefs'

export const PDF_PREFS_DEFAULT: PdfPrefs = {
  scrollMode: 'page',
  spread: 'none',
  fit: 'width',
  zoom: 1,
}

export const PDF_SCROLL_MODES = [
  { key: 'page', label: '翻页' },
  { key: 'scrolled', label: '纵向滚动' },
  { key: 'horizontal', label: '横向滚动' },
] as const

export const PDF_SPREADS = [
  { key: 'none', label: '单页' },
  { key: 'odd', label: '双页（奇右）' },
  { key: 'even', label: '双页（偶右）' },
  { key: 'auto', label: '自动' },
] as const

export const PDF_FITS = [
  { key: 'page', label: '整页' },
  { key: 'width', label: '适配宽度' },
  { key: 'auto', label: '自动' },
  { key: 'custom', label: '自定义' },
] as const

export const PDF_RANGES = {
  zoom: { min: 0.5, max: 3, step: 0.25, unit: '×' },
} as const

export function readPdfPrefs(): PdfPrefs {
  try {
    const raw = localStorage.getItem(PDF_PREFS_KEY)
    return raw
      ? { ...PDF_PREFS_DEFAULT, ...(JSON.parse(raw) as Partial<PdfPrefs>) }
      : { ...PDF_PREFS_DEFAULT }
  } catch {
    return { ...PDF_PREFS_DEFAULT }
  }
}

export function savePdfPrefs(prefs: PdfPrefs): void {
  try {
    localStorage.setItem(PDF_PREFS_KEY, JSON.stringify(prefs))
  } catch {
    /* 隐私模式等场景静默失败 */
  }
  notifyPrefsChanged()
}
