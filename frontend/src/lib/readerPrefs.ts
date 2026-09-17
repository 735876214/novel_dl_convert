/**
 * 阅读器偏好（字体 / 字号 / 行高 / 内容宽度 / 主题 / 翻页模式 / 排版细节）。
 *
 * 单一数据源：localStorage 的 `reader-prefs`。阅读界面（ReaderView）与
 * 设置页（ReaderEbookPage）读写同一份，因此「设置里改的默认值」会直接生效。
 *
 * 兼容性：读回时与 DEFAULT 做 spread 合并，因此**老数据（只有 5 个字段）无需迁移**；
 * 主题键名 light/sepia/dark 刻意保留在 13 档集合里，老用户的选择不会失效。
 */
import { notifyPrefsChanged } from './prefsBridge'

/** 13 档主题：浅色 4 档 + 深色 9 档 */
export type ReaderThemeKey =
  | 'light' | 'paper' | 'sepia' | 'gray'
  | 'charcoal' | 'dark' | 'black' | 'midnight' | 'navy'
  | 'forest' | 'wine' | 'umber' | 'slate'

/** 滚动 = 纵向连续；翻页 = 定高分栏 + 横向翻页（分栏只在翻页下有意义） */
export type ReaderMode = 'scroll' | 'paged'

export interface ReaderPrefs {
  /** 内置 serif / sans / system，或 `custom:<字体 id>`（上传的字体，见 lib/fonts.ts） */
  font: string
  size: number
  lineHeight: number
  width: number
  theme: ReaderThemeKey
  /** 翻页 / 滚动 */
  mode: ReaderMode
  /** 段落间距（em） */
  paragraphSpacing: number
  /** 两端对齐 */
  justify: boolean
  /** 断词（中英混排下主要影响西文长词） */
  hyphens: boolean
  /** 字距（em） */
  letterSpacing: number
  /** 词距（em） */
  wordSpacing: number
  /** 首行缩进（em） */
  indent: number
  /** 分栏数（仅翻页模式生效：1 = 单栏，2 = 双栏） */
  columns: number
}

export const READER_PREFS_KEY = 'reader-prefs'

export const READER_PREFS_DEFAULT: ReaderPrefs = {
  font: 'serif',
  size: 18,
  lineHeight: 1.9,
  width: 42,
  theme: 'light',
  mode: 'scroll',
  paragraphSpacing: 1,
  justify: false,
  hyphens: false,
  letterSpacing: 0,
  wordSpacing: 0,
  indent: 2,
  columns: 1,
}

export const READER_FONTS = [
  { key: 'serif', label: '衬线' },
  { key: 'sans', label: '无衬线' },
  { key: 'system', label: '系统' },
] as const

export const READER_MODES = [
  { key: 'scroll', label: '滚动' },
  { key: 'paged', label: '翻页' },
] as const

/**
 * 13 档主题。底色/字色都写成字面量（不依赖应用主题变量），
 * 这样「应用浅色 + 阅读器深色」这类组合也能正常工作（上游同口径）。
 */
export const READER_THEMES: Array<{ key: ReaderThemeKey; label: string; bg: string; fg: string; dark: boolean }> = [
  { key: 'light', label: '浅色', bg: '#ffffff', fg: '#1c1d21', dark: false },
  { key: 'paper', label: '纸白', bg: '#fbfaf7', fg: '#2b2a27', dark: false },
  { key: 'sepia', label: '纸黄', bg: '#f6efdf', fg: '#3b3226', dark: false },
  { key: 'gray', label: '灰调', bg: '#e9ebee', fg: '#2c3035', dark: false },
  { key: 'charcoal', label: '炭灰', bg: '#2b2e33', fg: '#cfd3da', dark: true },
  { key: 'dark', label: '深色', bg: '#16181d', fg: '#d5d7dc', dark: true },
  { key: 'black', label: '纯黑', bg: '#000000', fg: '#b9bcc2', dark: true },
  { key: 'midnight', label: '午夜蓝', bg: '#101726', fg: '#c3cde0', dark: true },
  { key: 'navy', label: '藏青', bg: '#16202e', fg: '#ccd6e6', dark: true },
  { key: 'forest', label: '墨绿', bg: '#131e19', fg: '#c3d6c8', dark: true },
  { key: 'wine', label: '酒红', bg: '#1f1418', fg: '#ddc8cf', dark: true },
  { key: 'umber', label: '棕褐', bg: '#211a14', fg: '#dccdbb', dark: true },
  { key: 'slate', label: '石板', bg: '#1b1e24', fg: '#c8ccd4', dark: true },
]

export const READER_FONT_STACK: Record<string, string> = {
  serif: "var(--font-serif, Georgia, 'Songti SC', serif)",
  sans: "var(--font-sans, system-ui, -apple-system, 'PingFang SC', sans-serif)",
  system: "system-ui, -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif",
}

/** 主题键 → 底色/字色。未知键回落到浅色（老数据或手改 localStorage 时不至于白屏） */
export function readerThemeStyle(key: string): { bg: string; fg: string; dark: boolean } {
  return READER_THEMES.find((t) => t.key === key) ?? READER_THEMES[0]
}

/** 各滑杆的取值范围（设置页与阅读器共用，避免两处不一致） */
export const READER_RANGES = {
  size: { min: 14, max: 26, step: 1, unit: 'px' },
  lineHeight: { min: 1.4, max: 2.4, step: 0.1, unit: '' },
  width: { min: 30, max: 70, step: 2, unit: 'rem' },
  paragraphSpacing: { min: 0, max: 2, step: 0.1, unit: 'em' },
  letterSpacing: { min: 0, max: 0.15, step: 0.01, unit: 'em' },
  wordSpacing: { min: 0, max: 0.5, step: 0.05, unit: 'em' },
  indent: { min: 0, max: 3, step: 0.5, unit: 'em' },
  columns: { min: 1, max: 2, step: 1, unit: '栏' },
} as const

export function readReaderPrefs(): ReaderPrefs {
  try {
    const raw = localStorage.getItem(READER_PREFS_KEY)
    return raw
      ? { ...READER_PREFS_DEFAULT, ...(JSON.parse(raw) as Partial<ReaderPrefs>) }
      : { ...READER_PREFS_DEFAULT }
  } catch {
    return { ...READER_PREFS_DEFAULT }
  }
}

export function saveReaderPrefs(prefs: ReaderPrefs): void {
  try {
    localStorage.setItem(READER_PREFS_KEY, JSON.stringify(prefs))
  } catch {
    /* 隐私模式等场景静默失败 */
  }
  // 通知同步层落盘（见 lib/prefsBridge.ts）；应用远端值时会被抑制，不会回环
  notifyPrefsChanged()
}
