<script setup lang="ts">
import { computed, ref } from 'vue'

import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Icon from '@/components/ui/Icon.vue'
import type { BookVolume } from '@/lib/api'

/**
 * 目录标签（第 63 期从 `BookDetailView` 抽出）。搜索与折叠状态是这块自己的事，
 * 父级只关心「有没有章节」。
 */
const props = defineProps<{ chapters: BookVolume[] }>()

const chapterQuery = ref('')
const collapsedVolumes = ref<Record<string, boolean>>({})

/** 章节过滤：输入时只切行显隐，不重建列表 */
const volumes = computed(() => {
  const q = chapterQuery.value.trim().toLowerCase()
  if (!q) return props.chapters
  return props.chapters
    .map((v) => ({ ...v, chapters: v.chapters.filter((c) => c.title.toLowerCase().includes(q)) }))
    .filter((v) => v.chapters.length > 0)
})

const total = computed(() => volumes.value.reduce((s, v) => s + v.chapters.length, 0))

function toggleVolume(name: string): void {
  collapsedVolumes.value[name] = !collapsedVolumes.value[name]
}
</script>

<template>
  <div>
    <div class="mb-3 flex items-center gap-2.5">
      <div class="relative max-w-[22rem] flex-1">
        <Icon
          name="search"
          class="pointer-events-none absolute top-1/2 left-2.5 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground"
        />
        <input
          v-model="chapterQuery"
          type="text"
          placeholder="搜索章节…"
          aria-label="搜索章节"
          class="h-8 w-full rounded-md border border-border bg-muted pr-2.5 pl-8 text-[12.5px] text-foreground outline-none placeholder:text-muted-foreground focus:border-ring focus:bg-card"
        >
      </div>
      <span class="text-[11.5px] text-muted-foreground tabular-nums">共 {{ total }} 章</span>
    </div>

    <Card v-for="v in volumes" :key="v.volume" padding="none" class="mb-2">
      <button
        type="button"
        class="flex w-full cursor-pointer items-center gap-2.5 px-3.5 py-2.5 text-left"
        @click="toggleVolume(v.volume)"
      >
        <Icon
          name="chev"
          class="h-3.5 w-3.5 text-muted-foreground transition-transform"
          :class="collapsedVolumes[v.volume] ? '-rotate-90' : ''"
        />
        <span class="text-[12.5px] font-semibold text-foreground">{{ v.volume || '目录' }}</span>
        <span class="text-[11px] text-muted-foreground tabular-nums">{{ v.chapters.length }} 章</span>
      </button>

      <div v-show="!collapsedVolumes[v.volume]" class="border-t border-border">
        <div
          v-for="c in v.chapters"
          :key="c.num"
          class="flex items-center gap-2.5 border-b border-border/60 px-3.5 py-1.5 last:border-b-0"
        >
          <span class="w-8 shrink-0 text-[11.5px] text-muted-foreground tabular-nums">{{ c.num }}</span>
          <span class="min-w-0 flex-1 truncate text-[12.5px] text-foreground">{{ c.title }}</span>
        </div>
      </div>
    </Card>

    <EmptyState
      v-if="!volumes.length"
      icon="search"
      title="没有匹配的章节"
      desc="换个关键词再试，或这本书还没有可用的目录。"
    />
  </div>
</template>
