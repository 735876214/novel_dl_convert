import { defineStore } from 'pinia'
import { ref } from 'vue'

import {
  DEFAULT_CHART_ORDER,
  STATISTICS_CHART_META,
  type StatisticsChartId,
  type StatisticsTab,
} from '@/lib/statistics-charts'

/**
 * 统计页图表配置（对应上游统计页的 Configure 面板：显隐 + 顺序）。
 *
 * 存 localStorage，与 `stores/shelfPrefs` 同一档 —— 这两者都是**本地视图偏好**
 * （这块屏幕怎么摆），不是「外观 / 阅读偏好」，所以**不进偏好同步载荷**。好处是
 * 不动服务端 `PREFS_BLOCKS` 的六块契约（`server.py:3001`），代价是换设备不同步。
 * 上游把这份配置存进 `users/me/settings` 跟账号走（`useStatisticsConfig.ts:93-104`）；
 * 本项目没有用户级 settings 表，既有边界就是「视图偏好留在本地」，故照既有边界来。
 *
 * 与上游的两处形态差异（语义等价）：
 *
 * 1. 上游是**扁平**的 `{id,visible,order}[]`，重排时把「不在本次列表里的」当隐藏项
 *    按原 order 追加到末尾（`:141-164`）。由于两个分区各自只把本分区的图交给重排，
 *    那个写法会让**另一个分区**的 order 整体挪到后面（相对顺序不变，所以看不出问题）。
 *    本项目改成**按分区各存一份有序数组**，分区之间彻底互不干扰。
 * 2. 上游 600ms 防抖写服务端（`:106-110`）；写 localStorage 是同步的，不需要防抖。
 */

export interface StatsChartPrefs {
  /**
   * 每个分区的顺序。**含被隐藏的图** —— 隐藏只是不画，它排在第几位要记着。
   *
   * 类型收窄成 `StatisticsChartId[]`（而不是 `string[]`）：这个数组的每个元素都要拿去
   * 查 `STATISTICS_CHART_META`，而目录的键现在是字面量联合，宽类型查不动。
   */
  order: Record<StatisticsTab, StatisticsChartId[]>
  /** 被隐藏的图表 id（顺序里仍在，只是不渲染）。宽成 string：只做集合查询，不查表 */
  hidden: string[]
}

const KEY = 'nf-stats-chart-prefs'

const TABS: StatisticsTab[] = ['library', 'reading']

function defaults(): StatsChartPrefs {
  return {
    order: {
      library: [...DEFAULT_CHART_ORDER.library],
      reading: [...DEFAULT_CHART_ORDER.reading],
    },
    hidden: [],
  }
}

/** 存档是**不可信输入**（版本回退、手改过 localStorage）：一律先当 unknown 读，再逐项收窄 */
interface RawPrefs {
  order?: Partial<Record<StatisticsTab, unknown>>
  hidden?: unknown
}

/** 非数组一律当空 */
function asList(v: unknown): unknown[] {
  return Array.isArray(v) ? v : []
}

/**
 * 读取时归一（照上游 `normalizeCharts` 的语义）：
 * 丢掉不认识的 id（版本回退、手改过 localStorage），给**新增的图补位**到末尾，
 * 这样以后补图时老用户的存档不会把新图吞掉。
 */
function read(): StatsChartPrefs {
  const fallback = defaults()
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return fallback
    const p = JSON.parse(raw) as RawPrefs
    // 白名单用 `Object.keys` 的集合，**不用 `id in META`** —— 后者会命中原型链上的名字
    // （存档里手写一个 "constructor" 就会被当成合法 id）
    const known = new Set<string>(Object.keys(STATISTICS_CHART_META))

    /** 收窄成一个合法 id；不合法（含原型链上的名字）返回 null */
    const asId = (v: unknown): StatisticsChartId | null =>
      typeof v === 'string' && known.has(v) ? (v as StatisticsChartId) : null

    const order = { library: [], reading: [] } as Record<StatisticsTab, StatisticsChartId[]>
    for (const tab of TABS) {
      const saved = asList(p.order?.[tab])
        .map(asId)
        .filter((id): id is StatisticsChartId => id !== null)
        .filter((id) => STATISTICS_CHART_META[id].tab === tab)
      // 去重：存档里重复的 id 会让同一张图渲染两次（`v-for` 的 key 还会撞）
      const unique = [...new Set(saved)]
      order[tab] = [...unique, ...DEFAULT_CHART_ORDER[tab].filter((id) => !unique.includes(id))]
    }

    const hidden = asList(p.hidden)
      .map(asId)
      .filter((id): id is StatisticsChartId => id !== null)
    return { order, hidden: [...new Set(hidden)] }
  } catch {
    return fallback
  }
}

export const useStatsChartPrefsStore = defineStore('statsChartPrefs', () => {
  const prefs = ref<StatsChartPrefs>(read())

  function save(): void {
    try {
      localStorage.setItem(KEY, JSON.stringify(prefs.value))
    } catch {
      /* 隐私模式下不可写：本次会话仍生效 */
    }
  }

  function isVisible(id: string): boolean {
    return !prefs.value.hidden.includes(id)
  }

  function toggle(id: string): void {
    prefs.value = {
      ...prefs.value,
      hidden: isVisible(id)
        ? [...prefs.value.hidden, id]
        : prefs.value.hidden.filter((x) => x !== id),
    }
    save()
  }

  /** 在分区内上移 / 下移一位；已经在头尾则不动 */
  function move(tab: StatisticsTab, id: string, delta: -1 | 1): void {
    const list = [...prefs.value.order[tab]]
    // 用 `===` 找而不是 `indexOf(id)`：id 是宽 string，直接 indexOf 通不过类型检查
    const from = list.findIndex((x) => x === id)
    const to = from + delta
    if (from < 0 || to < 0 || to >= list.length) return
    const a = list[from]
    const b = list[to]
    if (a === undefined || b === undefined) return
    list[from] = b
    list[to] = a
    prefs.value = { ...prefs.value, order: { ...prefs.value.order, [tab]: list } }
    save()
  }

  /** 恢复默认：全部可见 + 默认顺序 */
  function reset(): void {
    prefs.value = defaults()
    save()
  }

  return { prefs, isVisible, toggle, move, reset }
})
