<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'

/**
 * 通用浮层菜单壳（第 64 期）：`trigger` 槽 + `panel` 槽 + 面板外观。
 *
 * 本组件**不认识「书」** —— 开合由父组件通过 `open` 传入，本组件只负责
 * 「面板画在哪、什么时候关」。书架的菜单项在 `book/BookActionsMenu.vue`。
 *
 * ## 为什么面板要 Teleport 到 body
 *
 * 面板必须是 `position: fixed`（否则会被两处 `overflow` 裁掉），而 fixed 也不是
 * 万能的：
 *
 * 1. `App.vue` 的内容卡片带 `backdrop-blur-md` + `overflow-hidden` ——
 *    `backdrop-filter` 会成为 **fixed 后代的包含块**，于是 `overflow-hidden` 连
 *    fixed 后代一起裁。挂在页面内怎么定位都出不去。
 * 2. 表格视图的 `<Card class="overflow-x-auto">`：一轴非 `visible` 时另一轴的
 *    `visible` 会计算成 `auto` ⇒ 那个盒子**两轴都裁剪**，行内浮层会被裁在卡片边界上。
 *
 * Teleport 到 body 同时绕开这两条。**这是全仓第一个 Teleport** —— 代价是 spec 里
 * 断言面板要查 `document.body.querySelector(...)`，`wrapper.find(...)` 找不到它。
 *
 * ## 为什么要手动定位（而不是 CSS 相对定位）
 *
 * 面板既然在 body 下，就与触发器不在同一棵树里，`absolute` 无从谈起。用
 * `getBoundingClientRect()` 换算成视口坐标，是这条路上唯一说得通的做法。
 */
const props = withDefaults(
  defineProps<{
    open: boolean
    /** 面板贴住触发器的哪一边。默认右对齐（⋮ 在卡片右下角，面板往左展开） */
    align?: 'right' | 'left'
    /** 追加到面板上的类（宽度之类） */
    panelClass?: string
    /** 追加到触发器包裹元素上的类（网格卡用它把 ⋮ 绝对定位到封面角上） */
    triggerClass?: string
  }>(),
  { align: 'right', panelClass: '', triggerClass: '' },
)

const emit = defineEmits<{ (e: 'toggle'): void; (e: 'close'): void }>()

const trigger = ref<HTMLElement | null>(null)
const panel = ref<HTMLElement | null>(null)
/** 视口坐标（面板是 fixed，直接用 top/right 即可，不需要知道面板自身宽度） */
const pos = ref<{ top: number; right?: number; left?: number }>({ top: 0, right: 0 })

/** 与触发器 / 视口边缘留的缝，px */
const GAP = 6
const EDGE = 8

function place(): void {
  const el = trigger.value
  if (!el) return
  const r = el.getBoundingClientRect()
  const h = panel.value?.offsetHeight ?? 0
  let top = r.bottom + GAP
  // 下方放不下就翻到上方：⋮ 在封面右下角，靠屏幕底部的卡片必然会遇到。
  // `h` 为 0（尚未布局 / 测试环境）时不翻 —— 猜一个高度比不翻更糟。
  if (h > 0 && top + h > window.innerHeight - EDGE) {
    const above = r.top - h - GAP
    top = above >= EDGE ? above : Math.max(EDGE, window.innerHeight - h - EDGE)
  }
  if (props.align === 'left') {
    pos.value = { top, left: Math.max(EDGE, r.left) }
  } else {
    pos.value = { top, right: Math.max(EDGE, window.innerWidth - r.right) }
  }
}

const panelStyle = () => ({
  top: `${pos.value.top}px`,
  ...(pos.value.left !== undefined
    ? { left: `${pos.value.left}px` }
    : { right: `${pos.value.right}px` }),
})

/**
 * 滚动 / 缩放时**直接关掉**，而不是跟着重算。
 *
 * 「跟着重算」要监听所有祖先滚动容器（本页就有整页滚动与表格卡横滚两处），漏一个
 * 就会看到面板浮在离触发器很远的地方 —— 那比关掉更让人困惑。`capture: true` 是为了
 * 连**容器内部**的滚动（表格卡横滚）也收得到：scroll 事件不冒泡，但会捕获。
 */
function onScroll(): void {
  emit('close')
}
function onResize(): void {
  emit('close')
}

function bind(on: boolean): void {
  const m = on ? 'addEventListener' : 'removeEventListener'
  window[m]('scroll', onScroll, true)
  window[m]('resize', onResize)
}

watch(
  () => props.open,
  async (v) => {
    bind(v)
    if (!v) return
    await nextTick()
    place()
  },
)

onBeforeUnmount(() => bind(false))
</script>

<template>
  <!--
    单根元素（触发器包裹 + Teleport 在它内部）—— Teleport 本身不产生 DOM，
    所以这里仍然只有一个真实根节点，父组件传进来的 class 能正常落到它上面。
    `@click.stop`：点触发器绝不冒泡到 document / 外层卡片行 ——
    后者会让「点 ⋮」变成「打开这本书」，而前者会把**刚打开**的面板立刻关掉。
  -->
  <span
    ref="trigger"
    class="inline-flex"
    :class="triggerClass"
    data-book-menu
    @click.stop="emit('toggle')"
  >
    <slot name="trigger" />
    <Teleport to="body">
      <div
        v-if="open"
        ref="panel"
        role="menu"
        data-book-menu
        data-book-menu-panel
        class="fixed z-50 max-h-[70vh] w-[min(15rem,88vw)] overflow-y-auto overscroll-contain rounded-[var(--shell-radius)] border border-[var(--shell-border)] bg-[var(--shell-surface)] py-1 shadow-2xl backdrop-blur-md backdrop-saturate-150"
        :class="panelClass"
        :style="panelStyle()"
        @click.stop
      >
        <slot name="panel" />
      </div>
    </Teleport>
  </span>
</template>
