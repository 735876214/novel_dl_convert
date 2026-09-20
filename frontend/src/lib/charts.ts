/**
 * ECharts 基建：图型注册、主题适配、调色板 —— 全站**唯一**的图表入口。
 *
 * 第 32 期起统计页照搬上游 BookOrbit 的图表，这里对齐它的两处选择：
 *
 * - **SVGRenderer 而非 Canvas**：SVG 的事件落在真实 DOM 元素上，不存在 canvas
 *   命中测试坐标错位导致的 hover 闪烁（上游 `client/src/lib/echarts.ts:34-36` 的注释
 *   记的就是这个 bug）。
 * - **按需 `use([...])`**：只注册本期用到的图型与组件，其余不进包（上游是全量注册
 *   12 图型 + 14 组件，本项目只搬用得上的）。
 *
 * 与上游有**两处有意偏离**，都因为本项目的主题机制与它不同（它是切换时换主题名，
 * 本项目是运行时改 `<html>` 的 class）：
 *
 * 1. **不用 `registerTheme` + `<VChart :theme>`**。上游预注册「模式 × 强调色」的主题名
 *    再传给组件；本项目换主题名会让 vue-echarts **重建实例**（丢动画、重挂 DOM），
 *    与「局部更新不重建 DOM」的既有约束冲突。故主题以**普通 option 片段**下发
 *    （`chartTheme()`），各图展开进自己的 option —— 换主题就是换 option，图表原地更新。
 * 2. **调色板不进主题**，由 `chartPalette()` 单独给。它随强调色而变，主题只随深浅而变；
 *    混在一起会让「只换强调色」也变成一次主题切换。图标底色也取同一份（见 ChartCard）。
 *
 * 调色板的事实源是 `--primary` 的计算值 —— 本项目 30+ 个 accent class 的唯一真相，
 * **不维护第二份 accent 数值表**（那份表必然与 `accents.css` 漂移）。OKLCH→sRGB 的
 * 数学照搬上游（`client/src/lib/echarts.ts:82-109`）：ECharts 的颜色解析器不认 oklch()。
 */
import {
  BarChart,
  BoxplotChart,
  ChordChart,
  CustomChart,
  FunnelChart,
  GaugeChart,
  HeatmapChart,
  LineChart,
  PieChart,
  ScatterChart,
  TreemapChart,
} from 'echarts/charts'
import {
  CalendarComponent,
  DataZoomInsideComponent,
  DataZoomSliderComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  MarkPointComponent,
  PolarComponent,
  TooltipComponent,
  VisualMapComponent,
} from 'echarts/components'
import { use as echartsUse } from 'echarts/core'
import { SVGRenderer } from 'echarts/renderers'
import { onMounted, onScopeDispose, ref, shallowRef, watch } from 'vue'

import { useThemeStore } from '@/stores/theme'

// ---------------------------------------------------------------------------
// 单点注册
// ---------------------------------------------------------------------------

/**
 * 加新图时**在这里加**，不要在组件里各自 `use()` —— 那样注册时机就绑到了组件的
 * 挂载顺序上，懒加载的图一出现就是空白。
 *
 * 括号里是本期各图的用途，删图时照着核对：
 */
