<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import BookCover from '@/components/ui/BookCover.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Icon from '@/components/ui/Icon.vue'
import PageHead from '@/components/ui/PageHead.vue'
import { api, type BookCard } from '@/lib/api'

/** 作者详情：该作者名下的全部书目。 */
const route = useRoute()
const router = useRouter()
const name = computed(() => String(route.params.name))
const books = ref<BookCard[]>([])
const loading = ref(true)

async function load(): Promise<void> {
  loading.value = true
  try {
    books.value = (await api.authorDetail(name.value)).books
  } catch {
    books.value = []
  }
  loading.value = false
}

onMounted(load)
watch(name, load)
</script>

<template>
  <div>
    <button
      type="button"
      class="mb-4 flex cursor-pointer items-center gap-1 text-[12px] text-muted-foreground transition-colors hover:text-primary"
      @click="router.push('/authors')"
    >
      <Icon name="arrowLeft" class="h-3.5 w-3.5" />全部作者
    </button>

    <PageHead :title="name" :desc="`共 ${books.length} 本`" />

    <div v-if="loading" class="py-20 text-center text-[13px] text-muted-foreground">加载中…</div>

    <div
      v-else-if="books.length"
      class="grid grid-cols-2 gap-x-4 gap-y-5 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-6 2xl:grid-cols-8"
    >
      <button
        v-for="b in books"
        :key="b.id"
        type="button"
        class="group cursor-pointer text-left"
        @click="router.push(`/book/${b.id}`)"
      >
        <BookCover :book="b" />
        <div class="mt-2 truncate text-[12.5px] font-medium text-foreground">{{ b.title }}</div>
        <div class="truncate text-[11.5px] text-muted-foreground">{{ b.series || '独立作品' }}</div>
      </button>
    </div>

    <EmptyState v-else icon="users" title="这位作者名下的书被移除了" desc="书目可能已不在导出目录。" />
  </div>
</template>
