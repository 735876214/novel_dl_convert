<script setup lang="ts">
import type { DialogRootEmits, DialogRootProps } from 'reka-ui'
import { DialogRoot, useForwardPropsEmits } from 'reka-ui'

/**
 * 抽屉根（第 90 期，逐字移植 BookOrbit 的 `ui/sheet`，基座是 reka-ui 的 Dialog）。
 *
 * 它替项目管了四件事，都不是可有可无的：
 *   · `Teleport to body` —— 见 `SheetContent` 的说明（外壳的 `backdrop-blur` 会让
 *     `position: fixed` 的后代以外壳为包含块而被裁）；
 *   · 遮罩点击关闭；· `Esc` 关闭；· 打开期间锁滚动 + 焦点陷阱；
 *   · `role="dialog"` + `aria-modal`（无障碍的判据，不是装饰）。
 */
const props = defineProps<DialogRootProps>()
const emits = defineEmits<DialogRootEmits>()

const forwarded = useForwardPropsEmits(props, emits)
</script>

<template>
  <DialogRoot v-slot="slotProps" data-slot="sheet" v-bind="forwarded">
    <slot v-bind="slotProps" />
  </DialogRoot>
</template>
