import type { FontItem } from '@/lib/api'
import { READER_FONT_STACK } from './readerPrefs'

/**
 * 字体相关的**纯函数**（对应后端 `/api/fonts`）。
 *
 * 分层：这里不碰响应式状态，store（列表 + @font-face 注入）与 UI 都能用；
 * 偏好里的字体值形如 `serif` / `sans` / `system` / `custom:<族名或文件名>`。
 */

/** 自定义字体在偏好里的前缀 */
export const CUSTOM_FONT_PREFIX = 'custom:'

/** 自定义字体的 CSS family 名：加 NF- 前缀，避免与用户系统里同名族冲突 */
export function customFontFamily(id: string): string {
  return `NF-${id}`
}

/** 字体 id → 偏好值 */
export function customFontValue(id: string): string {
  return CUSTOM_FONT_PREFIX + id
}

/**
 * 字体 → 偏好值。
 * 同一族的多个变体（family_key 相同）归为一组，只存族名 —— 这样阅读器套用
 * 「加粗 / 斜体」时，浏览器能在同一 family 下挑中真实变体文件。
 * 解析不出族名（family_key 为空）时回落到旧口径 `custom:<文件名>`。
 */
export function fontPrefValue(f: FontItem): string {
  return f.family_key ? `${CUSTOM_FONT_PREFIX}${f.family_key}` : customFontValue(f.id)
}

/** 偏好值 → CSS font-family 栈。自定义字体回落内置衬线，即使字体被删也不会变成默认无衬线 */
export function readerFontStack(font: string): string {
  if (font.startsWith(CUSTOM_FONT_PREFIX)) {
    const id = font.slice(CUSTOM_FONT_PREFIX.length)
    return `'${customFontFamily(id)}', ${READER_FONT_STACK.serif}`
  }
  return READER_FONT_STACK[font] ?? READER_FONT_STACK.serif
}
