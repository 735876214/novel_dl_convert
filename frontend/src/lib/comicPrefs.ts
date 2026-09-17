/**
 * 漫画（CBZ）阅读偏好。
 *
 * 与 `readerPrefs`（eBook）/`pdfPrefs` 分开存：三类阅读器的设置项互不相干，
 * 混在一个键里会让「恢复默认」互相牵连。
 * 单一数据源：localStorage 的 `comic-prefs`（阅读器与设置页共读写）。
 */
import { notifyPrefsChanged } from './prefsBridge'

/** Paginated = 一页一屏（翻页）；Infinite = 纵向连续（无限滚动） */
export type ComicMode = 'paginated' | 'infinite'
/** Single = 单页；Double = 双页并排 */
export type ComicPageView = 'single' | 'double'
/** Page = 整页可见；Width = 适配宽度；Height = 适配高度；Actual = 原始尺寸 */
export type ComicFit = 'page' | 'width' | 'height' | 'actual'
/** 日漫常见右到左 */
export type ComicDirection = 'ltr' | 'rtl'

export interface ComicPrefs {
  mode: ComicMode
  pageView: ComicPageView
  fit: ComicFit
  direction: ComicDirection
  /** 双页并排时的页间距（px） */
  gap: number
  /** 阅读背景色（漫画常用纯黑或灰） */
  bg: 'black' | 'dark' | 'gray' | 'white'
}

export const COMIC_PREFS_KEY = 'comic-prefs'

export const COMIC_PREFS_DEFAULT: ComicPrefs = {
  mode: 'paginated',
  pageView: 'single',
  fit: 'page',
  direction: 'ltr',
  gap: 8,
  bg: 'dark',
}

export const COMIC_MODES = [
  { key: 'paginated', label: '翻页' },
  { key: 'infinite', label: '纵向连续' },
] as const

export const COMIC_PAGE_VIEWS = [
  { key: 'single', label: '单页' },
  { key: 'double', label: '双页' },
] as const

export const COMIC_FITS = [
  { key: 'page', label: '整页' },
  { key: 'width', label: '适配宽度' },
  { key: 'height', label: '适配高度' },
  { key: 'actual', label: '原始尺寸' },
] as const

export const COMIC_DIRECTIONS = [
  { key: 'ltr', label: '左 → 右' },
  { key: 'rtl', label: '右 → 左（日漫）' },
] as const

export const COMIC_BGS = [
  { key: 'black', label: '纯黑', css: '#000000' },
  { key: 'dark', label: '深灰', css: '#1a1a1a' },
  { key: 'gray', label: '中灰', css: '#4a4a4a' },
  { key: 'white', label: '白', css: '#ffffff' },
] as const

export const COMIC_RANGES = {
  gap: { min: 0, max: 40, step: 2, unit: 'px' },
} as const

export function comicBg(prefs: ComicPrefs): string {
  return COMIC_BGS.find((b) => b.key === prefs.bg)?.css ?? '#1a1a1a'
}

export function readComicPrefs(): ComicPrefs {
  try {
    const raw = localStorage.getItem(COMIC_PREFS_KEY)
    return raw
      ? { ...COMIC_PREFS_DEFAULT, ...(JSON.parse(raw) as Partial<ComicPrefs>) }
      : { ...COMIC_PREFS_DEFAULT }
  } catch {
    return { ...COMIC_PREFS_DEFAULT }
  }
}

export function saveComicPrefs(prefs: ComicPrefs): void {
  try {
    localStorage.setItem(COMIC_PREFS_KEY, JSON.stringify(prefs))
  } catch {
    /* 隐私模式等场景静默失败 */
  }
  notifyPrefsChanged()
}
