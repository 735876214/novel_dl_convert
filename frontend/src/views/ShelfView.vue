<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'

import BookCover from '@/components/ui/BookCover.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import PageHead from '@/components/ui/PageHead.vue'
import { useLibraryStore } from '@/stores/library'

/**
 * 书库落地页：库 / 智能书架 / 收藏夹 三个入口的共同落点。
 * 页头是条目名，右侧标签筛选 chips，下方书卡网格。
 */
const library = useLibraryStore()
const router = useRouter()

const chips = computed(() => ['全部', ...library.allTags])

function pick(tag: string): void {
  library.shelfTag = tag === '全部' ? '' : tag
}
</script>

<template>
  <div>
    <PageHead :title="library.shelfTitle" :desc="`共 ${library.shelfBooks.length} 本`" />

    <div class="mb-4 flex flex-wrap gap-1.5">
      <button
        v-for="tag in chips"
        :key="tag"
        type="button"
        :title="tag"
        class="cursor-pointer rounded-full px-3 py-1 text-[12px] font-medium transition-colors"
        :class="
          (tag === '全部' && !library.shelfTag) || library.shelfTag === tag
            ? 'bg-primary text-primary-foreground'
            : 'bg-muted text-muted-foreground hover:text-foreground'
        "
        @click="pick(tag)"
      >
        {{ tag }}
      </button>
    </div>

    <div
      v-if="library.shelfBooks.length"
      class="grid grid-cols-2 gap-x-4 gap-y-5 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-6 2xl:grid-cols-8"
    >
      <button
        v-for="b in library.shelfBooks"
        :key="b.id"
        type="button"
        class="group cursor-pointer text-left"
        @click="router.push(`/book/${b.id}`)"
      >
        <BookCover :book="b" />
        <div class="mt-2 truncate text-[12.5px] font-medium text-foreground">{{ b.title }}</div>
        <div class="truncate text-[11.5px] text-muted-foreground">{{ b.author }}</div>
      </button>
    </div>

    <EmptyState
      v-else
      icon="library"
      title="这个书架还是空的"
      desc="换个标签看看，或到「探索发现」把书下载进来。"
    />
  </div>
</template>
