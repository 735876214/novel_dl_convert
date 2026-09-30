import { onBeforeUnmount, onMounted, ref, type Ref } from 'vue'

/**
 * 书架行的「多行分带」纯函数（第 82 期对齐 BookOrbit 的 `lib/shelf-rows.ts`）。
 *
 * ⚠️ 刻意不引 `@vueuse/core`：上游用它做窄屏判定，本项目用 `window.matchMedia`
 * 自实现（见 `useNarrowScreen`），机制等价、零新增依赖（第 80 期口径）。
 */

export const MIN_SHELF_ROWS = 1
export const MAX_SHELF_ROWS = 3

/** 窄屏断点 = Tailwind 的 `sm`（640px），与全站栅格断点保持一致 */
const NARROW_QUERY = '(max-width: 639.98px)'

/**
 * 生效行数：宽屏按配置（1..3），窄屏最多压到 2 行
 * （BookOrbit 的 `effectiveShelfRows` 口径：窄屏放不下三行封面带）。
 */
export function effectiveShelfRows(rows: number, isNarrow: boolean): number {
  const clamped = Math.min(MAX_SHELF_ROWS, Math.max(MIN_SHELF_ROWS, rows))
  return isNarrow ? Math.min(2, clamped) : clamped
}

/** 把封面列表按行切成纵向堆叠的「带」；多行时同一列的封面底对齐 */
export function chunkIntoBands<T>(items: readonly T[], rows: number): T[][] {
  const r = Math.max(MIN_SHELF_ROWS, rows)
  if (r <= 1) return [[...items]]
  const bands: T[][] = []
  const perBand = Math.ceil(items.length / r)
  for (let i = 0; i < items.length; i += perBand) {
    bands.push(items.slice(i, i + perBand))
  }
  return bands.length ? bands : [[]]
}

/** 该书架要取的封面总数（每行上限 × 行数，夹到总量兜底） */
export function shelfBookLimit(perRow: number, rows: number, hardCap: number): number {
  return Math.min(hardCap, Math.max(1, perRow) * Math.max(MIN_SHELF_ROWS, rows))
}

/**
 * 窄屏判定（`matchMedia` 自实现，替代上游的 `useBreakpoints`）。
 * `matchMedia` 不可用的环境（极老内核 / 测试桩）按宽屏处理 —— 只影响行数，不影响可用性。
 */
export function useNarrowScreen(): Ref<boolean> {
  const narrow = ref(false)
  let mql: MediaQueryList | null = null
  let update: (() => void) | null = null

  onMounted(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return
    try {
      mql = window.matchMedia(NARROW_QUERY)
      update = () => {
        narrow.value = Boolean(mql?.matches)
      }
      update()
      mql.addEventListener('change', update)
    } catch {
      /* matchMedia 不可用：按宽屏处理 */
    }
  })

  onBeforeUnmount(() => {
    if (mql && update) {
      try {
        mql.removeEventListener('change', update)
      } catch {
        /* ignore */
      }
    }
    mql = null
    update = null
  })

  return narrow
}
