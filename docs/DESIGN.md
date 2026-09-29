# DESIGN.md — 视觉规则

> 视觉层**逐字照搬上游 BookOrbit**（`github.com/bookorbit/bookorbit`，AGPL-3.0），
> 落点为 `frontend/src/assets/theme/*.css`。**组件里禁止硬编码颜色/圆角/阴影** —— 一律用这里的 token 与 Tailwind 语义类。
>
> ⚠️ 历史提醒：更早的原型（`novelforge/static/` 下那套手写页）用的是 `#2563eb` / `#6366f1` 一类十六进制配色，
> **那套已作废**，现行主题是 oklch token 体系。看到旧色值一律按过时处理。

---

## 1. 样式入口与加载顺序

`frontend/src/assets/main.css` 是唯一入口，**顺序不可变**：

```
fonts.css            ← 自托管字体（10 个 woff2），必须在 tailwindcss 之前，保证 @font-face 先注册
tailwindcss
theme/tokens.css     ← 原子变量（--background / --muted-foreground …）
theme/accents.css    ← 65 档 accent class，覆盖 --tint-h 与 --primary
theme/radius.css     ← 4 档圆角，覆盖 --radius
theme/bridge.css     ← @theme inline 桥接层（把变量映射成 Tailwind 工具类）
theme/cover-effects.css  ← 书封视觉效果
```

两处刻意的与上游差异（已在 main.css 注明）：① 字体不用 `@fontsource-variable/*`，改本地自托管（**零外部请求**，NAS 内网可用）；
② 未引 `tw-animate-css`，动效由 `main.css` 的 keyframes 提供。

## 2. 主题架构（改一处即换整套观感）

```
--tint-h / --tint-c   控制所有中性表面的色相与彩度（默认 --tint-h: 80，暖中性）
accent-* 类           覆盖 --tint-h（表面）+ --primary（交互元素）
radius-* 类           覆盖 --radius
.dark                 覆盖明度，并略微抬高 --tint-c
```

- 应用方式：class 打在 **`<html>`** 上（如 `<html class="dark accent-blue radius-rounded">`）。
- 默认（不加 accent 类）= **neutral**，即 tokens.css 里的暖中性 `--tint-h: 80`。
- **65 档点缀色**分两组：**Vivid**（高彩度）与 **Pastel**（低彩度）；黄/黄绿档会把前景文字换成深色以保证可读性。
  档位清单即 `theme/accents.css` 的 `html.accent-*` 选择器。
- `bridge.css` 用 `@theme inline`（**不是** `@theme`）：工具类直接引用 `var(--background)` 这类原子变量，
  于是运行时切主题**无需重新生成 CSS** —— 这是「主题切换零重渲染」的前提。

## 3. 语义 token（写界面时用这些，不要用字面色）

| 类别 | token |
|---|---|
| 基底 | `--background` `--foreground` `--card` `--popover` `--secondary` `--muted` `--accent` `--border` `--input` `--ring` |
| 主/危/态 | `--primary` `--primary-foreground` `--destructive` `--success` `--warning` `--info` `--star-highlight` |
| 侧栏 | `--sidebar` `--sidebar-foreground` `--sidebar-count-foreground` `--sidebar-primary` `--sidebar-accent` `--sidebar-border` |
| 高程面 | `--surface-1..4`（卡片内的层次） |
| 外壳 | `--shell-gap` `--shell-content-gutter` `--shell-surface-opacity` `--shell-surface` `--shell-border` |
| 递进点缀 | `--shell-accent-wash`（6%）`--shell-accent-tint`（12%）`--shell-accent-line`（30%） |

对应 Tailwind 类：`bg-background` `text-foreground` `bg-card` `text-muted-foreground` `border-border` `bg-primary` `text-primary-foreground` …（映射见 `bridge.css`）。

## 4. 固定色板（**不随 accent 变**，因为它们是「事实」而非品牌）

