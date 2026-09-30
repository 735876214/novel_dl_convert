import { computed, type ComputedRef } from 'vue'

/**
 * 部件数据态的唯一真值源（第 82 期）。
 *
 * 12 件部件的数据源不同（`useStatsStore` / `useLibraryStore` / 批注接口），
 * 「加载中 / 失败 / 空」的判定若各写一份就是 12 份拷贝 —— 统一到这里。
 *
 * ⚠️ **只读各 store 的既有字段**（`loaded` / `error` / `loading` …），
 * 不引入假延迟、不造假数据 —— 项目铁律「不做假数据」。上游靠批量接口的统一 loading，
 * 本项目改为「逐部件读各自 store 的真实态」，这是机制等价、实现不同。
 */

export type WidgetState = 'loading' | 'error' | 'empty' | 'ready'

export interface WidgetStateInput {
  /** 数据正在加载（如 `!stats.loaded && !stats.error`、`!library.loaded`） */
  loading?: boolean
  /** 加载失败（如 `stats.error` 非空、批注拉取 catch） */
  error?: string | boolean
  /** 已加载且确实没有内容（如 `library.hasNoLibraries`、列表为空） */
  empty?: boolean
}

/** 判定优先级：loading > error > empty > ready（加载中先于失败先于空） */
export function widgetStateOf(input: WidgetStateInput): WidgetState {
  if (input.loading) return 'loading'
  if (input.error) return 'error'
  if (input.empty) return 'empty'
  return 'ready'
}

/**
 * 传入**返回输入对象的 getter**（保持响应性），返回响应式的数据态。
 * 例：`useWidgetState(() => ({ loading: !stats.loaded && !stats.error, error: stats.error }))`
 */
export function useWidgetState(input: () => WidgetStateInput): ComputedRef<WidgetState> {
  return computed(() => widgetStateOf(input()))
}
