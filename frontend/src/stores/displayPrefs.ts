import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

import { notifyPrefsChanged, suppressing } from '@/lib/prefsBridge'

/**
 * 显示 / 布局偏好（对应上游 `外观 → Layout`）。
 *
 * ⚠️ 与 `shelfPrefs` / `coverPrefs` 的关键差别：**这一份进偏好同步载荷**。
 * 上游该页分 4 组 13 项，本项目落地时做了两处收窄，都在下面写明：
 *
 * 1. **无方形封面**。上游 `squareCoverSize` / `squareGridGap` 管的是「方形缩略图」
 *    （列表 / 表格视图用），本项目三种视图一律是竖版 3:4 封面 ⇒ 这两项与
 *    `coverSizeScope`（「多个视图之间尺寸是否联动」，本项目只有一套网格）一并
 *    归入「上游有、本项目未支持」，不造假控件（见 LayoutPage 页尾对照卡）。
 * 2. **与 `shelfPrefs.cardInfo` 的分工**：那个（既有，存本机）管**显示多少**
 *    （紧凑 / 标准 / 详细），本 store 的 `cardInfoMode`（同步）管**放在哪**
 *    （悬停浮层 / 封面下方 / 不显示）。两者正交，故不合并。
 *
 * 落盘键 `nf-display-prefs`，并**并入 `appearance` 偏好块**同步（不新增第七块，
 * 免得牵动服务端 `PREFS_BLOCKS` 的六块契约）。
 */

/** 卡片信息放哪：悬停浮层 / 封面下方（改造前的行为）/ 不显示 */
export type CardInfoMode = 'hover-overlay' | 'below-cover' | 'off'
/** 作者封面形状。上游是 circle|square，本项目作者封面是竖版 3:4 ⇒ 对应为 竖版 / 圆形 */
export type AuthorCoverShape = 'portrait' | 'circle'
/**
 * 卡片主标签候选（第 51 期，对齐上游卡片信息可配）。
 * 默认 `title` = 改造前的行为；取不到值的书会回退到书名，不会渲染成空行。
 */
export type CardPrimaryLabel = 'title' | 'series' | 'series_index' | 'author' | 'none'
/** 卡片次标签候选（第 51 期）。默认 `author` = 改造前的行为 */
export type CardSecondaryLabel = 'author' | 'series' | 'series_index' | 'title' | 'none'
/**
 * 折叠系列行的封面形态（第 51 期，对齐上游 `Collapsed series cover`）。
 * `first` = 改造前的行为（取外层排序里首次出现的那本）。
 */
export type CollapsedCover = 'first' | 'latest' | 'first_unread' | 'stack' | 'mosaic'

export interface DisplayPrefs {
  /** 网格封面**最小宽度**（px）—— 网格按此自动排列表数，见 ShelfView 的 auto-fill 网格 */
  coverSize: number
  /** 网格横纵间距（px）。上游竖版/方版各一份，本项目只有竖版故合成一档 */
  gridGap: number
  /** 卡片信息位置 */
  cardInfoMode: CardInfoMode
  /** 卡片主标签（第 51 期；默认书名） */
  primaryLabel: CardPrimaryLabel
  /** 卡片次标签（第 51 期；默认作者） */
  secondaryLabel: CardSecondaryLabel
  /** 折叠系列行的封面形态（第 51 期；默认首册） */
  collapsedCover: CollapsedCover
  /** 作者页封面最小宽度（px） */
  authorCoverSize: number
  /** 作者页封面形状 */
  authorCoverShape: AuthorCoverShape
  /** 表格视图隔行底色 */
  zebraStriping: boolean
}

const KEY = 'nf-display-prefs'

/** 量程照搬上游（`AppearanceLayoutSettings.vue` 的 range 属性，三处都是 100-280/10） */
export const COVER_SIZE_RANGE = { min: 100, max: 280, step: 10 } as const
/** 上游 `portraitGridGap`：4-40 / step 4 */
export const GRID_GAP_RANGE = { min: 4, max: 40, step: 4 } as const
export const AUTHOR_COVER_SIZE_RANGE = { min: 100, max: 280, step: 10 } as const

/**
 * 默认值刻意取「这些设置出现之前的样子」，装完不惊动任何人：
 * - `coverSize: 140` / `gridGap: 16` —— 改造前是固定断点列数（`grid-cols-2 … 2xl:grid-cols-8`）
 *   配 `gap-x-4 gap-y-5`。改成按封面尺寸自适应后列数随容器宽连续浮动，这两个值按
 *   常见屏宽（1280 / 1440 下内容区约 950px）校准到与改造前同为 6 列、每列约 145px。
 *   纵向间距由 20 收到 16，肉眼不可辨。
 * - `cardInfoMode: 'below-cover'` / `zebraStriping: false` —— 改造前的行为，一字不差。
 * - `authorCoverSize: 170` —— 作者页改造前是 `xl:grid-cols-5`，比书架的 6 列宽一档；
 *   170 是在默认间距下仍排出 5 列的最大值（实测 180 会掉到 4 列）。
 */
