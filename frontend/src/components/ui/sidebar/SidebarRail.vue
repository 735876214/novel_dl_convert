<script setup lang="ts">
import type { HTMLAttributes } from 'vue'
import { onBeforeUnmount, ref } from 'vue'

import { cn } from '@/lib/utils'
import { useSidebar } from './utils'

/**
 * 侧栏右缘的「拉手」（第 90 期，逐字移植 BookOrbit 的 `ui/sidebar/SidebarRail.vue`）。
 *
 * 一个控件同时是**两种**操作，靠 3px 位移阈值区分：
 *   · 按下就走 ≥3px ⇒ **拖拽调宽**（224–480px，防抖落盘）；
 *   · 按下不挪就抬起 ⇒ **点击开合**侧栏。
 *
 * ⚠️ 阈值不能用「有没有 move 事件」代替：鼠标按下时手抖 1px 就发一次
 * `pointermove`，那样永远点不出「开合」。3px 是上游的经验值。
 *
 * ⚠️ 监听器**只在拖拽期间**挂到 `window`：常驻的话整页每秒都在跑一个没人用的
 * handler；而且指针拖出窗口后事件仍在 `window` 上，松手不会丢。
 *
 * ⚠️ 折叠态下**不**允许调宽（`isResizeGesture = state === 'expanded'`）：图标条
 * 只有 48px，在那儿拖动等于「一边改宽度一边看不见结果」，松手才发现宽度变了。
 * 折叠态点击 = 先展开，用户在展开态再拖。
 */
const props = defineProps<{
  class?: HTMLAttributes['class']
}>()

const { toggleSidebar, setWidth, widthPx, state } = useSidebar()

/** 按下后挪动超过这个距离才算「拖拽」，否则按「点击开合」处理 */
const DRAG_THRESHOLD_PX = 3

const activePointerId = ref<number | null>(null)
const dragStartX = ref(0)
const dragStartWidth = ref(0)
const dragSide = ref<'left' | 'right'>('left')
const isResizeGesture = ref(false)
const didDrag = ref(false)

/** 从 DOM 上读侧别（而不是从 props）：同一个 Rail 组件左右栏都能用，真值只有一处 */
function resolveSide(target: EventTarget | null): 'left' | 'right' {
  const element = target instanceof HTMLElement ? target : null
  const side = element?.closest('[data-side]')?.getAttribute('data-side')
  return side === 'right' ? 'right' : 'left'
}

function onPointerMove(event: PointerEvent) {
  if (activePointerId.value === null || event.pointerId !== activePointerId.value) return
  if (!isResizeGesture.value) return

  const deltaX = event.clientX - dragStartX.value
  if (Math.abs(deltaX) >= DRAG_THRESHOLD_PX) didDrag.value = true

  // 右栏的「往外拖」是向左，所以位移取反
  const nextWidth = dragSide.value === 'left' ? dragStartWidth.value + deltaX : dragStartWidth.value - deltaX
  setWidth(nextWidth)
}

function cleanupDragListeners() {
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('pointerup', onPointerEnd)
  window.removeEventListener('pointercancel', onPointerEnd)
}

function resetDragState() {
  activePointerId.value = null
  isResizeGesture.value = false
  didDrag.value = false
}

function onPointerEnd(event: PointerEvent) {
  if (activePointerId.value === null || event.pointerId !== activePointerId.value) return

  // `pointercancel`（系统接管手势）绝不当作点击：用户没打算开合侧栏
  const shouldToggleSidebar = event.type === 'pointerup' && !didDrag.value
  cleanupDragListeners()
  resetDragState()

  if (shouldToggleSidebar) toggleSidebar()
}

function onPointerDown(event: PointerEvent) {
  if (event.button !== 0) return

  activePointerId.value = event.pointerId
  dragStartX.value = event.clientX
  dragStartWidth.value = widthPx.value
  dragSide.value = resolveSide(event.currentTarget)
  isResizeGesture.value = state.value === 'expanded'
  didDrag.value = false

  window.addEventListener('pointermove', onPointerMove)
  window.addEventListener('pointerup', onPointerEnd)
  window.addEventListener('pointercancel', onPointerEnd)
  // 拦住原生拖拽/选中，否则按住拉手会把整块内容拖成蓝色选区
  event.preventDefault()
}

onBeforeUnmount(() => {
  cleanupDragListeners()
  resetDragState()
})
</script>

<template>
  <button
    data-sidebar="rail"
    data-slot="sidebar-rail"
    type="button"
    aria-label="切换侧边栏"
    title="点击展开/收起，拖动调整宽度"
    :tabindex="-1"
    :class="
      cn(
        // 16px 命中区骑在卡片右缘上（`-right-4` 再 `-translate-x-1/2` ⇒ 各探出 8px），
        // 2px 高亮线只在悬停时出现 —— 平时侧栏看起来仍然只有一张干净的卡片。
        'absolute inset-y-0 z-20 hidden w-4 -translate-x-1/2 transition-all ease-linear after:absolute after:top-0 after:bottom-0 after:left-1/2 after:w-[2px] after:rounded-full hover:after:bg-sidebar-border group-data-[side=left]:-right-4 group-data-[side=right]:left-0 group-data-[variant=floating]:after:top-3 group-data-[variant=floating]:after:bottom-3 sm:flex',
        'in-data-[side=left]:cursor-col-resize in-data-[side=right]:cursor-col-resize',
        '[[data-side=left][data-state=collapsed]_&]:cursor-e-resize [[data-side=right][data-state=collapsed]_&]:cursor-w-resize',
        props.class,
      )
    "
    @pointerdown="onPointerDown"
  >
    <slot />
  </button>
</template>
