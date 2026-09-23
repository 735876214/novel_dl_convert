<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import BookCover from '@/components/ui/BookCover.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Icon from '@/components/ui/Icon.vue'
import PageHead from '@/components/ui/PageHead.vue'
import { useCollectionsStore } from '@/stores/collections'

/** 收藏夹总览：自建收藏夹的增删改与进入。 */
const router = useRouter()
const collections = useCollectionsStore()

const draft = ref('')
const error = ref('')
const creating = ref(false)

/** 行内重命名：正在编辑的收藏夹 id 与输入框内容 */
const editingId = ref<number | null>(null)
const editName = ref('')
const renameError = ref('')

onMounted(() => collections.load(true))

function fmtDate(sec: number): string {
  if (!sec) return '—'
  const d = new Date(sec * 1000)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

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

function startRename(id: number, name: string): void {
  editingId.value = id
  editName.value = name
  renameError.value = ''
}

function cancelRename(): void {
  editingId.value = null
  editName.value = ''
  renameError.value = ''
}

async function commitRename(id: number): Promise<void> {
  const name = editName.value.trim()
  if (!name) return
  renameError.value = ''
  try {
    await collections.rename(id, name)
    cancelRename()
  } catch (e) {
    renameError.value = e instanceof Error ? e.message : '重命名失败'
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
        class="transition-colors hover:border-ring"
      >
        <div class="flex items-center gap-3">
          <!-- 首书封面预览（无成员时回退星标占位） -->
          <div class="h-16 w-12 shrink-0 overflow-hidden rounded-md bg-muted">
            <BookCover
              v-if="c.first_book_id"
              :book="{ id: c.first_book_id, title: c.name, c1: '', c2: '', has_cover: c.first_book_has_cover }"
              :interactive="false"
              :show-title="false"
            />
            <div v-else class="grid h-full w-full place-items-center text-muted-foreground">
              <Icon name="star" class="h-5 w-5" />
            </div>
          </div>

          <div class="min-w-0 flex-1" @click="router.push(`/collections/${c.id}`)">
            <!-- 行内重命名 -->
            <input
              v-if="editingId === c.id"
              v-model="editName"
              type="text"
              class="w-full rounded-md border border-ring bg-card px-2 py-1 text-[13px] font-medium text-foreground outline-none"
              @keyup.enter="commitRename(c.id)"
              @keyup.esc="cancelRename"
              @click.stop
            >
            <div
              v-else
              class="cursor-pointer truncate text-[13px] font-medium text-foreground"
            >{{ c.name }}</div>
            <div class="mt-0.5 text-[11.5px] text-muted-foreground tabular-nums">
              {{ c.count }} 本 · 最后修改 {{ fmtDate(c.updated_at) }}
            </div>
            <p v-if="editingId === c.id && renameError" class="mt-1 text-[11px] text-destructive">
              {{ renameError }}
            </p>
          </div>

          <div class="flex shrink-0 items-center gap-1">
            <button
              type="button"
              class="cursor-pointer rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              title="重命名"
              @click.stop="startRename(c.id, c.name)"
            >
              <Icon name="edit" class="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              class="cursor-pointer rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-destructive"
              title="删除收藏夹"
              @click.stop="remove(c.id, c.name)"
            >
              <Icon name="trash" class="h-3.5 w-3.5" />
            </button>
          </div>
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