export const DISPLAY_PREFS_DEFAULT: DisplayPrefs = {
  coverSize: 140,
  gridGap: 16,
  cardInfoMode: 'below-cover',
  // 第 51 期新增：默认「书名 + 作者」，与加这两项之前一字不差
  primaryLabel: 'title',
  secondaryLabel: 'author',
  // 折叠系列行默认取「首次出现的那本」= 改造前的行为
  collapsedCover: 'first',
  authorCoverSize: 170,
  authorCoverShape: 'portrait',
  zebraStriping: false,
}

export const CARD_INFO_MODE_OPTIONS: { value: CardInfoMode; label: string; hint: string }[] = [
  { value: 'hover-overlay', label: '悬停浮层', hint: '信息压在封面上，鼠标移上去才浮出来' },
  { value: 'below-cover', label: '封面下方', hint: '书名与作者排在封面下（默认）' },
  { value: 'off', label: '不显示', hint: '只画封面，信息进详情页看' },
]

export const AUTHOR_COVER_SHAPE_OPTIONS: { value: AuthorCoverShape; label: string; hint: string }[] =
  [
    { value: 'portrait', label: '竖版', hint: '3:4 圆角矩形（默认）' },
    { value: 'circle', label: '圆形', hint: '裁成 1:1 圆形头像' },
  ]

/** 卡片主标签候选（第 51 期）。`none` = 不显示主标签（卡片只剩封面） */
export const CARD_PRIMARY_LABEL_OPTIONS: {
  value: CardPrimaryLabel
  label: string
}[] = [
  { value: 'title', label: '书名' },
  { value: 'series', label: '系列名' },
  { value: 'series_index', label: '系列号' },
  { value: 'author', label: '作者' },
  { value: 'none', label: '不显示' },
]

/** 卡片次标签候选（第 51 期） */
export const CARD_SECONDARY_LABEL_OPTIONS: {
  value: CardSecondaryLabel
  label: string
}[] = [
  { value: 'author', label: '作者' },
  { value: 'series', label: '系列名' },
  { value: 'series_index', label: '系列号' },
  { value: 'title', label: '书名' },
  { value: 'none', label: '不显示' },
]

/** 折叠系列行的封面形态（第 51 期，对齐上游五档） */
export const COLLAPSED_COVER_OPTIONS: { value: CollapsedCover; label: string; hint: string }[] = [
  { value: 'first', label: '首册', hint: '用系列里首次出现的那本做封面（默认）' },
  { value: 'latest', label: '最新', hint: '用系列末册做封面' },
  { value: 'first_unread', label: '首册未读', hint: '用第一本没读完的做封面；都读完则回退首册' },
  { value: 'stack', label: '堆叠', hint: '前几册错位叠放（纯 CSS 位移）' },
  { value: 'mosaic', label: '马赛克', hint: '前 4 册 2×2 拼贴，不足则留空位' },
]

/** 取整并夹到量程内；非数字落回默认值 */
function readSize(v: unknown, fallback: number, r: { min: number; max: number }): number {
  if (typeof v !== 'number' || !Number.isFinite(v)) return fallback
  return Math.min(r.max, Math.max(r.min, Math.round(v)))
}

function read(): DisplayPrefs {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return { ...DISPLAY_PREFS_DEFAULT }
    const p = JSON.parse(raw) as Partial<DisplayPrefs>
    return {
      coverSize: readSize(p.coverSize, DISPLAY_PREFS_DEFAULT.coverSize, COVER_SIZE_RANGE),
      gridGap: readSize(p.gridGap, DISPLAY_PREFS_DEFAULT.gridGap, GRID_GAP_RANGE),
      cardInfoMode: CARD_INFO_MODE_OPTIONS.some((o) => o.value === p.cardInfoMode)
        ? (p.cardInfoMode as CardInfoMode)
        : DISPLAY_PREFS_DEFAULT.cardInfoMode,
      // 第 51 期新增三项：旧数据没有这些键 → 一律取默认（= 改造前行为）
      primaryLabel: CARD_PRIMARY_LABEL_OPTIONS.some((o) => o.value === p.primaryLabel)
        ? (p.primaryLabel as CardPrimaryLabel)
        : DISPLAY_PREFS_DEFAULT.primaryLabel,
      secondaryLabel: CARD_SECONDARY_LABEL_OPTIONS.some((o) => o.value === p.secondaryLabel)
        ? (p.secondaryLabel as CardSecondaryLabel)
        : DISPLAY_PREFS_DEFAULT.secondaryLabel,
      collapsedCover: COLLAPSED_COVER_OPTIONS.some((o) => o.value === p.collapsedCover)
        ? (p.collapsedCover as CollapsedCover)
        : DISPLAY_PREFS_DEFAULT.collapsedCover,
      authorCoverSize: readSize(
        p.authorCoverSize,
        DISPLAY_PREFS_DEFAULT.authorCoverSize,
        AUTHOR_COVER_SIZE_RANGE,
      ),
      authorCoverShape: AUTHOR_COVER_SHAPE_OPTIONS.some((o) => o.value === p.authorCoverShape)
        ? (p.authorCoverShape as AuthorCoverShape)
        : DISPLAY_PREFS_DEFAULT.authorCoverShape,
      zebraStriping:
        typeof p.zebraStriping === 'boolean'
          ? p.zebraStriping
          : DISPLAY_PREFS_DEFAULT.zebraStriping,
    }
  } catch {
    return { ...DISPLAY_PREFS_DEFAULT }
  }
}