| 族 | 用途 | 变量前缀 |
|---|---|---|
| 系列卷状态 | 已读 / 在读 / 未读 / 缺失 | `--volume-*` |
| 元数据评分坡 | 红 → 橙 → 黄 → 绿（消费者用 `color-mix` 插值） | `--score-red/orange/yellow/green` |
| 格式族 | 电子书 / Kindle / 文档 / 漫画 / 音频 / 其它（书库构成条） | `--format-*` |
| 格式胶囊 | `epub` `pdf` `cbz` `mobi` …（各格式一个色相，文字自带颜色） | `--pill-format-*` |
| 批注来源/状态/媒体 | `--pill-web` `--pill-koreader` `--pill-kobo` `--pill-repaired` `--pill-pending` `--pill-media-*` … | `--pill-*` |
| 命名规则语法 | 占位符 / 修饰符 / 可选段 / 回落 | `--pattern-token/modifier/optional/fallback` |
| 重命名差异 | 删除 / 新增 / 未变 / 路径分隔 | `--diff-del*` `--diff-ins*` `--path-dim` `--path-fold` |
| 审计类别 | 认证 / 书籍 / 用户 / 书库 / 收藏 / 集成 / 设置 | `--audit-*` |
| 供应商徽标 | 品牌色混合比（浅色态把 ink 往表面色混以过 AA） | `--provider-fill/ring/ink/ink-base` |

**为什么固定**：同一实体的颜色在所有 accent 下必须一致，否则「绿色=已读」会在换主题后失真。

## 5. 圆角与阴影

```css
--radius: 0.625rem            /* 默认 */
html.radius-sharp   { --radius: 0rem }
html.radius-rounded { --radius: 1.25rem }
html.radius-pill    { --radius: 2.5rem }
--shell-radius: min(var(--radius), 1.25rem)   /* 外壳卡片封顶，pill 档不会把整面板圆成胶囊 */
```

- Tailwind 档位全部由 `--radius` 派生：`rounded-sm/md/lg/xl/2xl/3xl` = `--radius` ∓ 4/2/0/+4/+8/+12 px。
- 阴影 6 档：`--elevation-xs` → `--elevation-2xl`（浅色低透明、深色提高不透明度）。**不要把阴影写在组件里**。

## 6. 字体与排版

| 角色 | 栈 | 说明 |
|---|---|---|
| 正文/界面 | `--font-sans` = `'Inter Variable', ui-sans-serif, system-ui, …` | 自托管可变字体 |
| 标题/衬线 | `--font-serif` = `'Fraunces Variable', ui-serif, Georgia, serif` | 页头大标题用它 |
| 等宽 | `--font-mono` = `ui-monospace, SFMono-Regular, …` | 路径 / 代码 |

- `body` 基准：`font-size: 14px`、`line-height: 1.5`，背景/文字各 0.15s 过渡。
- 触屏（`pointer: coarse`）下输入控件强制 **16px** 以防 iOS 聚焦缩放。
- 阅读器另有一套**阅读主题（13 档）与排版偏好**，属内容区，与外壳主题互不影响（`lib/readerPrefs.ts`）。

## 7. 动效

统一 keyframes 于 `main.css`，全部包在 `@media (prefers-reduced-motion: no-preference)` 内，
并提供 `prefers-reduced-motion: reduce` 的全局降级（时长压到 0.001ms）：

`animate-fade-in` / `animate-fade-up` / `animate-scale-in` / `animate-shimmer`（骨架屏）/ `animate-shake` /
`animate-float` / `animate-count-pulse` / `animate-progress-stripes`。

## 8. 组件范式（配合 `docs/component-api.md`）

- 原语在 `components/ui/`：`Card` / `Button` / `Badge` / `Icon` / `IconButton` / `Segment` / `SwatchGrid` /
  `TabBar` / `RatingStars` / `ProgressBar` / `ProgressRing` / `StatTile` / `EmptyState` / `PageHead` /
  `BookCover` / `DropdownMenu`。**新页面优先复用，不要另起一套按钮/卡片。**
- 交互范式：设置页=「行 + 标签 + 控件」；工具页=顶部下划线标签栏 + 页内切换；浮层用 `Teleport` 到 body。
- 状态诚实：读失败要说出来（可重试），**不许靠 `catch {}` 让块变空**；空态区分「加载中 / 无匹配 / 空」；
  计数不要出现 `N/0`。
- 窄屏双写法：宽屏 `<table class="hidden md:block">` + 窄屏 `<ul class="md:hidden">`；纯装饰增强取不到就不设变量。
- 焦点可见：`:focus-visible { outline: 2px solid var(--ring); outline-offset: 2px }`（已在 base 层统一）。

## 9. 不要做

- ❌ 在 `.vue` 里写十六进制/oklch 字面量（除固定色板已给的语义用途外）。
- ❌ 引入外部字体/CDN/图标库（图标走 `lib/icons.ts` 内联 SVG）。
- ❌ 新增第三方动画库或与 `main.css` 重复的动效。
- ❌ 改变 `main.css` 里主题文件的 `@import` 顺序（bridge 依赖 tokens 先就位）。
