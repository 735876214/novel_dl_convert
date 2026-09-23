<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import BookCover from '@/components/ui/BookCover.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Icon from '@/components/ui/Icon.vue'
import PageHead from '@/components/ui/PageHead.vue'
import { api, type CollectionDetail } from '@/lib/api'
import { useCollectionsStore } from '@/stores/collections'

/** 收藏夹详情：夹内书目，可移出或整夹删除。 */
const route = useRoute()
const router = useRouter()
const collections = useCollectionsStore()

const cid = computed(() => Number(route.params.id))
const detail = ref<CollectionDetail | null>(null)
const loading = ref(true)
/** 加载失败信息：失败不能退化成「这个收藏夹还是空的」。 */
const error = ref('')

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    detail.value = await api.collectionDetail(cid.value)
  } catch (e) {
    detail.value = null
    error.value = e instanceof Error ? e.message : '加载失败'
  }
  loading.value = false
}

onMounted(load)
watch(cid, load)

async function remove(bookId: string): Promise<void> {
  try {
    await api.removeFromCollection(cid.value, bookId)
  } catch {
    /* ignore */
  }
  await load()
  await collections.load(true)
}

async function removeCollection(): Promise<void> {
  const name = detail.value?.name ?? '该收藏夹'
  if (!window.confirm(`删除收藏夹「${name}」？（仅删除收藏，不影响书籍文件）`)) return
  try {
    await collections.remove(cid.value)
  } catch {
    /* ignore */
  }
  router.push('/collections')
}
</script>

<template>
  <div>
    <button
      type="button"
      class="mb-4 flex cursor-pointer items-center gap-1 text-[12px] text-muted-foreground transition-colors hover:text-primary"
      @click="router.push('/collections')"
    >
      <Icon name="arrowLeft" class="h-3.5 w-3.5" />全部收藏夹
    </button>

    <div class="flex items-start justify-between gap-3">
      <PageHead :title="detail?.name ?? '收藏夹'" :desc="`共 ${detail?.books.length ?? 0} 本`" />
      <Button v-if="detail" variant="danger" size="sm" @click="removeCollection">
        <Icon name="trash" class="h-3.5 w-3.5" />删除收藏夹
      </Button>
    </div>

    <div v-if="loading" class="py-20 text-center text-[13px] text-muted-foreground">加载中…</div>

    <!-- 加载失败：可重试的错误态（不与「这个收藏夹还是空的」空态混淆） -->
    <Card v-else-if="error" padding="sm" class="mb-4">
      <div class="flex flex-wrap items-center gap-2 text-[12.5px] text-destructive">
        <Icon name="alert" class="h-3.5 w-3.5 shrink-0" />
        <span>收藏夹加载失败：{{ error }}</span>
        <Button size="sm" variant="secondary" class="ml-auto" @click="load">重试</Button>
      </div>
    </Card>

    <div
      v-else-if="detail && detail.books.length"
      class="grid grid-cols-2 gap-x-4 gap-y-5 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-6 2xl:grid-cols-8"
    >
      <div v-for="b in detail.books" :key="b.id" class="group relative">
        <button
          type="button"
          class="w-full cursor-pointer text-left"
          @click="router.push(`/book/${b.id}`)"
        >
          <BookCover :book="b" />
          <div class="mt-2 truncate text-[12.5px] font-medium text-foreground">{{ b.title }}</div>
          <div class="truncate text-[11.5px] text-muted-foreground">{{ b.author }}</div>
        </button>
        <button
          type="button"
          class="absolute top-1.5 right-1.5 cursor-pointer rounded-md bg-black/55 p-1 text-white opacity-0 transition-opacity group-hover:opacity-100"
          title="移出收藏夹"
          @click.stop="remove(b.id)"
        >
          <Icon name="trash" class="h-3.5 w-3.5" />
        </button>
      </div>
    </div>

    <EmptyState
      v-else
      icon="star"
      title="这个收藏夹还是空的"
      desc="到书籍详情页点「加入收藏」把书放进来。"
    />
  </div>
</template>