export const useDisplayPrefsStore = defineStore('displayPrefs', () => {
  const prefs = ref<DisplayPrefs>(read())

  function save(): void {
    try {
      localStorage.setItem(KEY, JSON.stringify(prefs.value))
    } catch {
      /* 隐私模式下不可写：本次会话仍生效 */
    }
    notifyPrefsChanged()
  }

  function patch(p: Partial<DisplayPrefs>): void {
    prefs.value = { ...prefs.value, ...p }
    save()
  }

  function reset(): void {
    prefs.value = { ...DISPLAY_PREFS_DEFAULT }
    save()
  }

  /**
   * 应用远端（模式 / 设备）值：写 ref + 落盘，但**抑制通知**，避免把刚拉下来的值又推回去。
   *
   * ⚠️ 传进来的其实是整个 `appearance` 块（含 `theme` / `accent` / `radius`），故**逐键挑**、
   * 不整体 merge —— 否则那三个主题字段会被写进 `nf-display-prefs`，既脏了存储，
   * 也让「本机 display 值」与远端主题纠缠在一起。做法对齐 `theme.applyRemote`。
   * 远端值同样过量程校验：越界值不该把本机网格撑坏。
   */
  function applyRemote(next: Partial<DisplayPrefs>): void {
    suppressing(() => {
      const cur = prefs.value
      const merged: DisplayPrefs = {
        coverSize:
          typeof next.coverSize === 'number'
            ? readSize(next.coverSize, cur.coverSize, COVER_SIZE_RANGE)
            : cur.coverSize,
        gridGap:
          typeof next.gridGap === 'number'
            ? readSize(next.gridGap, cur.gridGap, GRID_GAP_RANGE)
            : cur.gridGap,
        cardInfoMode: CARD_INFO_MODE_OPTIONS.some((o) => o.value === next.cardInfoMode)
          ? (next.cardInfoMode as CardInfoMode)
          : cur.cardInfoMode,
        // 第 51 期新增三项：远端没带就保持本机值（与其它字段同口径）
        primaryLabel: CARD_PRIMARY_LABEL_OPTIONS.some((o) => o.value === next.primaryLabel)
          ? (next.primaryLabel as CardPrimaryLabel)
          : cur.primaryLabel,
        secondaryLabel: CARD_SECONDARY_LABEL_OPTIONS.some((o) => o.value === next.secondaryLabel)
          ? (next.secondaryLabel as CardSecondaryLabel)
          : cur.secondaryLabel,
        collapsedCover: COLLAPSED_COVER_OPTIONS.some((o) => o.value === next.collapsedCover)
          ? (next.collapsedCover as CollapsedCover)
          : cur.collapsedCover,
        authorCoverSize:
          typeof next.authorCoverSize === 'number'
            ? readSize(next.authorCoverSize, cur.authorCoverSize, AUTHOR_COVER_SIZE_RANGE)
            : cur.authorCoverSize,
        authorCoverShape: AUTHOR_COVER_SHAPE_OPTIONS.some((o) => o.value === next.authorCoverShape)
          ? (next.authorCoverShape as AuthorCoverShape)
          : cur.authorCoverShape,
        zebraStriping:
          typeof next.zebraStriping === 'boolean' ? next.zebraStriping : cur.zebraStriping,
      }
      prefs.value = merged
      save()
    })
  }

  // 兜底：本 store 直接暴露了 `prefs` ref，`prefs.prefs.x = v` 这种写法不经过 patch。
  // 照 `coverPrefs` 的写法，watcher 保证它仍然落盘并通知同步层。
  watch(prefs, () => suppressing(() => save()), { deep: true })

  return { prefs, patch, reset, applyRemote }
})
