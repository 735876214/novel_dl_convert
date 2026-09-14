/**
 * 点缀色 65 档。迁移自 v2 app.js 的 ACCENTS（原第 125–191 行）。
 *
 * 与 accents.css 的 accent-<name> 类一一对应：
 *   前 21 档为 vivid，后 44 档为 pastel，neutral 为默认（不挂类）。
 * `c` 只用于在设置页画 swatch 的取色；真正的变量覆盖由 accents.css 完成。
 */
export interface AccentOption {
  name: string
  label: string
  /** swatch 取色 */
  c: string
}

export const ACCENTS: AccentOption[] = [
  { name: 'neutral', label: '中性', c: 'oklch(0.21 0.006 80)' },
  { name: 'white', label: '白', c: 'oklch(0.2 0 0)' },
  { name: 'grey', label: '灰', c: 'oklch(0.55 0 0)' },
  { name: 'scarlet', label: '猩红', c: 'oklch(0.58 0.25 2)' },
  { name: 'rose', label: '玫瑰', c: 'oklch(0.57 0.24 15)' },
  { name: 'orange', label: '橙', c: 'oklch(0.64 0.22 42)' },
  { name: 'marigold', label: '金盏', c: 'oklch(0.76 0.18 82)' },
  { name: 'amber', label: '琥珀', c: 'oklch(0.72 0.17 70)' },
  { name: 'yellow', label: '黄', c: 'oklch(0.75 0.18 95)' },
  { name: 'viridian', label: '铬绿', c: 'oklch(0.54 0.17 171)' },
  { name: 'lime', label: '青柠', c: 'oklch(0.64 0.2 118)' },
  { name: 'green', label: '绿', c: 'oklch(0.527 0.18 142)' },
  { name: 'emerald', label: '翡翠', c: 'oklch(0.52 0.17 162)' },
  { name: 'teal', label: '鸭青', c: 'oklch(0.52 0.18 180)' },
  { name: 'cyan', label: '青蓝', c: 'oklch(0.52 0.2 197)' },
  { name: 'jade', label: '玉', c: 'oklch(0.62 0.2 155)' },
  { name: 'iris', label: '鸢尾', c: 'oklch(0.52 0.25 270)' },
  { name: 'blue', label: '蓝', c: 'oklch(0.487 0.25 263)' },
  { name: 'indigo', label: '靛', c: 'oklch(0.51 0.26 276)' },
  { name: 'violet', label: '紫罗兰', c: 'oklch(0.491 0.27 292)' },
  { name: 'fuchsia', label: '紫红', c: 'oklch(0.56 0.27 312)' },
  { name: 'pink', label: '粉', c: 'oklch(0.56 0.26 328)' },
  { name: 'rosewater', label: '玫瑰水', c: 'oklch(0.7 0.125 2)' },
  { name: 'coral', label: '珊瑚', c: 'oklch(0.69 0.12 15)' },
  { name: 'peach', label: '蜜桃', c: 'oklch(0.76 0.11 42)' },
  { name: 'flax', label: '亚麻', c: 'oklch(0.82 0.09 82)' },
  { name: 'butter', label: '奶油', c: 'oklch(0.82 0.085 70)' },
  { name: 'lemon', label: '柠檬', c: 'oklch(0.82 0.09 95)' },
  { name: 'foam', label: '泡沫', c: 'oklch(0.68 0.085 171)' },
  { name: 'celadon', label: '青瓷', c: 'oklch(0.76 0.1 118)' },
  { name: 'sage', label: '鼠尾草', c: 'oklch(0.68 0.09 142)' },
  { name: 'mint', label: '薄荷', c: 'oklch(0.68 0.085 162)' },
  { name: 'seafoam', label: '海沫', c: 'oklch(0.68 0.09 180)' },
  { name: 'powder', label: '粉蓝', c: 'oklch(0.68 0.1 197)' },
  { name: 'sea-glass', label: '海玻璃', c: 'oklch(0.74 0.1 155)' },
  { name: 'cornflower', label: '矢车菊', c: 'oklch(0.68 0.14 247)' },
  { name: 'periwinkle', label: '长春花', c: 'oklch(0.68 0.125 263)' },
  { name: 'wisteria', label: '紫藤', c: 'oklch(0.68 0.13 276)' },
  { name: 'lavender', label: '薰衣草', c: 'oklch(0.68 0.135 292)' },
  { name: 'orchid', label: '兰花', c: 'oklch(0.68 0.135 312)' },
  { name: 'blush', label: '胭脂', c: 'oklch(0.68 0.13 328)' },
  { name: 'vermilion', label: '朱红', c: 'oklch(0.62 0.24 28)' },
  { name: 'salmon', label: '鲑粉', c: 'oklch(0.74 0.12 28)' },
  { name: 'copper', label: '铜', c: 'oklch(0.65 0.19 56)' },
  { name: 'sand', label: '沙', c: 'oklch(0.77 0.095 56)' },
  { name: 'chartreuse', label: '黄绿', c: 'oklch(0.76 0.2 106)' },
  { name: 'pear', label: '梨', c: 'oklch(0.82 0.1 106)' },
  { name: 'wasabi', label: '芥末', c: 'oklch(0.68 0.19 130)' },
  { name: 'sprout', label: '新芽', c: 'oklch(0.8 0.095 130)' },
  { name: 'malachite', label: '孔雀石', c: 'oklch(0.56 0.18 152)' },
  { name: 'aloe', label: '芦荟', c: 'oklch(0.68 0.09 152)' },
  { name: 'turquoise', label: '松石', c: 'oklch(0.58 0.18 188)' },
  { name: 'aqua', label: '水色', c: 'oklch(0.7 0.09 188)' },
  { name: 'acid-green', label: '酸绿', c: 'oklch(0.7 0.2 112)' },
  { name: 'pistachio', label: '开心果', c: 'oklch(0.8 0.11 112)' },
  { name: 'electric-blue', label: '电光蓝', c: 'oklch(0.54 0.24 230)' },
  { name: 'baby-blue', label: '天蓝', c: 'oklch(0.68 0.12 230)' },
  { name: 'ultramarine', label: '群青', c: 'oklch(0.5 0.28 247)' },
  { name: 'bluebell', label: '风铃草', c: 'oklch(0.68 0.125 270)' },
  { name: 'purple', label: '紫', c: 'oklch(0.51 0.25 284)' },
  { name: 'thistle', label: '蓟', c: 'oklch(0.68 0.125 284)' },
  { name: 'amethyst', label: '紫晶', c: 'oklch(0.54 0.24 302)' },
  { name: 'mauve', label: '木槿', c: 'oklch(0.68 0.12 302)' },
  { name: 'raspberry', label: '覆盆子', c: 'oklch(0.56 0.23 344)' },
  { name: 'rose-quartz', label: '蔷薇石英', c: 'oklch(0.68 0.115 344)' },
]

/** 由 name 反查中文标签（设置页与 toast 用） */
export function accentLabel(name: string): string {
  return ACCENTS.find((a) => a.name === name)?.label ?? name
}
