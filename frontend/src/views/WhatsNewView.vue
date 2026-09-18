<script setup lang="ts">
import PageHead from '@/components/ui/PageHead.vue'
import Card from '@/components/ui/Card.vue'
import Badge from '@/components/ui/Badge.vue'
import { WHATS_NEW } from '@/data/whatsNew'

/** What's New：静态更新日志（对应上游 Help → What's New）。 */
</script>

<template>
  <div>
    <PageHead title="更新日志" desc="What's New · 本项目新增能力一览" />

    <div class="space-y-4">
      <Card v-for="entry in WHATS_NEW" :key="entry.version" padding="none">
        <div class="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
          <span class="text-[13px] font-semibold text-foreground">{{ entry.title }}</span>
          <Badge tone="accent">{{ entry.version }}</Badge>
          <span class="ml-auto text-[11.5px] text-muted-foreground tabular-nums">{{ entry.date }}</span>
        </div>
        <ul class="space-y-1.5 px-4 py-3">
          <li
            v-for="item in entry.items"
            :key="item"
            class="flex gap-2 text-[12.5px] text-foreground/90"
          >
            <span class="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-primary" />
            <span>{{ item }}</span>
          </li>
        </ul>
      </Card>
    </div>
  </div>
</template>
