import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

import { notifyPrefsChanged, suppressing } from '@/lib/prefsBridge'

/**
 * 封面样式偏好（对应上游 `外观 → Book Covers`）。
 *
 * 存 localStorage：本项目的「外观」类偏好都在前端（`stores/theme`、`lib/readerPrefs`），
 * 与上游的「本机 / 账号」二选一不同 —— 偏好同步是第 3 期的事（见 capability-gap §14）。
 *
 * 用 pinia store 而不是纯模块（对比 `lib/readerPrefs`）：封面出现在书架 / 系列 / 作者 /
 * 详情 / 仪表盘等**多个页面**，设置页改完要立即反映到所有地方，所以需要响应式来源。
 */

export type CoverDisplay = 'fill' | 'natural' | 'blurred'
export type CoverSpine = 'off' | 'subtle' | 'strong'
export type CoverShadow = 'off' | 'normal' | 'strong'
export type CoverOverlay = 'progress' | 'format' | 'stars' | 'status' | 'series'

export interface CoverPrefs {
  /** 封面填充方式：填满卡片 / 自然比例贴底 / 模糊底图居中 */
  display: CoverDisplay
  /** 书脊覆盖层 */
  spine: CoverSpine
  /** 阴影强度 */
  shadow: CoverShadow
  /** 卡片叠加层（勾选项） */
  overlays: CoverOverlay[]
}

const KEY = 'nf-cover-prefs'

/**
 * 默认值与「改造前的实际观感」一致：填满卡片、书脊 subtle、阴影 normal、无叠加层。
 * 刻意不默认打开叠加层 —— 书架本来就在封面下方显示进度条，默认再叠一个就成了重复信息。
 */
export const COVER_PREFS_DEFAULT: CoverPrefs = {
  display: 'fill',
  spine: 'subtle',
  shadow: 'normal',
  overlays: [],
}

export const COVER_DISPLAY_OPTIONS: { value: CoverDisplay; label: string; hint: string }[] = [
  { value: 'fill', label: '填满卡片', hint: '封面裁切后铺满整张卡片' },
  { value: 'natural', label: '自然比例贴底', hint: '保留封面原始比例，贴卡片底部，四周露出底色' },
  { value: 'blurred', label: '模糊底图', hint: '封面居中完整显示，四周用同一张图模糊填充' },
]

export const COVER_SPINE_OPTIONS: { value: CoverSpine; label: string }[] = [
  { value: 'off', label: '关闭' },
  { value: 'subtle', label: '轻微' },
  { value: 'strong', label: '明显' },
]

export const COVER_SHADOW_OPTIONS: { value: CoverShadow; label: string }[] = [
  { value: 'off', label: '关闭' },
  { value: 'normal', label: '默认' },
  { value: 'strong', label: '加强' },
]

export const COVER_OVERLAY_OPTIONS: { value: CoverOverlay; label: string; hint: string }[] = [
  { value: 'progress', label: '阅读进度', hint: '封面底部显示进度条' },
  { value: 'format', label: '格式', hint: '右上角显示 EPUB / MOBI 等' },
  { value: 'stars', label: '评分', hint: '左上角显示星级（0 星不显示）' },
  { value: 'status', label: '阅读状态', hint: '未读 / 在读 / 已读完' },
  { value: 'series', label: '系列名', hint: '封面顶部显示所属系列' },
]

function read(): CoverPrefs {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return { ...COVER_PREFS_DEFAULT }
    const p = JSON.parse(raw) as Partial<CoverPrefs>
    return {
      display: COVER_DISPLAY_OPTIONS.some((o) => o.value === p.display)
        ? (p.display as CoverDisplay)
        : COVER_PREFS_DEFAULT.display,
      spine: COVER_SPINE_OPTIONS.some((o) => o.value === p.spine)
        ? (p.spine as CoverSpine)
        : COVER_PREFS_DEFAULT.spine,
      shadow: COVER_SHADOW_OPTIONS.some((o) => o.value === p.shadow)
        ? (p.shadow as CoverShadow)
        : COVER_PREFS_DEFAULT.shadow,
      // 叠加层：过滤掉未知值，避免旧版本遗留的键渲染出空 div
      overlays: Array.isArray(p.overlays)
        ? p.overlays.filter((o) => COVER_OVERLAY_OPTIONS.some((x) => x.value === o))
        : [],
    }
  } catch {
    return { ...COVER_PREFS_DEFAULT }
  }
}

export const useCoverPrefsStore = defineStore('coverPrefs', () => {
  const prefs = ref<CoverPrefs>(read())

  function save(): void {
    try {
      localStorage.setItem(KEY, JSON.stringify(prefs.value))
    } catch {
      /* 隐私模式下不可写：本次会话仍生效 */
    }
    notifyPrefsChanged()
  }

  function patch(p: Partial<CoverPrefs>): void {
    prefs.value = { ...prefs.value, ...p }
    save()
  }

  function toggleOverlay(o: CoverOverlay): void {
    const has = prefs.value.overlays.includes(o)
    patch({
      overlays: has ? prefs.value.overlays.filter((x) => x !== o) : [...prefs.value.overlays, o],
    })
  }

  function reset(): void {
    prefs.value = { ...COVER_PREFS_DEFAULT }
    save()
  }

  /** 应用远端（模式 / 设备）值：写 ref + 落盘，但**抑制通知**，避免把刚拉下来的值又推回去 */
  function applyRemote(next: Partial<CoverPrefs>): void {
    suppressing(() => {
      prefs.value = { ...prefs.value, ...next }
      save()
    })
  }

  // 兜底：本 store 直接暴露了 `prefs` ref，`prefs.prefs.x = v` 这种写法不经过 patch。
  // 这里的 watcher 保证它仍然落盘并通知同步层（对比三个阅读器模块自带的 deep watch）。
  watch(prefs, () => suppressing(() => save()), { deep: true })

  return { prefs, patch, toggleOverlay, reset, applyRemote }
})
