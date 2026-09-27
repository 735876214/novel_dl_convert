/**
 * 「这本书能不能在线打开、去哪儿」—— 全前端**唯一**的这段判据（第 64 期）。
 *
 * 抽出来的起因：书卡 ⋮ 菜单要放一项「阅读 / 收听」，而这件事此前**两处各判一遍**：
 * `ShelfView` 的 `READABLE_FORMATS` 与 `BookDetailView` 的 `canRead` / `canListen`。
 * 两份判据只要有一份走样，就会出现「详情页有「开始阅读」、书架菜单里没有」这种
 * 说不清的差异 —— 而且不报错，只是少一项 / 多一项。
 *
 * ⚠️ 抽出来**不等于**抹平：下面两个格式集合的差异是**历史事实**，不是笔误，
 *    见 `THUMBNAIL_READER_FORMATS` 的注释。本期只把它们放到同一处好对照。
 *
 * （`BookDetailView.canRead` 还有一条「EPUB / TXT 要有章节」的条件，那一半留在原处：
 *   章节数是**这本书**的属性、要等详情响应，不是格式的属性，塞不进一个纯函数。）
 */

/** 只收格式字符串：调用点常常拿不到整张卡（如 `ShelfView.openBook` 只有 id + format） */
type Formattable = { format?: string }

/** 有声书走播放器而不是阅读器（整本是一个目录 / 一个 m4b，阅读器打不开） */
export function isAudioBook(b: Formattable): boolean {
  return (b.format || '').toUpperCase() === 'AUDIO'
}

/**
 * 阅读器**能就地打开**的格式 —— 「点进去有东西看」的清单，不是「本项目支持的格式」清单。
 *
 * - EPUB / TXT：章节流（TXT 自第 55 期起走派生 EPUB 或原生分章，见后端 `txtcache`）
 * - PDF / CBZ / CBR：由各自阅读器就地处理
 *
 * MOBI / AZW3 之类**不在**其中：转换是另一条流水线的事，点开只会得到一句「点不了」。
 */
export const READER_FORMATS = new Set(['EPUB', 'PDF', 'CBZ', 'CBR', 'TXT'])

/**
 * 「浏览行为 → 缩略图点击」选「直接阅读」时认的格式。
 *
 * ⚠️ **刻意比 `READER_FORMATS` 少一个 TXT** —— 这不是漏了同步，是自第 32 期起的既有行为，
 * 本期不动（用户明确要求「封面行为一个字都不改」）。差别只体现在「点卡片先去哪儿」：
 * TXT 点卡片进详情页，但详情页里照样能读。菜单里的「阅读」按 `READER_FORMATS` 走。
 */
export const THUMBNAIL_READER_FORMATS = new Set(['EPUB', 'PDF', 'CBZ', 'CBR'])

export interface OpenTarget {
  /** 按钮文案：有声书是「收听」，其余是「阅读」 */
  label: '阅读' | '收听'
  /** 目标路由 */
  to: string
}

/**
 * 在线打开这本书的目标；**打不开的格式返回 `null`**（调用方据此整条不显示）。
 *
 * 返回 `null` 而不是回落到详情页：菜单里那一项写的是「阅读」，点了却进详情页
 * 是另一种假交互。要进详情页，菜单里本来就有「书籍详细信息」那一项。
 */
export function openTargetOf(b: { id: string } & Formattable): OpenTarget | null {
  if (isAudioBook(b)) return { label: '收听', to: `/listen/${b.id}` }
  if (READER_FORMATS.has((b.format || '').toUpperCase())) {
    return { label: '阅读', to: `/read/${b.id}` }
  }
  return null
}
