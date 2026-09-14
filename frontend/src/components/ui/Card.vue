<script setup lang="ts">
/**
 * 卡片容器。BookOrbit 的卡片语言：细边框分层 + 语义 token 上色，不用重阴影。
 * 所有面（部件卡、设置卡、详情面板）共用同一套类串。
 */
withDefaults(
  defineProps<{
    /** 内边距档位：none 由调用方自己控制间距 */
    padding?: 'none' | 'sm' | 'md'
    /** 是否用更弱的底（用于嵌套区） */
    muted?: boolean
  }>(),
  { padding: 'md', muted: false },
)

const PADDING: Record<string, string> = {
  none: '',
  sm: 'p-3',
  md: 'p-4',
}
</script>

<template>
  <div
    class="min-w-0 rounded-lg border border-border shadow-sm"
    :class="[muted ? 'bg-muted' : 'bg-card', PADDING[padding]]"
  >
    <slot />
  </div>
</template>
