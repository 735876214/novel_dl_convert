<script setup lang="ts">
/** 小徽章：状态与标签。accent 用主色系，其余用语义色。 */
withDefaults(
  defineProps<{
    tone?: 'neutral' | 'accent' | 'ok' | 'warn' | 'err'
    /** 胶囊形（用于筛选 chips） */
    pill?: boolean
  }>(),
  { tone: 'neutral', pill: false },
)

const TONE: Record<string, string> = {
  neutral: 'bg-muted text-muted-foreground',
  accent: 'bg-primary text-primary-foreground',
  ok: 'bg-success/14 text-success',
  warn: 'bg-warning/14 text-warning',
  err: 'bg-destructive/14 text-destructive',
}
</script>

<template>
  <span
    class="inline-flex shrink-0 items-center gap-1 rounded font-medium whitespace-nowrap"
    :class="[TONE[tone], pill ? 'rounded-full px-3 py-1 text-[12px]' : 'px-1.5 py-0.5 text-[11px]']"
  >
    <slot />
  </span>
</template>
