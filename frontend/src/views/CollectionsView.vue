<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Icon from '@/components/ui/Icon.vue'
import PageHead from '@/components/ui/PageHead.vue'
import { useCollectionsStore } from '@/stores/collections'

/** 收藏夹总览：自建收藏夹的增删与进入。 */
const router = useRouter()
const collections = useCollectionsStore()

const draft = ref('')
const error = ref('')
const creating = ref(false)

onMounted(() => collections.load(true))

async function create(): Promise<void> {
  const name = draft.value.trim()
  if (!name) return
  error.value = ''
  creating.value = true
  try {
    await collections.create(name)
    draft.value = ''
  } catch (e) {
    error.value = e instanceof Error ? e.message : '创建失败'
  } finally {
    creating.value = false
  }
}

async function remove(id: number, name: string): Promise<void> {
  if (!window.confirm(`删除收藏夹「${name}」？（仅删除收藏，不影响书籍文件）`)) return
  try {
    await collections.remove(id)
  } catch {
    /* ignore */
  }
}
</script>

<template>
  <div>
    <PageHead title="收藏夹" :desc="`共 ${collections.items.length} 个收藏夹`" />

    <Card class="mb-5">
      <div class="flex flex-wrap items-center gap-2">
        <input
          v-model="draft"
          type="text"
          placeholder="新建收藏夹名称…"
          class="h-8 min-w-[12rem] flex-1 rounded-md border border-border bg-muted px-2.5 text-[12.5px] text-foreground outline-none placeholder:text-muted-foreground focus:border-ring focus:bg-card"
          @keyup.enter="create"
        >
        <Button variant="primary" :disabled="creating || !draft.trim()" @click="create">
          <Icon name="plus" class="h-3.5 w-3.5" />新建
        </Button>
      </div>
      <p v-if="error" class="mt-2 text-[11.5px] text-destructive">{{ error }}</p>
    </Card>

    <div v-if="collections.items.length" class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
      <Card
        v-for="c in collections.items"
        :key="c.id"
        class="cursor-pointer transition-colors hover:border-ring"
        @click="router.push(`/collections/${c.id}`)"
      >
        <div class="flex items-center gap-3">
          <span class="grid h-9 w-9 shrink-0 place-items-center rounded-md bg-muted text-muted-foreground">
            <Icon name="star" class="h-4 w-4" />
          </span>
          <div class="min-w-0 flex-1">
            <div class="truncate text-[13px] font-medium text-foreground">{{ c.name }}</div>
            <div class="text-[11.5px] text-muted-foreground tabular-nums">{{ c.count }} 本</div>
          </div>
          <button
            type="button"
            class="shrink-0 cursor-pointer rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-destructive"
            title="删除收藏夹"
            @click.stop="remove(c.id, c.name)"
          >
            <Icon name="trash" class="h-3.5 w-3.5" />
          </button>
        </div>
      </Card>
    </div>

    <EmptyState
      v-else
      icon="star"
      title="还没有收藏夹"
      desc="在上方输入名称新建一个，或在书籍详情页把书加入收藏。"
    />
  </div>
</template>