echartsUse([
  SVGRenderer,
  // 图型
  BarChart, // 入库节奏 / 时段分布 / 周几分布 / 漏斗的 dropoff 模式 / 出版年代 / Top 作者 / Top 系列 / 体积榜 / 元数据覆盖率 / 分数分布 / 完成耗时 / 会话时间轴
  BoxplotChart, // 页数分布（上游是箱线图，不是直方图）
  ChordChart, // 题材共现（弦图，第 33 期）
  CustomChart, // 会话时间轴（一天的时段条，bar/scatter 都画不出「起点 + 长度」两个自由度）
  FunnelChart, // 进度漏斗
  GaugeChart, // 书库体检（半环仪表盘）
  HeatmapChart, // 按库的元数据覆盖率 + 阅读热力图（第 33 期）
  LineChart, // 出版年时间轴 / 按月读完 / 读完累计 / 格式占比随时间 / 题材阅读时长折线 / Top 作者与 Top 系列的累计占比折线
  PieChart, // 语言分布 / 格式分布
  ScatterChart, // 入库滞后 / 阅读速度 / 会话形态（第 33 期）
  TreemapChart, // 题材分布 / 题材阅读时长（矩形树图）
  // 组件
  CalendarComponent, // 阅读热力图（日历坐标系）
  GridComponent,
  TooltipComponent,
  LegendComponent,
  PolarComponent, // 阅读时钟（极坐标）
  VisualMapComponent, // 热力图与散点的分档配色（第 33 期）
  MarkAreaComponent, // 出版年时间轴的「黄金年代」区间 / 分数分布图的 P25–P75 阴影带
  MarkLineComponent, // 分数分布图的 P50 / P90 虚线
  MarkPointComponent, // 出版年时间轴的峰值标注
  DataZoomInsideComponent, // 出版年时间轴（滚轮 / 拖动缩放）
  DataZoomSliderComponent, // 出版年时间轴（底部滑块）
])

// ---------------------------------------------------------------------------
// 调色板
// ---------------------------------------------------------------------------

/** 相邻序列的色相错开，让同屏多序列更易区分（照搬上游的步长） */
const HUE_OFFSETS = [0, 72, 144, 216, 288, 36, 108, 180, 252, 324]

/** 低于此彩度就视为「无彩色」强调色（默认 neutral / accent-white / accent-grey 的 `--primary` 彩度为 0～0.006） */
const MIN_CHROMA = 0.05

/**
 * 无彩色强调色下的兜底明度与彩度。
 * 取值来自 `accents.css` 里各 accent 的**实际区间**（浅色 L≈0.49–0.76 / C≈0.14–0.27，
 * 深色 L≈0.72–0.84 / C≈0.14–0.23），取中位 —— 不另造一套配色。
 */
const FALLBACK = {
  light: { l: 0.58, c: 0.2 },
  dark: { l: 0.74, c: 0.18 },
}

/** `:root` 的 `--tint-h` 默认值（tokens.css），读不到变量时的最后兜底 */
const DEFAULT_TINT_HUE = 80

/**
 * OKLCH → sRGB hex。逐行照搬上游 `client/src/lib/echarts.ts:82-109`
 * （超出 sRGB 色域的分量按上游做法直接裁剪到 [0,1]）。
 */
export function oklchToHex(L: number, C: number, H: number): string {
  const h = (H * Math.PI) / 180
  const a = C * Math.cos(h)
  const b = C * Math.sin(h)
  const l_ = L + 0.3963377774 * a + 0.2158037573 * b
  const m_ = L - 0.1055613458 * a - 0.0638541728 * b
  const s_ = L - 0.0894841775 * a - 1.291485548 * b
  const l = l_ ** 3
  const m = m_ ** 3
  const s = s_ ** 3
  const lr = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
  const lg = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
  const lb = -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s
  const toSrgb = (v: number) => {
    const c = Math.max(0, Math.min(1, v))
    return c <= 0.0031308 ? c * 12.92 : 1.055 * c ** (1 / 2.4) - 0.055
  }
  return (
    '#' +
    [lr, lg, lb]
      .map((v) =>
        Math.round(toSrgb(v) * 255)
          .toString(16)
          .padStart(2, '0'),
      )
      .join('')
  )
}

/** `<html>` 上的 class 挂没挂 —— 深浅的真相源（见 `useChartTheme` 的注释） */
function domIsDark(): boolean {
  return document.documentElement.classList.contains('dark')
}

/**
 * 读一个 CSS 颜色变量的 oklch 三元组。
 *
 * 走 `getComputedStyle(documentElement).getPropertyValue()`：自定义属性的计算值会把
 * `var()` 展开（`--primary` 在 `:root` 里是 `oklch(0.21 var(--tint-c-surface) var(--tint-h))`），
 * 并应用 `<html>` 上的 class 覆盖（`.dark` / `.accent-*`），所以拿到的就是**当前生效**的值。
 *
 * 浏览器对 oklch() 的计算值保留原色彩空间（CSS Color 4），故能直接解析；解析不出
 * （老浏览器折算成了 rgb()）返回 null，由调用方回落到兜底配色。
 */
