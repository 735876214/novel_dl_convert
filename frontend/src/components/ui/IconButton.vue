<script setup lang="ts">
import { computed } from 'vue'

/**
 * 顶栏图标按钮（第 65 期）。
 *
 * ## 为什么要有这个组件
 *
 * 在它之前，那串按钮类**被逐字复制了三份**（`AppHeader.vue` / `NotificationBell.vue`
 * / `AppearanceMenu.vue` 各自一份 `ICON_BTN` 常量）。第 65 期要在同一行里再加
 * 四个入口（工具 / 阅读记录 / 阅读活动 / 成就）并统一改成圆形 —— 七份复制必然漂移，
 * 于是把「外观 + 气泡 + 角标」这三件事收到一处定义。
 *
 * ## 三个约定
 *
 * 1. **整行统一圆形描边**（用户口径：「整行统一圆形」）。基准是
 *    `DashboardSettingsSheet.vue` 里那个全仓唯一的圆形描边按钮。
 * 2. **不写原生 `title`**：有了自绘气泡，两个提示会一起冒出来。
 *    无障碍信息由 `aria-label` 承担（气泡本身 `aria-hidden`）。
 * 3. 气泡**右对齐**而不是居中：这一行的最右端是头像，居中的气泡会越过卡片
 *    右边缘，被外壳的 `overflow-x: clip` 裁掉半截。
 */
const props = defineProps<{
  /** `aria-label`，同时是气泡的默认文案 */
  label: string
  /** 气泡文案（默认取 `label`）。用于「当前值」这类要补一句的情况，如「外观（当前：深色）」 */
  tooltip?: string
  /** 当前态：主色底 + 主色字（浮层打开时也用它） */
  active?: boolean
  /** `aria-expanded`。不传则整个属性不输出（非浮层触发器的按钮不该有它） */
  expanded?: boolean
  /** 数字角标；`null` / `undefined` / `0` / 空串 一律不渲染 */
  badge?: string | number | null
}>()

const emit = defineEmits<{ (e: 'click', ev: MouseEvent): void }>()

/**
 * ⚠️ 关键：`bg-foreground text-background` 是**反色**（浅色主题下就是图二那个黑气泡），
 * 用的是 token 而不是写死 `black`。
 *
 * 写死黑的话，深色主题下气泡会贴在深色卡片上 —— 一团看不见的黑。而 `--foreground`
 * 在深色主题下翻成近白（`tokens.css` 两个主题块各自定义），反色自动成立。
 * 同理不能写 `bg-primary`：`--primary` 在深色下也会翻成近白，那是「主色」不是「反色」。
 */
const BUBBLE =
  'pointer-events-none absolute top-[calc(100%+0.375rem)] right-0 z-50 rounded-md bg-foreground px-2 py-1 text-[11px] whitespace-nowrap text-background opacity-0 transition-opacity group-hover:opacity-100'

const BTN =
  'relative grid h-[2.0625rem] w-[2.0625rem] cursor-pointer place-items-center rounded-full border border-border text-muted-foreground transition-colors hover:bg-muted hover:text-foreground'

const ACTIVE = 'bg-[var(--shell-accent-tint)] text-primary hover:text-primary'

/** 角标文案：三位数以上折成 `99+`（否则会把按钮撑变形） */
const badgeText = computed(() => {
  const b = props.badge
  if (b === null || b === undefined || b === '' || b === 0 || b === '0') return ''
  const n = typeof b === 'number' ? b : Number(b)
  return Number.isFinite(n) && n > 99 ? '99+' : String(b)
})
</script>

<template>
  <!-- `data-icon-button` 供 spec 计数（照 `[data-dock-row]` 的先例）：这一行有几个
       按钮、是不是都圆形，是本期用户口径（「整行统一圆形」）的判据，
       靠类名选择器去数太脆（类一漂移，断言就静默失效）。 -->
  <span class="group relative inline-flex" data-icon-button>
    <button
      type="button"
      :class="[BTN, active ? ACTIVE : '']"
      :aria-label="label"
      :aria-expanded="expanded"
      @click="emit('click', $event)"
    >
      <slot />
      <span
        v-if="badgeText"
        class="pointer-events-none absolute -top-0.5 -right-0.5 min-w-[1rem] rounded-full bg-destructive px-1 text-[9.5px] leading-4 font-semibold text-white tabular-nums"
      >
        {{ badgeText }}
      </span>
    </button>

    <span :class="BUBBLE" aria-hidden="true">{{ tooltip ?? label }}</span>
  </span>
</template>
