import { READER_FONT_STACK } from './readerPrefs'

/**
 * 字体相关的**纯函数**（对应后端 `/api/fonts`）。
 *
 * 分层：这里不碰响应式状态，store（列表 + @font-face 注入）与 UI 都能用；
 * 偏好里的字体值形如 `serif` / `sans` / `system` / `custom:<字体文件名>`。
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

/** 偏好值 → CSS font-family 栈。自定义字体回落内置衬线，即使字体被删也不会变成默认无衬线 */
export function readerFontStack(font: string): string {
  if (font.startsWith(CUSTOM_FONT_PREFIX)) {
    const id = font.slice(CUSTOM_FONT_PREFIX.length)
    return `'${customFontFamily(id)}', ${READER_FONT_STACK.serif}`
  }
  return READER_FONT_STACK[font] ?? READER_FONT_STACK.serif
}
