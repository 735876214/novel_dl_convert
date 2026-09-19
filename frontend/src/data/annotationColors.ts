/**
 * 批注高亮色的**唯一**调色板。
 *
 * 此前仓库有 4 处各写了一份一模一样的四色表（阅读器 `ReaderView`、批注总览
 * `AnnotationsView`、图书详情「批注」tab `BookDetailView`、每日划线
 * `HighlightOfTheDayWidget`），每处都是 `X[c] || X.yellow` 兜底 —— 那种写法在
 * 颜色扩容时会**静默出错**：没改到的页面把新颜色统统渲染成黄色，不报任何错。
 * 所以调色板只留这一份，四处一律引用这里。
 *
 * ⚠️ 键名就是后端 `annotations.color` 里存的值（纯字符串），所以：
 * **新增颜色只往这里加，不要改既有键名** —— 改了会让存量批注找不到颜色、
 * 掉进兜底色。现有的 yellow/green/blue/pink 四色是沿用值，色值不能动。
 *
 * 来源说明：上游应用侧为 10 色。除既有 4 色外，其余 6 色的**具体色值未经上游源码
 * 逐色取证**（未验证），是按同一柔和色域尽量拉开色相后定的；如需严格逐色对齐，
 * 以将来取到的上游常量为准替换这 6 个值即可（键名与兜底逻辑不受影响）。
 */
export interface HighlightColor {
  /** 存进 DB 的键（`annotations.color`） */
  key: string
  /** 阅读器调色板的无障碍标签 */
  label: string
  hex: string
}

/** 黄→橙→红→粉→品红→紫→蓝→青→绿→灰：同一柔和色域内把色相尽量拉开。 */
export const HIGHLIGHT_COLORS: HighlightColor[] = [
  { key: 'yellow', label: '黄色高亮', hex: '#f5d76e' },
  { key: 'orange', label: '橙色高亮', hex: '#f2b17a' },
  { key: 'red', label: '红色高亮', hex: '#ec9a9a' },
  { key: 'pink', label: '粉色高亮', hex: '#f2a6c4' },
  { key: 'magenta', label: '品红高亮', hex: '#d9a0e0' },
  { key: 'purple', label: '紫色高亮', hex: '#b3a4ec' },
  { key: 'blue', label: '蓝色高亮', hex: '#8fc1f0' },
  { key: 'teal', label: '青色高亮', hex: '#7fd0cd' },
  { key: 'green', label: '绿色高亮', hex: '#8fd694' },
  { key: 'gray', label: '灰色高亮', hex: '#b9c0c9' },
]

/** 未知颜色与新建批注的回落色 —— 这个名字在迁移前的存量数据里就已经在用了。 */
export const DEFAULT_HIGHLIGHT_COLOR = 'yellow'

const HEX_BY_KEY: Record<string, string> = Object.fromEntries(
  HIGHLIGHT_COLORS.map((c) => [c.key, c.hex]),
)

/** 取颜色的十六进制值。未知/历史颜色回落到默认色，**不抛错** —— 显示层不该因脏数据崩。 */
export function highlightHex(color: string): string {
  return HEX_BY_KEY[color] || HEX_BY_KEY[DEFAULT_HIGHLIGHT_COLOR]
}
