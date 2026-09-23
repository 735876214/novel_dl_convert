<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import Card from '@/components/ui/Card.vue'
import PageHead from '@/components/ui/PageHead.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import { api } from '@/lib/api'
import { WHATS_NEW, type WhatsNewTag } from '@/data/whatsNew'

/** What's New：静态更新日志（对应上游 Help → What's New）。 */

/** 当前版本（后端 /health 下发，全站唯一真值源；不再在前端手写版本号） */
const version = ref('')

/** 上次访问时已看到的最新日期（localStorage 持久化，确定性、非随机）。 */
const SEEN_KEY = 'whatsnew:last-seen'
const lastSeen = ref<string | null>(localStorage.getItem(SEEN_KEY))

/** 该条目是否「自上次访问以来新增」：日期严格晚于 lastSeen 才算新；「—」不参与。 */
function isNew(date: string): boolean {
  if (date === '—') return false
  if (lastSeen.value === null) return true
  return date > lastSeen.value
}

/** 分类标签 → 低饱和 chip 配色（全类串静态写出，避免被 tailwind 摇树）。 */
const TAG_CLASS: Record<WhatsNewTag, string> = {
  新功能: 'bg-primary/10 text-primary',
  优化: 'bg-emerald-500/10 text-emerald-600',
  修复: 'bg-amber-500/10 text-amber-600',
  生态: 'bg-indigo-500/10 text-indigo-600',
}

const isEmpty = computed(() => WHATS_NEW.length === 0)

onMounted(() => {
  api
    .health()
    .then((h) => (version.value = h.version))
    .catch(() => {})
  // 记录本次已看到的最新有效日期（取最大），下次访问据此判定「新条目」
  const valid = WHATS_NEW.map((e) => e.date)
    .filter((d) => d !== '—')
    .sort()
  const latest = valid.length ? valid[valid.length - 1] : null
  if (latest) localStorage.setItem(SEEN_KEY, latest)
})
</script>

<template>
  <div>
    <PageHead title="更新日志" :desc="`What's New · 当前版本 ${version || '…'}`" />

    <EmptyState
      v-if="isEmpty"
      icon="bell"
      title="暂无更新记录"
      desc="新功能上线后会出现在这里。"
    />

    <div v-else class="space-y-4">
      <Card
        v-for="entry in WHATS_NEW"
        :key="entry.date + entry.title"
        padding="none"
        :class="isNew(entry.date) ? 'border-l-2 border-primary' : ''"
      >
        <div class="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
          <span
            class="rounded-full border border-primary/40 px-2 py-0.5 text-[11px] font-medium text-primary"
          >{{ entry.date }}</span>
          <span class="text-[13px] font-semibold text-foreground">{{ entry.title }}</span>
          <span
            class="ml-auto rounded-full px-2 py-0.5 text-[11px] font-medium"
            :class="TAG_CLASS[entry.tag]"
          >{{ entry.tag }}</span>
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
