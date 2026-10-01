<script setup lang="ts">
import { computed, ref } from 'vue'

import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Icon from '@/components/ui/Icon.vue'
import type { BookVolume } from '@/lib/api'
import { tocGroups } from '@/lib/chapterGroups'

/**
 * 目录标签（第 63 期从 `BookDetailView` 抽出）。搜索与折叠状态是这块自己的事，
 * 父级只关心「有没有章节」。
 *
 * 第 85 期三处改动（与阅读器左侧目录栏**共用** `lib/chapterGroups.ts` 的分组口径）：
 * 1. 段名不再把空卷名回落成「目录」—— 无名段由 `groupLabel` 统一叫「正文」，
 *    前后段叫「卷前」/「卷尾」；
 * 2. 折叠记忆的键从「卷名」换成**段 key**：段名会重复（背靠背的两个无名段都叫「正文」），
 *    拿它当 key 会让两段互相串折叠；
 * 3. 无编号条目（楔子 / 番外…）**不渲染序号**，但保留序号列宽，标题才不会参差。
 */
const props = defineProps<{ chapters: BookVolume[] }>()

const chapterQuery = ref('')
const collapsedVolumes = ref<Record<string, boolean>>({})

/** 章节过滤：输入时只切行显隐，不重建列表 */
const groups = computed(() => {
  const q = chapterQuery.value.trim().toLowerCase()
  const all = tocGroups(props.chapters)
  if (!q) return all
  return all
    .map((g) => ({ ...g, items: g.items.filter((c) => c.title.toLowerCase().includes(q)) }))
    .filter((g) => g.items.length > 0)
})

const total = computed(() => groups.value.reduce((s, g) => s + g.items.length, 0))

function toggleVolume(key: string): void {
  collapsedVolumes.value[key] = !collapsedVolumes.value[key]
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

    <Card v-for="g in groups" :key="g.key" padding="none" class="mb-2">
      <button
        type="button"
        class="flex w-full cursor-pointer items-center gap-2.5 px-3.5 py-2.5 text-left"
        :aria-expanded="!collapsedVolumes[g.key]"
        @click="toggleVolume(g.key)"
      >
        <Icon
          name="chev"
          class="h-3.5 w-3.5 text-muted-foreground transition-transform"
          :class="collapsedVolumes[g.key] ? '-rotate-90' : ''"
        />
        <span class="text-[12.5px] font-semibold text-foreground">{{ g.label }}</span>
        <span class="text-[11px] text-muted-foreground tabular-nums">{{ g.items.length }} 章</span>
      </button>

      <div v-show="!collapsedVolumes[g.key]" class="border-t border-border">
        <div
          v-for="(c, ci) in g.items"
          :key="`${g.key}-${ci}`"
          class="flex items-center gap-2.5 border-b border-border/60 px-3.5 py-1.5 last:border-b-0"
          :class="g.headered ? 'pl-6' : ''"
        >
          <span class="w-8 shrink-0 text-[11.5px] text-muted-foreground tabular-nums">{{ c.num ?? '' }}</span>
          <span class="min-w-0 flex-1 truncate text-[12.5px] text-foreground">{{ c.title }}</span>
        </div>
      </div>
    </Card>

    <EmptyState
      v-if="!groups.length"
      icon="search"
      title="没有匹配的章节"
      desc="换个关键词再试，或这本书还没有可用的目录。"
    />
  </div>
</template>
