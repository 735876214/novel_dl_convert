/**
 * 「自动翻到系列下一册」的唯一真值源（第 62 期）。
 *
 * 背景：漫画 / PDF / 有声书三处阅读器原本**各写一份**同样的逻辑
 * （`api.seriesDetail` → `sortBySeriesIndex` → 找当前书 → 取下一本 → `router.push`），
 * 于是「本 / 册」文案混用、有声书漏了「无系列」提示与单飞闸 —— 三份拷贝就是三个真相源。
 * 收敛到本文件后，三处只调 `useSeriesNext().goToNextVolume(...)`。
 *
 * ⚠️ 三处阅读器**不得**再各写文案或各拼 `seriesDetail + sortBySeriesIndex + findIndex`。
 */
import { useRouter } from 'vue-router'

import { api, type BookCard } from './api'
import { sortBySeriesIndex } from './bookInfo'
import { useUiStore } from '@/stores/ui'

/** 三处续接共用的提示文案（统一用「册」口径） */
export const SERIES_NEXT_MSG = {
  /** 这本没有 `series` 字段 —— 不跳，如实告知 */
  noSeries: '这本没有系列信息，无法自动翻下一册',
  /** 已经是系列最后一册（或当前书不在系列清单里）—— 不跳 */
  lastVolume: '已经是系列最后一册',
  /** 请求失败（网络 / 后端）—— 不跳，带上原因 */
  notFound: (message?: string) =>
    message ? `找不到系列下一册：${message}` : '找不到系列下一册',
} as const

/** 同类提示的节流窗口（ms）；与 `useUiStore().toast` 的 2s 生命周期对齐 */
export const SERIES_NEXT_HINT_MS = 2000

export type NextVolumeReason = 'ok' | 'no_series' | 'last' | 'error'

export interface NextVolumeResult {
  /** 命中的下一册；`reason !== 'ok'` 时恒为 null */
  next: BookCard | null
  reason: NextVolumeReason
  /** 仅 `reason === 'error'` 时带（原始错误信息） */
  message?: string
}

/**
 * 纯函数：解析系列里当前书的下一册。**异常在内部收敛为 `reason='error'`，绝不外抛**
 * （续接失败不得打断阅读）。
 *
 * `fetchSeries` 可注入 —— 契约测试据此完全离线验证，无需真联网。
 *
 * ⚠️ 当前书不在系列清单里（`findIndex < 0`）按既有三处实现的口径归为 `'last'`
 * （「已经是系列最后一册」），不新增第五种状态。
 */
export async function resolveNextVolume(
  series: string | undefined,
  bookId: string,
  fetchSeries: (name: string) => Promise<{ books: BookCard[] }> = api.seriesDetail,
): Promise<NextVolumeResult> {
  const name = (series || '').trim()
  if (!name) return { next: null, reason: 'no_series' }
  try {
    const d = await fetchSeries(name)
    const list = sortBySeriesIndex(d.books ?? [])
    const i = list.findIndex((b) => String(b.id) === String(bookId))
    const next = i >= 0 ? list[i + 1] ?? null : null
    return next ? { next, reason: 'ok' } : { next: null, reason: 'last' }
  } catch (e) {
    return { next: null, reason: 'error', message: e instanceof Error ? e.message : String(e) }
  }
}

// ---------------- 组合式：单飞闸 + 同类提示节流 ----------------
//
// 同一时刻只会挂载一处阅读器，故状态放模块级即可（不必逐组件持有）。

let hintKey = ''
let hintAt = 0
let inFlight = false

/** 仅供测试：清空模块级单飞闸与提示节流状态 */
export function resetSeriesNextState(): void {
  hintKey = ''
  hintAt = 0
  inFlight = false
}

export interface GoToNextVolumeOptions {
  /** 开关（漫画 `autoNext` / PDF `autoNext` / 有声书 `autoNextBook`）；为假**静默返回**、不弹提示 */
  enabled: boolean
  series?: string
  bookId: string
  /** 跳转路径前缀：电子书 / 漫画 `/read`，有声书 `/listen` */
  routeBase: '/read' | '/listen'
  /** 跳转前的落盘钩子（先落进度再跳，避免卸载时丢最后一段） */
  beforeJump?: () => void | Promise<void>
}

/**
 * 组合式：读到末页 / 末轨时调用。返回**是否已跳转**。
 *
 * 职责：`enabled` 门 → 解析下一册 → 按原因弹提示（同类节流）→ 命中则先 `beforeJump` 再跳转。
 * `enabled` 为假时立即返回 `false` 且**不弹任何提示**（保持「开关关着就原地不动、静默」的既有行为）。
 */
export function useSeriesNext(): {
  goToNextVolume: (opts: GoToNextVolumeOptions) => Promise<boolean>
} {
  const router = useRouter()
  const ui = useUiStore()

  /** 同类提示在窗口内只弹一次；跨因（key 不同）立即放行 */
  function hint(key: NextVolumeReason, message: string): void {
    const now = Date.now()
    if (key === hintKey && now - hintAt < SERIES_NEXT_HINT_MS) return
    hintKey = key
    hintAt = now
    ui.toast(message)
  }

  async function goToNextVolume(opts: GoToNextVolumeOptions): Promise<boolean> {
    if (!opts.enabled || inFlight) return false
    inFlight = true
    try {
      const r = await resolveNextVolume(opts.series, opts.bookId)
      if (r.reason === 'no_series') {
        hint('no_series', SERIES_NEXT_MSG.noSeries)
        return false
      }
      if (r.reason === 'last') {
        hint('last', SERIES_NEXT_MSG.lastVolume)
        return false
      }
      if (r.reason === 'error' || !r.next) {
        hint('error', SERIES_NEXT_MSG.notFound(r.message))
        return false
      }
      await opts.beforeJump?.()
      await router.push(`${opts.routeBase}/${r.next.id}`)
      return true
    } finally {
      inFlight = false
    }
  }

  return { goToNextVolume }
}
