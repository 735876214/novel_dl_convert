<script setup lang="ts">
import { computed } from 'vue'
import { getActivePinia } from 'pinia'

import { iconPath } from '@/lib/icons'
import { useCustomIconsStore } from '@/stores/customIcons'

const props = withDefaults(
  defineProps<{
    name: string
    /** 额外 class，用于控制尺寸与颜色 */
    class?: string
  }>(),
  { class: '' },
)

// 组件测试可能在没有 Pinia 的树上单独挂 Icon（历史上它零依赖）；没有实例时只走内置表。
const custom = getActivePinia() ? useCustomIconsStore() : null

// 自定义图标由 App 登录后统一加载；图标组件本身不发请求（否则每个图标实例都会探测一次，
// 组件测试里也会因为没桩到 api 而爆）。
const path = computed(() => (custom ? custom.pathOf(props.name) : '') || iconPath(props.name))
</script>

<template>
  <!--
    图标 path 来自内部常量表（lib/icons.ts），非用户输入，因此 v-html 是安全的。
    尺寸在 CSS 里由 .nav-item svg / .tb-icon svg 等父级规则控制，与 v2 一致。
  -->
  <svg
    :class="props.class"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.75"
    stroke-linecap="round"
    stroke-linejoin="round"
    v-html="path"
  />
</template>
