/**
 * 键盘事件的「落点」判据 —— 焦点是不是在一个**可编辑控件**里。
 *
 * ⚠️ 阅读器的翻页键（←/→、PageUp/PageDown）挂在 `window` / `document` 上，事件会从
 * 输入框**冒泡**上来。不看落点的话，用户在「PDF 文内搜索」「批注内容」「跳页」这些
 * 输入框里按方向键移动光标时，**书也会同时翻一页**（滑块 / 下拉还会被方向键改值，
 * 等于一次按键干了两件事）。
 *
 * 判据只有这一份：三处阅读器（EPUB / PDF / 漫画）共用。`contenteditable` 区域同样算
 * 「在编辑」，否则将来的富文本批注编辑器会踩同一个坑。
 */
export function isFormControlTarget(e: KeyboardEvent): boolean {
  const el = e.target as HTMLElement | null
  if (!el) return false
  const tag = String(el.tagName || '').toUpperCase()
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true
  return el.isContentEditable === true
}
