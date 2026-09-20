<script setup lang="ts">
import { onMounted, ref } from 'vue'

import Card from '@/components/ui/Card.vue'
import PageHead from '@/components/ui/PageHead.vue'
import { api } from '@/lib/api'
import { WHATS_NEW } from '@/data/whatsNew'

/** What's New：静态更新日志（对应上游 Help → What's New）。 */

/** 当前版本（后端 /health 下发，全站唯一真值源；不再在前端手写版本号） */
const version = ref('')
onMounted(() => {
  api
    .health()
    .then((h) => (version.value = h.version))
    .catch(() => {})
})
</script>

<template>
  <div>
    <PageHead title="更新日志" :desc="`What's New · 当前版本 ${version || '…'}`" />

    <div class="space-y-4">
      <Card v-for="entry in WHATS_NEW" :key="entry.date + entry.title" padding="none">
        <div class="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
          <span class="text-[13px] font-semibold text-foreground">{{ entry.title }}</span>
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
