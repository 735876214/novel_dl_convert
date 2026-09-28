/**
 * 滚动模式「跨章连续流」的纯逻辑（第 69 期）—— **唯一真值源**。
 *
 * 为什么单独一个模块：这里的每一件事都是纯计算，但每一条错了都会变成肉眼可见的毛病
 * （读着读着跳一屏 / 页码乱跳 / 惯性滚出空白），塞在组件里既难测也难讲清。
 * 组件只负责「量几何 → 落 DOM → 调这里」。
 *
 * ⚠️ 本模块**不做任何 DOM 操作**：`ChunkGeom` 由组件在 `nextTick` + `rAF` 里
 * 一次性量好再传进来（在滚动回调里反复 `getBoundingClientRect` 会强制同步布局）。
 */

/**
 * 窗口内单个章块的最小几何量。
 *
 * 坐标系是**滚动容器的内容坐标**（与 `scrollTop` 同一把尺子）：
 * `top` = 从内容顶部到章块顶部的距离，不是 `getBoundingClientRect().top`。
 * 组件换算方式：`rect.top - box.rect.top + box.scrollTop`（见 `ReaderView` 的 `measureChunks`）。
 */
export interface ChunkGeom {
  /** 该章在 `flat` 里的位置 */
  pos: number
  /** 距滚动容器**内容顶部**的偏移（与 `scrollTop` 同坐标系） */
  top: number
  /** 章块高度（含章标题与分隔留白） */
  height: number
}

/**
 * 可见章判定的基准线位置（相对视口高度的比例）。
 *
 * 取视口中线：章界处「下一章占到视口一半」才算换章 —— 既不早到（刚露头就报下一章），
 * 也不晚到（读了大半屏还在报上一章）。
 */
export const VISIBLE_ANCHOR = 0.5

/** 裁剪安全余量（屏数）：离开视口之外还要再留这么多，否则惯性滚动会甩出空白 */
export const TRIM_MARGIN_SCREENS = 1

function clamp01(v: number): number {
  return Math.min(1, Math.max(0, v))
}

/**
 * 由可见章推出「应当挂在容器里」的章位置列表（升序、已 clamp、已去重）。
 *
 * - `enabled = true`（连续滚动开着）：`[visible - 1, visible + 1]`
 * - `enabled = false`（关着）：`[visible - 1, visible]` —— **不向后（未来章）看**，
 *   于是「滚到底就停下」，由用户自己点「下一章」。
 *
 * ⚠️ 往前（历史章）**始终给一章**：向上滚能读回上一章是这个功能的一半，
 * 与开关无关；开关管的只是「要不要自动往后接」。
 */
export function computeWindow(visible: number, total: number, enabled: boolean): number[] {
  if (!Number.isFinite(total) || total <= 0) return []
  const v = Math.min(Math.max(0, Math.trunc(visible)), total - 1)
  const lo = Math.max(0, v - 1)
  const hi = Math.min(total - 1, v + (enabled ? 1 : 0))
  const out: number[] = []
  for (let p = lo; p <= hi; p += 1) out.push(p)
  return out
}

/**
 * 依据章块几何与滚动位置判定当前可见章（返回它在 `flat` 里的位置）。
 *
 * 取「顶部不超过基准线」的**最后一个**章块；`chunks` 允许乱序（内部不依赖顺序，只有 3 个块）。
 *
 * 几何量全为 0（`happy-dom` 等无布局环境）时**保守返回第一个章块** ——
 * 宁可不动，也不要凭零值算出一个假位置把进度写歪。
 */
export function pickVisiblePos(chunks: ChunkGeom[], scrollTop: number, clientHeight: number): number {
  const first = chunks[0]
  if (!first) return 0
  if (!chunks.some((c) => c.height > 0)) return first.pos
  const line = scrollTop + clientHeight * VISIBLE_ANCHOR
  let best = first.pos
  let bestTop = Number.NEGATIVE_INFINITY
  for (const c of chunks) {
    if (c.top <= line && c.top >= bestTop) {
      bestTop = c.top
      best = c.pos
    }
  }
  return best
}

/** 章内阅读比例（0–1）：`scrollTop` 落在该章块内的相对位置，越界即 clamp */
export function localFractionIn(geom: ChunkGeom | undefined, scrollTop: number): number {
  if (!geom || geom.height <= 0) return 0
  return clamp01((scrollTop - geom.top) / geom.height)
}

/**
 * 前插 / 裁上方之后的 `scrollTop` 补偿量。
 *
 * 向上**前插**会把已有内容整体推下 `insertedAboveHeight` ⇒ 必须同量加大 `scrollTop`，
 * 否则「滚到顶会往上跳一屏」；**裁掉上方**则相反，必须减回去。
 * 正数 = 需向下回补，负数 = 需向上回补。下方增删不影响上方内容，故不参与。
 */
export function scrollCompensation(insertedAboveHeight: number, removedAboveHeight: number): number {
  return insertedAboveHeight - removedAboveHeight
}

/**
 * 该章块是否**安全可裁**：完全离开视口，且在视口外**上下各留 >= `marginScreens` 屏**。
 *
 * 不满足就留着（内存多一点，但绝不会滚出空白 —— 空白是更糟的失败）。
 */
export function canTrim(
  geom: ChunkGeom,
  scrollTop: number,
  clientHeight: number,
  marginScreens: number = TRIM_MARGIN_SCREENS,
): boolean {
  const margin = Math.max(0, clientHeight) * marginScreens
  const viewTop = scrollTop
  const viewBottom = scrollTop + clientHeight
  const fullyAbove = geom.top + geom.height <= viewTop - margin
  const fullyBelow = geom.top >= viewBottom + margin
  return fullyAbove || fullyBelow
}

/** 取某个章块的几何量（找不到返回 `undefined`） */
export function chunkGeomOf(chunks: ChunkGeom[], pos: number): ChunkGeom | undefined {
  return chunks.find((c) => c.pos === pos)
}
