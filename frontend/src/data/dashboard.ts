/**
 * 仪表盘部件与书架的**稳定标识与元信息**。
 *
 * 这里的 id 一经发布不可改名 —— 它们同时是 localStorage 持久化的键。
 * 部件组件与自定义面板都从本文件取 id 与文案，避免两处各写一份。
 * （组件的实际挂载在 components/dashboard/widgets/registry.ts，
 *   本轮 12 个全登记、其中 3 个已实现。）
 */

export type WidgetId =
  | 'library-overview'
  | 'currently-reading'
  | 'reading-streak'
  | 'reading-goal'
  | 'reading-rhythm'
  | 'reading-dna'
  | 'monthly-challenge'
  | 'highlight-of-the-day'
  | 'neglected-gems'
  | 'diversity-score'
  | 'year-projection'
  | 'long-wait'

export type WidgetSize = 'sm' | 'md' | 'lg'

export interface WidgetMeta {
  id: WidgetId
  title: string
  description: string
  /** 决定在部件行中占几列 */
  size: WidgetSize
}

/**
 * 12 个部件全登记，且**均已实现**（见 widgets/registry.ts，数据来自 /api/stats 等）。
 *
 * 标题按 NovelForge 的业务语义落定：「阅读节奏」类部件对应「入库节奏」，
 * 其余沿用 BookOrbit 原名；需要的数据（进度 / 批注 / 会话 / 入库）均已持久化。
 */
export const WIDGET_META: WidgetMeta[] = [
  { id: 'library-overview', title: '书库概览', description: '书籍、作者、系列与占用的一行数字', size: 'lg' },
  { id: 'reading-goal', title: '年度目标', description: '环形进度显示年度入库目标完成度', size: 'md' },
  { id: 'reading-rhythm', title: '入库节奏', description: '最近 28 天每日入库数量柱状图', size: 'md' },
  { id: 'currently-reading', title: '正在阅读', description: '已打开的书，按最近阅读时间排序', size: 'md' },
  { id: 'reading-streak', title: '连续天数', description: '当前连续记录天数与最近 7 天点阵', size: 'sm' },
  { id: 'reading-dna', title: '阅读基因', description: '长度、多样性、节奏、时段四项刻画', size: 'md' },
  { id: 'monthly-challenge', title: '月度挑战', description: '当月挑战进度', size: 'sm' },
  { id: 'highlight-of-the-day', title: '每日划线', description: '随机抽取的一条批注', size: 'md' },
  { id: 'neglected-gems', title: '被遗忘的佳作', description: '已开始却久未触碰的一本书', size: 'sm' },
  { id: 'diversity-score', title: '多样性评分', description: '体裁、作者、年代、语言四维评分', size: 'md' },
  { id: 'year-projection', title: '年度预测', description: '按当前节奏推算年底累计量', size: 'sm' },
  { id: 'long-wait', title: '等待最久', description: '书库中未读时间最长的一本书', size: 'sm' },
]

/**
 * 部件 → 所需能力（第 10 期「库类型 → 全量显隐」）。
 * 不声明 = 通用部件。真值源在后端 `core/features.py`。
 */
export const WIDGET_FEATURE: Record<string, string> = {
  // 每日划线取自批注，而批注只对 EPUB 有效
  'highlight-of-the-day': 'annotations',
}

export const WIDGET_IDS: WidgetId[] = WIDGET_META.map((w) => w.id)

/** 已实现的部件（registry 会为这些 id 挂真实组件）—— 现在 12 个全部实现 */
export const IMPLEMENTED_WIDGET_IDS: WidgetId[] = [...WIDGET_IDS]

/** 默认启用的部件：一屏信息量适中，其余可在自定义面板里打开 */
export const DEFAULT_WIDGET_IDS: WidgetId[] = [
  'library-overview',
  'currently-reading',
  'reading-goal',
  'reading-rhythm',
  'highlight-of-the-day',
]

/**
 * 书架行类型（对齐 BookOrbit 的四种）：
 *   continue 继续阅读 / recent 最近添加 / discover 随机发现 / scope 智能书架
 */
export type ShelfType = 'continue' | 'recent' | 'discover' | 'scope'

export interface ShelfDef {
  id: string
  type: ShelfType
  title: string
  /** 最多 6 行 */
  enabled: boolean
  /** type === 'scope' 时的智能书架键（recent/unread/reading/finished/annotated） */
  scope?: string
}

/** 可加为「智能书架行」的筛选（键与 stores/library.ts 的 SMART_KEYS 对应） */
export const SCOPE_OPTIONS: { key: string; label: string }[] = [
  { key: 'recent', label: '最近添加' },
  { key: 'unread', label: '未读' },
  { key: 'reading', label: '在读' },
  { key: 'finished', label: '已完成' },
  { key: 'annotated', label: '有批注' },
]

/** 最多 6 个书架行、最少保留 1 个 */
export const MAX_SHELVES = 6

export const DEFAULT_SHELVES: ShelfDef[] = [
  { id: 'shelf-continue', type: 'continue', title: '继续阅读', enabled: true },
  { id: 'shelf-recent', type: 'recent', title: '最近添加', enabled: true },
  { id: 'shelf-discover', type: 'discover', title: '发现新书', enabled: true },
]

export const SHELF_TYPE_LABEL: Record<ShelfType, string> = {
  continue: '继续阅读',
  recent: '最近添加',
  discover: '随机发现',
  scope: '智能书架',
}