function readOklch(varName: string): [number, number, number] | null {
  const raw = getComputedStyle(document.documentElement).getPropertyValue(varName)
  const m = raw.match(/oklch\(\s*([\d.]+%?)\s+([\d.]+%?)\s+([\d.]+)/i)
  if (!m) return null
  const n = (s: string) => (s.endsWith('%') ? parseFloat(s) / 100 : parseFloat(s))
  return [n(m[1]), n(m[2]), parseFloat(m[3])]
}

/** `--tint-h` 是**裸数字**的色相（不是颜色），不能走 readOklch */
function readTintHue(): number {
  const raw = getComputedStyle(document.documentElement).getPropertyValue('--tint-h').trim()
  const n = parseFloat(raw)
  return Number.isFinite(n) ? n : DEFAULT_TINT_HUE
}

/**
 * 按当前强调色生成 10 色序列调色板（给 ECharts 当 `color` 用）。
 *
 * 色相取自 `--primary`，但**默认 neutral 与 accent-white / accent-grey 的 `--primary`
 * 是无彩色**，原样用会画出一片灰（饼图直接不可读）。故这类情况保留它的**表面色相**
 * （`--tint-h`，默认 80 = 暖琥珀），只把明度与彩度换成 accent 的中位取值。
 */
export function chartPalette(): string[] {
  const fallback = domIsDark() ? FALLBACK.dark : FALLBACK.light
  const primary = readOklch('--primary')

  let l = fallback.l
  let c = fallback.c
  let h = readTintHue()
  if (primary && primary[1] >= MIN_CHROMA) {
    ;[l, c, h] = primary
  }

  return HUE_OFFSETS.map((off) => oklchToHex(l, c, h + off))
}

/**
 * 单色深浅序列：热力图的**分档配色**（取调色板首色，按递增不透明度铺开）。
 *
 * 为什么是「一色多档」而不是彩虹色：热力图读的是**深浅**，多色相（上游入库滞后那张
 * 用了绿→黄→橙→红）在深色主题下会有一半档位糊在背景里，且红绿相邻对色觉障碍不友好。
 *
 * `palette` 由调用方从 `useChartTheme()` 里传进来（**不是**在这里读 DOM）：
 * 这个函数要能在 `computed` 里跟着主题/强调色重算，所以必须是 palette 的纯函数。
 */
export function chartShades(palette: string[], steps = 5): string[] {
  const base = palette[0] ?? '#888888'
  // 8 位 hex 的 alpha 分量（ECharts 的取色器认 #RRGGBBAA）
  const alphas = ['14', '3d', '66', 'a3', 'ff']
  Array.from({ length: Math.max(0, steps - alphas.length) }).forEach(() => alphas.push('ff'))
  return alphas.slice(0, Math.max(1, steps)).map((a) => `${base}${a}`)
}

// ---------------------------------------------------------------------------
// 主题（以 option 片段下发，见文件头第 1 条偏离）
// ---------------------------------------------------------------------------

export interface ChartThemeParts {
  /** 浅描边色：轴线的，也是分割线与 tooltip 边框的 */
  border: string
  /** 轴标签色（比正文弱一档） */
  axisLabel: string
  /**
   * 轴标签样式。要改字号 / 旋转角时展开它 —— 例如：
   * `axisLabel: { ...t.axisLabelStyle, fontSize: 11, rotate: 35 }`
   */
  axisLabelStyle: { show: boolean; color: string }
  /**
   * 轴样式，展开进 xAxis / yAxis：`{ ...t.axis, type: 'category', data }`。
   * ⚠️ 先展开它**再**覆盖 `axisLabel` —— 反过来会被它自带的 `axisLabel` 盖回去。
   */
  axis: Record<string, unknown>
  /** legend 文字色，展开进 legend：`{ ...t.legend, data: [...] }` */
  legend: { textStyle: { color: string } }
  /** tooltip 样式，展开进 tooltip：`{ trigger: 'item', ...t.tooltip, formatter }` */
  tooltip: {
    backgroundColor: string
    borderColor: string
    textStyle: { color: string }
  }
}

/**
 * 中性色片段 —— 只管**跟着深浅变**的部分（轴 / 分割线 / tooltip / legend）。
 * 序列颜色由 `chartPalette()` 给，两者分开（见文件头第 2 条偏离）。
 *
 * 取值照搬上游 `buildTheme()`（`client/src/lib/echarts.ts:129-152`）。
 */
export function chartTheme(dark: boolean): ChartThemeParts {
  const border = dark ? 'rgba(255,255,255,0.10)' : 'rgba(0,0,0,0.12)'
  const axisLabel = dark ? '#9CA3AF' : '#6B7280'
  const axisLabelStyle = { show: true, color: axisLabel }
  const axis = {
    axisLine: { show: true, lineStyle: { color: border } },
    axisTick: { show: false },
    axisLabel: axisLabelStyle,
    splitLine: { show: true, lineStyle: { color: [border] } },
    splitArea: { show: false },
  }

  return {
    border,
    axisLabel,
    axisLabelStyle,
    axis,
    legend: { textStyle: { color: dark ? '#F3F4F6' : '#111827' } },
    tooltip: {
      backgroundColor: dark ? '#1F2937' : '#FFFFFF',
      borderColor: border,
      textStyle: { color: dark ? '#F9FAFB' : '#111827' },
    },
  }
}

// ---------------------------------------------------------------------------
// 组合式：给各图用的响应式主题
// ---------------------------------------------------------------------------

/**
 * 主题三件套。三者都读同一份 DOM 状态，故一起重算、一次给全。
 *
 * ⚠️ 深浅读的是 `<html>` 的 class，**不是** store 的 `isDark`：`theme.ts` 的
 * `watchSystem()` 在「跟随系统」模式下切主题时只改 class、不动响应式数据，
 * 那条路径上 `isDark` 不会重算。这里以 DOM 为真相源，另配一个 media query 监听
 * （见下）补齐那个缺口。
 */
export function useChartTheme() {
  const store = useThemeStore()
  const dark = shallowRef(false)
  const palette = shallowRef<string[]>([])
  const theme = shallowRef<ChartThemeParts>(chartTheme(false))

  function refresh(): void {
    const d = domIsDark()
    dark.value = d
    palette.value = chartPalette()
    theme.value = chartTheme(d)
  }

  // 强调色或深浅变化：`applyClasses()` 是**同步**挂 class 的，而 watch 回调在微任务里
  // 跑，所以回调时 class 一定已就位，读 DOM 不会读到上一步的值。
  watch(() => [store.isDark, store.accent], refresh)

  // 首屏兜底：store 的 applyClasses() 未必早于本 composable 的首次执行
  onMounted(refresh)

  if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const onSystemChange = (): void => {
      // 只有「跟随系统」才理会；显式选了浅/深时系统怎么变都不该动
      if (store.theme === 'system') refresh()
    }
    mq.addEventListener?.('change', onSystemChange)
    onScopeDispose(() => mq.removeEventListener?.('change', onSystemChange))
  }

  return { dark, palette, theme }
}

/**
 * `matchMedia` 的响应式封装 —— 图上要按容器宽度改布局（饼图 legend 横排还是竖排、
 * 圆心偏左还是居中）时用它。
 *
 * 上游用的是 `@vueuse/core` 的 `useBreakpoints`；本项目不引那个库，这十几行够用。
 * 默认断点与 Tailwind 的 `md` 一致，与栅格 `md:grid-cols-2` 同一条线。
 */
export function useIsWide(query = '(min-width: 768px)') {
  const matches = ref(false)
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return matches

  const mq = window.matchMedia(query)
  matches.value = mq.matches
  const onChange = (e: MediaQueryListEvent): void => {
    matches.value = e.matches
  }
  mq.addEventListener?.('change', onChange)
  onScopeDispose(() => mq.removeEventListener?.('change', onChange))

  return matches
}
