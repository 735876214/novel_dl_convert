/**
 * ECharts **注册入口**（全站唯一）—— 图型 / 组件 / 渲染器只在这里 `use()`。
 *
 * 第 179 期拆过一次：配色与主题的**纯计算**（`oklchToHex` / `cssVarHex` / `chartPalette` /
 * `chartShades` / `chartTheme` / `useChartTheme` / `useIsWide`）搬到了 `@/lib/chartTheme`，
 * 因为本文件带 `echartsUse([...])` 的**副作用** —— 任何 import 它的模块都会把整包
 * ECharts（773 KB / 255 KB gzip）打进自己的 chunk。「阅读活动」页只需要算五个热力图颜色，
 * 却因此下载了整个 ECharts。
 *
 * 现在：
 *   · 画图的组件（`ChartFrame` / 各 `*Chart.vue`）**继续 import `@/lib/charts`** —— 注册必须
 *     在它们首次渲染前发生，靠的就是这个 import 的副作用；
 *   · 只要颜色 / 主题、不画图的模块（如 `views/ReadingActivityView.vue`）import
 *     `@/lib/chartTheme`，不碰这个文件；
 *   · 本文件把 `chartTheme` 的成员 **re-export** 出去，既有 `import { useChartTheme } from
 *     '@/lib/charts'` 的调用点一个都不用改（re-export 不是第二份实现）。
 *
 * 两处与上游 BookOrbit 的**有意偏离**（实现见 `chartTheme.ts`）：
 *
 * 1. **不用 `registerTheme` + `<VChart :theme>`**。上游预注册「模式 × 强调色」的主题名
 *    再传给组件；本项目换主题名会让 vue-echarts **重建实例**（丢动画、重挂 DOM），
 *    与「局部更新不重建 DOM」的既有约束冲突。故主题以**普通 option 片段**下发
 *    （`chartTheme()`），各图展开进自己的 option —— 换主题就是换 option，图表原地更新。
 * 2. **调色板不进主题**，由 `chartPalette()` 单独给。它随强调色而变，主题只随深浅而变；
 *    混在一起会让「只换强调色」也变成一次主题切换。图标底色也取同一份（见 ChartCard）。
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

// 配色 / 主题的纯实现都在 chartTheme（不引 ECharts）；这里只做转出。
export {
  chartPalette,
  chartShades,
  chartTheme,
  cssVarHex,
  oklchToHex,
  useChartTheme,
  useIsWide,
  type ChartThemeParts,
} from '@/lib/chartTheme'

// ---------------------------------------------------------------------------
// 单点注册
// ---------------------------------------------------------------------------

/**
 * 加新图时**在这里加**，不要在组件里各自 `use()` —— 那样注册时机就绑到了组件的
 * 挂载顺序上，懒加载的图一出现就是空白。
 *
 * 括号里是各图的用途，删图时照着核对：
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
