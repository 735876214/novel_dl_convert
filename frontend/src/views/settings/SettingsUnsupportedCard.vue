<script setup lang="ts">
import Card from '@/components/ui/Card.vue'

/**
 * 「上游还有、本项目未支持」只读卡片。
 *
 * 已实现真实功能的页面（Theme / eBook / Profile 等）用它补齐同页的上游条目，
 * 保证「全部对齐（含占位）」——既不做成空页面，也不伪造交互。
 */
withDefaults(
  defineProps<{
    /** 上游页名（英文原名） */
    label: string
    /** 上游页内分组标题 */
    groups?: string[]
    /** 上游有、本项目未支持的设置项 */
    items: string[]
    /** 补充说明 */
    note?: string
  }>(),
  { groups: () => [], note: '' },
)
</script>

<template>
  <Card padding="none" class="mt-4">
    <div class="border-b border-border px-4 py-3">
      <div class="flex flex-wrap items-baseline gap-2">
        <h3 class="text-[13px] font-semibold text-foreground">上游还有、本项目未支持</h3>
        <span class="font-mono text-[11px] text-muted-foreground">{{ label }}</span>
      </div>
      <p class="mt-1 text-[11.5px] leading-relaxed text-muted-foreground">
        {{ note || '以下条目在上游该页存在，本项目未实现，仅作只读对照。' }}
      </p>
    </div>

    <div v-if="groups.length" class="border-b border-border px-4 py-2.5">
      <div class="flex flex-wrap gap-1.5">
        <span
          v-for="g in groups"
          :key="g"
          class="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground"
        >{{ g }}</span>
      </div>
    </div>

    <div
      v-for="(it, i) in items"
      :key="i"
      class="flex items-start gap-3 border-b border-border/60 px-4 py-2 last:border-b-0"
    >
      <span class="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-muted-foreground/50" />
      <span class="min-w-0 flex-1 text-[12.5px] leading-relaxed text-foreground/90">{{ it }}</span>
      <span class="shrink-0 text-[10.5px] text-muted-foreground">未支持</span>
    </div>
  </Card>
</template>
